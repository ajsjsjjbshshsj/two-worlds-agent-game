#!/bin/sh
set -eu

# Interpolate one DNS name into the Nginx configuration.
if ! printf '%s' "${TWOWORLDS_PUBLIC_HOST:-}" | LC_ALL=C grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$' ||
   [ "${#TWOWORLDS_PUBLIC_HOST}" -gt 253 ] ||
   [ "$(printf '%s' "$TWOWORLDS_PUBLIC_HOST" | wc -l)" -ne 0 ]; then
    printf '%s\n' 'A valid TWOWORLDS_PUBLIC_HOST is required' >&2
    exit 1
fi

envsubst '${TWOWORLDS_PUBLIC_HOST}' < /etc/twoworlds/site.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
