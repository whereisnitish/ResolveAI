"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  AuditLogEntry,
  Invitation,
  Me,
  Organization,
  OrganizationMembership,
  Paginated,
  Workspace,
  WorkspaceMembership,
} from "@/lib/types";

export const queryKeys = {
  me: ["me"] as const,
  organization: (id: string) => ["organizations", id] as const,
  orgMembers: (id: string) => ["organizations", id, "members"] as const,
  orgInvitations: (id: string) => ["organizations", id, "invitations"] as const,
  orgAuditLogs: (id: string) => ["organizations", id, "audit-logs"] as const,
  workspace: (id: string) => ["workspaces", id] as const,
  workspaceMembers: (id: string) => ["workspaces", id, "members"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.get<Me>("auth/me"),
    staleTime: 60_000,
  });
}

export function useOrganization(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.organization(id ?? ""),
    queryFn: () => api.get<Organization>(`organizations/${id}`),
    enabled: Boolean(id),
  });
}

export function useOrgMembers(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orgMembers(id ?? ""),
    queryFn: () => api.get<Paginated<OrganizationMembership>>(`organizations/${id}/members`, { page_size: 100 }),
    enabled: Boolean(id) && enabled,
  });
}

export function useOrgInvitations(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orgInvitations(id ?? ""),
    queryFn: () =>
      api.get<Paginated<Invitation>>(`organizations/${id}/invitations`, { status: "pending", page_size: 100 }),
    enabled: Boolean(id) && enabled,
  });
}

export function useOrgAuditLogs(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orgAuditLogs(id ?? ""),
    queryFn: () => api.get<Paginated<AuditLogEntry>>(`organizations/${id}/audit-logs`, { page_size: 50 }),
    enabled: Boolean(id) && enabled,
  });
}

export function useWorkspaceDetail(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workspace(id ?? ""),
    queryFn: () => api.get<Workspace>(`workspaces/${id}`),
    enabled: Boolean(id),
  });
}

export function useWorkspaceMembers(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workspaceMembers(id ?? ""),
    queryFn: () => api.get<Paginated<WorkspaceMembership>>(`workspaces/${id}/members`, { page_size: 100 }),
    enabled: Boolean(id),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("auth/logout"),
    onSettled: () => {
      queryClient.clear();
    },
  });
}
