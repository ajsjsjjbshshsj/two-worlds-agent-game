#!/usr/bin/env bash
set -euo pipefail
umask 077

# shellcheck source=scripts/mongodb-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/mongodb-common.sh"

[[ $# = 1 ]] || fail "Usage: mongodb-restore.sh BACKUP_BUNDLE"
target=${MONGO_RESTORE_DATABASE:-}
require_database "$target"
[[ $target =~ ^twoworlds_restore_[a-zA-Z0-9_-]+$ ]] ||
    fail "Choose a new twoworlds_restore_* database. Overwriting existing data is unsupported."
[[ $target != "${MONGO_DATABASE:-}" ]] || fail "Target is the configured application database."
configure_tools

bundle=$1
[[ -d $bundle && ! -L $bundle ]] || fail "Backup bundle must be an existing directory."
work=$(mktemp -d) || fail "Cannot allocate restore staging."
trap 'rm -rf -- "$work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Make one private snapshot so rotation or later changes cannot alter the validated input.
if [[ -e $bundle/archive.gz.age || -L $bundle/archive.gz.age ]]; then
    [[ ! -e $bundle/archive.gz && ! -L $bundle/archive.gz ]] ||
        fail "Backup bundle contains two archive variants."
    archive=archive.gz.age
else
    archive=archive.gz
fi
cp -P -- "$bundle/source-db" "$bundle/SHA256SUMS" "$bundle/$archive" "$work/" 2>/dev/null ||
    fail "Backup bundle is incomplete or unreadable."
[[ $(bundle_archive "$work") = "$archive" ]] ||
    fail "Backup checksum validation failed."
source_db=$(<"$work/source-db")
require_database "$source_db"
[[ $source_db != "$target" ]] || fail "Restore requires a separate target database."

if [[ $archive = *.age ]]; then
    identity=${MONGO_RESTORE_IDENTITY_FILE:-}
    [[ -n $identity && -f $identity && -r $identity ]] ||
        fail "Set MONGO_RESTORE_IDENTITY_FILE to a trusted age identity."
    command -v age >/dev/null || fail "Install age to decrypt this backup."
fi

stream_archive() {
    if [[ $archive = *.age ]]; then
        age -d -i "$identity" "$work/$archive" 2>/dev/null
    else
        cat -- "$work/$archive"
    fi
}

# Finish decryption and compressed integrity checks before contacting the destination.
stream_archive | gzip -t 2>/dev/null || fail "Archive decryption or gzip verification failed."

restore() {
    docker exec -i "$MONGO_CONTAINER" mongorestore --quiet "${connection[@]}" \
        --archive --gzip --stopOnError --nsInclude "$source_db.*" \
        --nsFrom "$source_db.*" --nsTo "$target.*" "$@" >/dev/null 2>&1
}

# Validate the official archive structure and source namespace before any write.
stream_archive | restore --dryRun || fail "MongoDB dry-run failed. Check the archive and destination connection."
if docker exec -e "TW_TOOLS_CONFIG=$tools_config" -e "TW_RESTORE_DB=$target" \
    "$MONGO_CONTAINER" mongosh --nodb --quiet --eval '
        const path = process.env.TW_TOOLS_CONFIG;
        const uri = path ? JSON.parse(require("fs").readFileSync(path, "utf8")).uri : "mongodb://127.0.0.1";
        if (typeof uri !== "string" || !uri.startsWith("mongodb")) quit(4);
        const target = new Mongo(uri).getDB(process.env.TW_RESTORE_DB);
        if (target.getCollectionInfos().length !== 0) quit(42);
    ' >/dev/null 2>&1; then
    :
else
    status=$?
    [[ $status != 42 ]] || fail "Target database already contains collections. Choose a new database."
    fail "Cannot verify destination. Check connection and listCollections permissions."
fi

stream_archive | restore || fail "Restore failed. Leave this target isolated and inspect it before retrying into a new database."
printf 'Restore completed into %s\n' "$target"
