# Shared helpers for backup/restore scripts. Sourced, not executed.
#
# Connection uses the standard libpq variables: PGHOST, PGPORT, PGUSER, PGPASSWORD,
# PGDATABASE (default: resolveai). Set PG_CONTAINER=<name> to run the Postgres client
# tools inside that container instead (no local install needed, e.g. resolveai-db-1).

set -euo pipefail

: "${PGDATABASE:=resolveai}"
: "${PGUSER:=resolveai}"
export PGDATABASE PGUSER

pg() {
    if [[ -n "${PG_CONTAINER:-}" ]]; then
        docker exec -i \
            -e PGUSER="$PGUSER" -e PGDATABASE="$PGDATABASE" -e PGPASSWORD="${PGPASSWORD:-}" \
            "$PG_CONTAINER" "$@"
    else
        "$@"
    fi
}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
