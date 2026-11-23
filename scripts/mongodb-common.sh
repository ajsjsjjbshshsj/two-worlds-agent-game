#!/usr/bin/env bash

fail() {
    printf 'MongoDB maintenance: %s\n' "$*" >&2
    exit 1
}

require_database() {
    case "$1" in
        admin|config|local) fail "System databases are outside this workflow." ;;
    esac
    [[ $1 =~ ^[a-zA-Z0-9_-]{1,63}$ ]] || fail "Supply a valid database name."
}

# The callers use connection for the official Database Tools invocation.
# shellcheck disable=SC2034
configure_tools() {
    [[ ${MONGO_CONTAINER:-} =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] ||
        fail "Set MONGO_CONTAINER to the explicit Database Tools container."
    tools_config=${MONGO_TOOLS_CONFIG:-}
    if [[ -n $tools_config ]]; then
        [[ $tools_config = /* ]] || fail "MONGO_TOOLS_CONFIG must be an absolute path inside the container."
        connection=(--config "$tools_config")
    else
        connection=(--host 127.0.0.1)
    fi
}

bundle_archive() {
    local bundle=$1 name file
    [[ -d $bundle && ! -L $bundle ]] || return 1
    if [[ -f $bundle/archive.gz && ! -e $bundle/archive.gz.age && ! -L $bundle/archive.gz.age ]]; then
        name=archive.gz
    elif [[ -f $bundle/archive.gz.age && ! -e $bundle/archive.gz && ! -L $bundle/archive.gz ]]; then
        name=archive.gz.age
    else
        return 1
    fi
    for file in source-db SHA256SUMS "$name"; do
        [[ -s $bundle/$file && -f $bundle/$file && ! -L $bundle/$file ]] || return 1
    done
    # Generate only the two expected entries. Never follow paths from the checksum file.
    (cd -- "$bundle" && sha256sum -- source-db "$name") | cmp -s - "$bundle/SHA256SUMS" ||
        return 1
    printf '%s\n' "$name"
}
