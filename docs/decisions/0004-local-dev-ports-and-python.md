# ADR-0004: Local development defaults (Python 3.13, ports 5433/6380)

* Status: Accepted · Date: 2026-11-09

## Context
The dev machine has Python 3.15 (default) and 3.13; several binary packages (psycopg, argon2,
pgvector tooling) ship wheels for 3.13 first. Another local stack already binds 5432 and 6379.

## Decision
* Backend targets **Python 3.13** (venv and Docker image `python:3.13-slim`).
* Docker Compose publishes Postgres on host **5433** and Redis on **6380** by default
  (`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` override). Inside the Compose network services still
  use 5432/6379.

## Consequences
* No clashes with other local projects. Production uses managed services, unaffected.
