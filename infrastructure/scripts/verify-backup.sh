#!/usr/bin/env bash
# Prove a backup is restorable: restore it into a throwaway database, compare row
# counts of critical tables against the source, check the append-only triggers and
# pgvector index came back, then drop the throwaway database.
#
#   infrastructure/scripts/verify-backup.sh <dump-file>
#
# Run on a schedule (weekly) against the latest dump — an untested backup is a hope.
source "$(dirname "$0")/pg-common.sh"

dump="${1:?usage: verify-backup.sh <dump-file>}"
scratch="resolveai_verify_$(date -u +%Y%m%d%H%M%S)"
source_db="$PGDATABASE"

cleanup() { pg dropdb --if-exists "$scratch" >/dev/null 2>&1 || true; }
trap cleanup EXIT

"$(dirname "$0")/restore.sh" "$dump" "$scratch"

tables=(organizations_organization workspaces_workspace accounts_user conversations_conversation
        conversations_message knowledge_knowledgechunk audit_auditlog billing_usageledger)
status=0
for t in "${tables[@]}"; do
    src="$(pg psql -X -tAc "SELECT count(*) FROM $t" "$source_db")"
    dst="$(pg psql -X -tAc "SELECT count(*) FROM $t" "$scratch")"
    # The source may have grown since the dump; the restore must never have MORE rows.
    if [[ "$dst" -gt "$src" ]]; then status=1; fi
    log "table=$t source=$src restored=$dst"
done

triggers="$(pg psql -X -tAc "SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%_append_only'" "$scratch")"
hnsw="$(pg psql -X -tAc "SELECT count(*) FROM pg_indexes WHERE indexdef ILIKE '%USING hnsw%'" "$scratch")"
migrations="$(pg psql -X -tAc "SELECT count(*) FROM django_migrations" "$scratch")"
log "append_only_triggers=$triggers hnsw_indexes=$hnsw migrations=$migrations"
[[ "$triggers" -ge 2 && "$hnsw" -ge 1 && "$migrations" -ge 1 ]] || status=1

if [[ $status -eq 0 ]]; then log "VERIFY OK: $dump is restorable"; else log "VERIFY FAILED: $dump"; fi
exit $status
