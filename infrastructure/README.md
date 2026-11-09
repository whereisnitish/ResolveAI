# Infrastructure

| Path | Purpose |
|---|---|
| `nginx/nginx.conf` | Single-host ingress. Routes `/api`, `/ws` and `/static` to Django and everything else to Next.js. Also provides JSON access logs, gzip, edge rate limits and WebSocket upgrade |
| `scripts/backup.sh` | Runs `pg_dump` (custom format), checks the archive's integrity, writes a checksum and prunes old dumps |
| `scripts/restore.sh` | Restores into a **new** database and refuses to overwrite an existing one |
| `scripts/verify-backup.sh` | Restores into a throwaway database, compares row counts, checks triggers and indexes, then drops it |

The production stack is defined in `../docker-compose.prod.yml`. The AWS reference architecture is in
[`docs/operations/DEPLOYMENT.md`](../docs/operations/DEPLOYMENT.md).
