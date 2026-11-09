# Coding conventions

## Backend (Python / Django)
* Python 3.13, type hints on public functions; `ruff check` + `ruff format` (line length 120).
* Layering: `views` (HTTP only) → `services` (business logic, transactions, audit) → `models`.
* Every tenant endpoint uses `WorkspaceScopedViewMixin`/`OrganizationScopedViewMixin` and declares
  `permission_by_action`. Querysets filter by `self.workspace` / `self.organization`.
* New permissions go in `common/rbac.py` only.
* Tenant-owned models inherit `apps.workspaces.models.WorkspaceOwnedModel`.
* Raise `common.exceptions.ServiceError` / `ConflictError` with a stable `code` for business errors.
* Security-sensitive actions call `apps.audit.services.record(...)`.
* Emails/slow work: `common.email.queue_email` or Celery tasks, scheduled with `on_commit`.
* Tests: pytest, factories in `tests/factories.py`; every new endpoint gets isolation tests
  (other tenant → 404, insufficient role → 403, anonymous → 403).

## Frontend (TypeScript / Next.js 16)
* Read `frontend/AGENTS.md` and the bundled docs in `node_modules/next/dist/docs/` before using
  unfamiliar Next APIs — v16 differs from older versions (`proxy.ts`, async params,
  `cacheComponents`).
* All HTTP through `src/lib/api.ts`; server state through TanStack Query hooks in `src/lib/queries.ts`
  with query keys that include the tenant id.
* Forms: react-hook-form + zod schemas in `src/lib/validation.ts`; map server errors with
  `applyApiErrors`.
* UI: shadcn/ui on Base UI — compose triggers with `render={<Button />}`; `DropdownMenuLabel`
  must sit inside `DropdownMenuGroup`.
* Components reading `useSearchParams` are wrapped in `<Suspense>`.
* Every data view handles loading, empty and error states.
* `npm run lint`, `npm run typecheck`, `npm test` must pass.

## Git
* Never commit `.env` or secrets. Conventional, descriptive commit messages.
