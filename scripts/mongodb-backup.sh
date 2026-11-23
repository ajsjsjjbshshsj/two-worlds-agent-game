#!/usr/bin/env bash
set -euo pipefail
umask 077

# shellcheck source=scripts/mongodb-common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/mongodb-common.sh"

[[ $# = 0 ]] || fail "Use environment variables to configure this command."
require_database "${MONGO_DATABASE:-}"
[[ ${MONGO_BACKUP_QUIESCED:-} = 1 ]] ||
    fail "Pause all writes to the standalone database and set MONGO_BACKUP_QUIESCED=1."
configure_tools

retention=${MONGO_BACKUP_RETENTION_DAYS:-30}
[[ $retention =~ ^(0|[1-9][0-9]{0,3})$ ]] || fail "Use 0–9999 retention days."
root=${MONGO_BACKUP_DIR:-./backups}
mkdir -p -- "$root" 2>/dev/null || fail "Cannot create backup directory."
root=$(realpath -e -- "$root") || fail "Cannot resolve backup directory."
[[ -d $root && -O $root && $(stat -c %a -- "$root") = 700 && -w $root ]] ||
    fail "Use a writable, owner-only (0700) backup directory."
[[ ! -L $root/.backup.lock ]] || fail "Invalid backup lock."
exec 9>>"$root/.backup.lock"
flock 9 || fail "Cannot lock backup directory."

recipient=${MONGO_BACKUP_RECIPIENT:-}
if [[ -n $recipient ]]; then
    command -v age >/dev/null || fail "Install age for encrypted backups."
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
staging=$(mktemp -d "$root/.staging-$stamp-XXXXXXXX") || fail "Cannot allocate staging directory."
verifier=
cleanup() {
    if [[ -n $verifier ]]; then
        kill "$verifier" 2>/dev/null || true
        wait "$verifier" 2>/dev/null || true
    fi
    if [[ -n $staging ]]; then
        rm -rf -- "$staging"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

dump() {
    docker exec "$MONGO_CONTAINER" mongodump --quiet "${connection[@]}" \
        --db "$MONGO_DATABASE" --archive --gzip 2>/dev/null
}

archive=archive.gz
if [[ -n $recipient ]]; then
    archive+=.age
    # Validate the compressed stream without writing a plaintext archive to disk.
    mkfifo -- "$staging/gzip-check"
    gzip -t <"$staging/gzip-check" 2>/dev/null &
    verifier=$!
    if ! dump | tee "$staging/gzip-check" | age -r "$recipient" >"$staging/$archive" 2>/dev/null; then
        fail "Dump or encryption failed. Check MongoDB availability, permissions and the age recipient."
    fi
    wait "$verifier" || fail "Dump did not produce a valid compressed stream."
    verifier=
    rm -- "$staging/gzip-check"
else
    dump >"$staging/$archive" || fail "Dump failed. Check MongoDB availability and permissions."
    gzip -t "$staging/$archive" 2>/dev/null || fail "Dump did not produce a valid compressed archive."
fi

printf '%s\n' "$MONGO_DATABASE" >"$staging/source-db"
(cd -- "$staging" && sha256sum -- source-db "$archive" >SHA256SUMS)
bundle_archive "$staging" >/dev/null || fail "Staged checksum validation failed."
# Flush the archive and its metadata before publishing or removing older bundles.
sync -f "$staging"
bundle="$root/backup-${staging##*/.staging-}"
mv -T -- "$staging" "$bundle"
staging=
sync -f "$root"

if (( retention > 0 )); then
    while IFS= read -r -d '' older; do
        [[ $older != "$bundle" && ${older##*/} =~ ^backup-[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9]{8}$ ]] ||
            continue
        # A replacement must cover the same database and backup format.
        if [[ $(bundle_archive "$older") = "$archive" && $(<"$older/source-db") = "$MONGO_DATABASE" ]]; then
            rm -rf -- "$older"
        fi
    done < <(find "$root" -mindepth 1 -maxdepth 1 -type d -name 'backup-*' \
        -mmin "+$((retention * 1440))" -print0)
fi

printf '%s\n' "$bundle"
