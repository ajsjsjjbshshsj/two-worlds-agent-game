#!/bin/sh
set -eu

host=${TWOWORLDS_PLAYTEST_HOST:-}
if ! printf '%s' "$host" | LC_ALL=C grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$' ||
   [ "${#host}" -gt 253 ] || [ "$(printf '%s' "$host" | wc -l)" -ne 0 ]; then
    printf '%s\n' 'Invalid Playtest HTTPS hostname' >&2
    exit 1
fi

bind=${TWOWORLDS_PLAYTEST_BIND_IP:-127.0.0.1}
case "$bind" in
    0.0.0.0|*:*|\*) printf '%s\n' 'Playtest requires a specific IPv4 bind address' >&2; exit 1 ;;
esac
if [ "${TWOWORLDS_PLAYTEST_CONTENT_PURPOSE:-participant}" = internal-drill ] &&
   [ "$bind" != 127.0.0.1 ]; then
    printf '%s\n' 'Internal Playtest drills must bind to loopback' >&2
    exit 1
fi

# Restrict this file to comma-separated, exact IPv4 addresses from the VPN.
# Read one untrusted string and write only canonical addresses as geo entries.
allowlist=${TWOWORLDS_PLAYTEST_ALLOWLIST:-}
if [ "${#allowlist}" -gt 8192 ] ||
   ! printf '%s\n' "$allowlist" | LC_ALL=C awk -F, '
    NR != 1 { exit 1 }
    {
        if (!NF) exit 1
        for (i = 1; i <= NF; i++) {
            if (split($i, octet, /\./) != 4 || $i == "0.0.0.0") exit 1
            for (j = 1; j <= 4; j++)
                if (octet[j] !~ /^(0|[1-9][0-9]?[0-9]?)$/ || octet[j] > 255) exit 1
            if (!seen[$i]++) print $i "/32 1;"
        }
    }
' > /tmp/playtest-allowlist.conf; then
    printf '%s\n' 'Playtest requires an explicit list of IPv4 source addresses' >&2
    exit 1
fi

envsubst '${TWOWORLDS_PLAYTEST_HOST}' < /etc/twoworlds/gateway.conf.template > /tmp/nginx.conf
if ! nginx -t -c /tmp/nginx.conf >/dev/null 2>&1; then
    printf '%s\n' 'Playtest TLS or gateway configuration is invalid' >&2
    exit 1
fi
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
