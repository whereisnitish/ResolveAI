"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";
import type { Me, MeOrganization, MeWorkspace } from "@/lib/types";

const WORKSPACE_STORAGE_KEY = "resolveai.currentWorkspaceId";

interface AppContextValue {
  me: Me;
  workspace: MeWorkspace | null;
  organization: MeOrganization | null;
  setWorkspaceId: (id: string) => void;
  /** UX gating only — the backend enforces every permission. */
  canWorkspace: (perm: string) => boolean;
  canOrg: (perm: string) => boolean;
}

const AppContext = createContext<AppContextValue | null>(null);

function readStoredWorkspace(): string | null {
  try {
    return window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeWorkspace(id: string) {
  try {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, id);
  } catch {
    // Storage unavailable (private mode); selection just won't persist.
  }
}

export function AppProvider({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const meQuery = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  // Lazy init is hydration-safe: the selection only affects output after /me
  // has loaded on the client (server and first client render show the fallback).
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : readStoredWorkspace(),
  );

  // Stale or invalid session: clear the cookie server-side, then go to login.
  useEffect(() => {
    if (meQuery.error instanceof ApiError && (meQuery.error.status === 401 || meQuery.error.status === 403)) {
      api
        .post("auth/logout")
        .catch(() => undefined)
        .finally(() => {
          queryClient.clear();
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        });
    }
  }, [meQuery.error, pathname, queryClient, router]);

  const setWorkspaceId = useCallback(
    (id: string) => {
      storeWorkspace(id);
      // Workspace-scoped query keys include the workspace id, so cached data
      // can never bleed between workspaces when switching.
      setSelectedId(id);
    },
    [],
  );

  const value = useMemo<AppContextValue | null>(() => {
    const me = meQuery.data;
    if (!me) return null;
    const workspace =
      me.workspaces.find((w) => w.id === selectedId) ??
      me.workspaces.find((w) => w.is_default) ??
      me.workspaces[0] ??
      null;
    const organization =
      (workspace && me.organizations.find((o) => o.id === workspace.organization_id)) ?? me.organizations[0] ?? null;
    return {
      me,
      workspace,
      organization,
      setWorkspaceId,
      canWorkspace: (perm) => Boolean(workspace?.permissions.includes(perm)),
      canOrg: (perm) => Boolean(organization?.permissions.includes(perm)),
    };
  }, [meQuery.data, selectedId, setWorkspaceId]);

  if (!value) {
    const isAuthError =
      meQuery.error instanceof ApiError && (meQuery.error.status === 401 || meQuery.error.status === 403);
    if (meQuery.isError && !isAuthError) {
      return (
        <div className="flex min-h-screen items-center justify-center p-6 text-center">
          <div className="max-w-sm space-y-2">
            <p className="font-medium">We couldn&apos;t load your workspace.</p>
            <p className="text-sm text-muted-foreground">{meQuery.error.message}</p>
            <button className="text-sm font-medium text-primary hover:underline" onClick={() => meQuery.refetch()}>
              Try again
            </button>
          </div>
        </div>
      );
    }
    return <>{fallback}</>;
  }
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>");
  return ctx;
}
