#!/usr/bin/env bash
# Logical backup of the ResolveAI database (pg_dump custom format, compressed).
#
#   infrastructure/scripts/backup.sh <output-dir>
#
# Writes resolveai-<db>-<UTC timestamp>.dump plus a .sha256 checksum, verifies the
# archive is readable (pg_restore --list), and prunes local dumps older than
# RETENTION_DAYS (default 14). Ship <output-dir> to off-site storage (e.g.
# `aws s3 sync <output-dir> s3://<bucket>/db/ --sse aws:kms`) — see docs/operations/BACKUPS.md.
#
# This complements, not replaces, managed point-in-time recovery (RDS PITR).
source "$(dirname "$0")/pg-common.sh"

out_dir="${1:?usage: backup.sh <output-dir>}"
retention_days="${RETENTION_DAYS:-14}"
mkdir -p "$out_dir"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$out_dir/resolveai-${PGDATABASE}-${stamp}.dump"

log "backup start db=$PGDATABASE file=$file"
# --no-owner/--no-acl: restorable into any role layout (e.g. a fresh RDS instance).
pg pg_dump --format=custom --compress=6 --no-owner --no-acl >"$file"

# A dump that pg_restore cannot list is not a backup.
entries="$(pg pg_restore --list <"$file" | grep -c 'TABLE DATA' || true)"
if [[ "$entries" -lt 1 ]]; then
    log "backup FAILED verification: no table data in archive"
    exit 1
fi
sha256 "$file" >"$file.sha256"
log "backup ok size=$(wc -c <"$file") table_data_entries=$entries sha256=$(cat "$file.sha256")"

# Prune only files this script created, only in the output dir.
find "$out_dir" -maxdepth 1 -type f \( -name 'resolveai-*.dump' -o -name 'resolveai-*.dump.sha256' \) \
    -mtime +"$retention_days" -print -delete | sed 's/^/pruned /' >&2 || true
echo "$file"
