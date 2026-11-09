# Runbook

Each entry gives the symptom, how to diagnose it and the fix. Run commands inside the backend container (`docker compose exec backend …`, or ECS Exec on AWS).

## API returns 503 on `/api/v1/health/ready/`

The response body names the failing dependency (`database`, `cache` or `broker`).

* **database:** check RDS status, connections and CPU. Look for `PoolTimeout` or `too many connections` in the logs. Then lower `DB_POOL_MAX_SIZE`, scale down tasks, or add RDS Proxy.
* **cache / broker:** check ElastiCache status and memory. Redis must run `noeviction`. A full Redis rejects writes, so free memory or scale the node.

## AI agent not replying ("everything goes to humans")

1. Check the conversation's `ai_state` and the AI executions list (*AI agents → executions*), which shows the decision and the reason.
2. Common reasons:
   * **Agent not deployed / paused:** expected behaviour.
   * **No provider key:** in production there is no mock fallback. `check --deploy` warns with W101. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
   * **Low confidence or no knowledge match:** add or re-index knowledge sources.
   * **Refusal or provider error:** a transient provider outage. Executions record `error`. The fallback model handles the Anthropic overload path.
   * **Plan limit reached:** the AI resolutions quota is exhausted (402 `plan_limit_reached`). Upgrade the plan.
3. Celery backlog: `celery -A config inspect active`. Check the queue depth (`redis-cli -n 1 LLEN celery`).

## Users can't log in

* `429 login_locked`: per-account lockout after `LOGIN_LOCKOUT_THRESHOLD` failures within `LOGIN_LOCKOUT_WINDOW_SECONDS`. It clears automatically. To clear it now: `python manage.py shell -c "from apps.accounts import lockout; lockout.reset('user@example.com')"`. Check the audit log (`user.login_failed`, `locked: true`) for a credential-stuffing pattern. If you find one, add a WAF rule.
* `403 CSRF`: `CSRF_TRUSTED_ORIGINS` must contain the exact dashboard origin (scheme, host and port).
* Every user logged out at once: `DJANGO_SECRET_KEY` changed, or the session table was cleared.

## Realtime (inbox not updating live)

* The browser console shows WebSocket close codes. `4401` means the session expired, and `4403` means the origin is not in `CSRF_TRUSTED_ORIGINS`.
* Check that the ALB or nginx forwards `Upgrade`, and that the idle timeout is at least 300s.
* Check the channel layer Redis (`CHANNEL_LAYER_REDIS_URL`). The UI polls as a fallback, so messages are never lost, only delayed.

## Billing webhooks failing

* Check `billing_webhookevent` rows with status `failed` and their `error`, or the Django admin.
* A signature error usually means `STRIPE_WEBHOOK_SECRET` or `RAZORPAY_WEBHOOK_SECRET` doesn't match the dashboard endpoint secret.
* Replay is safe because events are idempotent on `(provider, event_id)`. Resend from the Stripe or Razorpay dashboard.

## Integration (outgoing webhook) disabled

An integration auto-disables after 50 consecutive failures. Fix the receiver, then re-enable it in *Integrations*. Deliveries are logged per attempt.

## Database migration takes too long or locks

Migrations run with `DB_STATEMENT_TIMEOUT_MS=0`, which the `migrate` service sets. For large tables:

* create indexes `CONCURRENTLY` (a separate non-atomic migration)
* add columns as nullable or with a database default
* backfill in batches from a management command

## Suspected data tampering

The audit log and usage ledger can't be modified, even through raw SQL: triggers raise `append-only: UPDATE rejected`. If you see that error in the logs, **investigate**: something tried to rewrite history. Correlate the request with its `request_id`.

## Secrets rotation

| Secret | How | Impact |
|---|---|---|
| `DJANGO_SECRET_KEY` | Set the new value and redeploy. You can keep the old value in `SECRET_KEY_FALLBACKS` for a grace period | Without fallbacks, sessions and reset links are invalidated |
| Provider API keys (Anthropic, OpenAI, Stripe, Razorpay, SMTP) | Rotate in the provider console, update Secrets Manager, redeploy | None |
| Webhook secrets | Rotate at the provider and in the environment together | Webhooks fail in between |
| `FIELD_ENCRYPTION_KEY` | Needs a re-encryption migration (decrypt with the old key, encrypt with the new). **Not a hot swap** | Integration URLs unreadable if swapped naively |
| Database password | RDS rotation with Secrets Manager. Restart tasks | Brief connection errors during restart |

## Useful commands

```bash
python manage.py check --deploy                # config sanity
python manage.py showmigrations | grep '\[ \]' # pending migrations
python manage.py sendtestemail you@example.com # SMTP check
celery -A config inspect ping                   # workers alive
celery -A config inspect active                 # running tasks
```
