#!/usr/bin/env bash
# Restore a backup into a NEW database (never over an existing one).
#
#   infrastructure/scripts/restore.sh <dump-file> <target-db>
#
# The target database must not exist: restoring is a deliberate, two-step operation
# (restore → verify → repoint the app via POSTGRES_DB/DATABASE_URL), so a typo can
# never overwrite live data. The pgvector/citext/pg_trgm extensions are created first.
source "$(dirname "$0")/pg-common.sh"

dump="${1:?usage: restore.sh <dump-file> <target-db>}"
target="${2:?usage: restore.sh <dump-file> <target-db>}"

if [[ ! "$target" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
    log "invalid target database name: $target"
    exit 2
fi
if [[ -f "$dump.sha256" ]] && [[ "$(sha256 "$dump")" != "$(cat "$dump.sha256")" ]]; then
    log "checksum mismatch for $dump — refusing to restore"
    exit 1
fi
exists="$(pg psql -X -tAc "SELECT 1 FROM pg_database WHERE datname = '$target'" postgres)"
if [[ "$exists" == "1" ]]; then
    log "database $target already exists — refusing to overwrite. Pick a new name."
    exit 1
fi

log "restore start dump=$dump target=$target"
pg createdb "$target"
pg psql -X -q -v ON_ERROR_STOP=1 -d "$target" \
    -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS citext; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
pg pg_restore --no-owner --no-acl --exit-on-error --dbname="$target" <"$dump"
log "restore ok target=$target"
