# ADR-0002: Tenant isolation via path-scoped workspaces and a central access layer

* Status: Accepted · Date: 2026-11-09

## Context
Organization is the billing boundary; workspace is the data-isolation boundary. Users can belong
to several organizations and workspaces. Cross-tenant leakage is the most severe failure mode for
this product.

## Options considered
1. **Workspace in a header** (`X-Workspace-ID`) with flat routes (`/api/v1/customers/`).
2. **Workspace in the URL path** (`/api/v1/workspaces/{id}/customers/`).
3. Subdomain per tenant.

## Decision
Option 2. Workspace-scoped resources are nested under `/api/v1/workspaces/{workspace_id}/`.
All access decisions go through `apps/tenancy/access.py`, used by `WorkspaceScopedViewMixin` /
`OrganizationScopedViewMixin`, which:
* resolve membership (user active, org membership active, workspace not archived, effective role),
* return 404 for any tenant the caller cannot access,
* require each view to declare `permission_by_action` (default deny).

Tenant-owned models inherit `WorkspaceOwnedModel`, which carries both `organization` and
`workspace` and derives the organization from the workspace.

## Consequences
* + The tenant is explicit in every URL, log line and cache key; a missing header can't silently
  fall back to a default tenant.
* + One place to audit and test authorization; mutation-tested isolation suite.
* − Slightly longer URLs; frontend must know the current workspace (kept in app context).
* PostgreSQL RLS is **deferred** (Phase 5) as defense in depth: it requires setting a per-request
  `app.workspace_id` GUC and careful handling of Celery/admin/migration connections. The
  application layer is the primary control; RLS will backstop it.
