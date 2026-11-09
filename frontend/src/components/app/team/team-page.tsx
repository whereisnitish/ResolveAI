"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, ShieldAlert, Users } from "lucide-react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { initials } from "@/components/app/app-shell";
import { PageHeader } from "@/components/app/page-header";
import { assignableOrgRoles, InviteDialog } from "@/components/app/team/invite-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { queryKeys, useOrgAuditLogs, useOrgInvitations, useOrgMembers } from "@/lib/queries";
import { ORG_ROLE_LABELS, type OrganizationMembership, type OrganizationRole } from "@/lib/types";

const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function TeamPage() {
  const { organization, canOrg } = useApp();
  if (!organization) return null;
  const canView = canOrg("org.members.view");
  const canManage = canOrg("org.members.manage");
  const canAudit = canOrg("org.audit.view");

  if (!canView) {
    return (
      <div className="mx-auto max-w-5xl">
        <PageHeader title="Team" />
        <EmptyState
          icon={<ShieldAlert className="size-6" />}
          title="You don't have access to team management"
          description="Ask an organization owner or admin if you need to manage members."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Team"
        description={`People with access to ${organization.name}.`}
        actions={canManage ? <InviteDialog /> : null}
      />
      <Tabs defaultValue="members">
        <TabsList>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="invitations">Pending invitations</TabsTrigger>
          {canAudit ? <TabsTrigger value="audit">Audit log</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="members" className="mt-4">
          <MembersTable orgId={organization.id} canManage={canManage} actorRole={organization.role} />
        </TabsContent>
        <TabsContent value="invitations" className="mt-4">
          <InvitationsTable orgId={organization.id} canManage={canManage} />
        </TabsContent>
        {canAudit ? (
          <TabsContent value="audit" className="mt-4">
            <AuditLogTable orgId={organization.id} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

function MembersTable({
  orgId,
  canManage,
  actorRole,
}: {
  orgId: string;
  canManage: boolean;
  actorRole: OrganizationRole;
}) {
  const { me } = useApp();
  const queryClient = useQueryClient();
  const members = useOrgMembers(orgId);
  const assignable = assignableOrgRoles(actorRole);

  const update = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Pick<OrganizationMembership, "role" | "is_active">> }) =>
      api.patch<OrganizationMembership>(`organizations/${orgId}/members/${id}`, data),
    onSuccess: () => {
      toast.success("Member updated");
      void queryClient.invalidateQueries({ queryKey: queryKeys.orgMembers(orgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Update failed"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`organizations/${orgId}/members/${id}`),
    onSuccess: () => {
      toast.success("Member removed");
      void queryClient.invalidateQueries({ queryKey: queryKeys.orgMembers(orgId) });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Removal failed"),
  });

  if (members.isPending) return <TableSkeleton />;
  if (members.isError) return <ErrorState message={members.error.message} onRetry={() => members.refetch()} />;

  return (
    <Card className="overflow-hidden p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">Member</TableHead>
            <TableHead>Role</TableHead>
            <TableHead className="hidden sm:table-cell">Status</TableHead>
            <TableHead className="hidden md:table-cell">Joined</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.data.results.map((m) => {
            const isSelf = m.user.id === me.user.id;
            const ownerProtected = m.role === "owner" && actorRole !== "owner";
            const manageable = canManage && !ownerProtected;
            return (
              <TableRow key={m.id}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-3">
                    <Avatar className="size-8">
                      <AvatarFallback className="text-xs">{initials(m.user.full_name || m.user.email)}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {m.user.full_name || m.user.email}
                        {isSelf ? <span className="ml-2 text-xs font-normal text-muted-foreground">(you)</span> : null}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">{m.user.email}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant={m.role === "owner" ? "default" : "secondary"}>{ORG_ROLE_LABELS[m.role]}</Badge>
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {m.is_active ? (
                    <span className="text-sm text-emerald-700">Active</span>
                  ) : (
                    <span className="text-sm text-muted-foreground">Deactivated</span>
                  )}
                </TableCell>
                <TableCell className="hidden text-sm text-muted-foreground md:table-cell">
                  {dateFmt.format(new Date(m.created_at))}
                </TableCell>
                <TableCell className="pr-4 text-right">
                  {manageable ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={<Button variant="ghost" size="icon-sm" aria-label={`Manage ${m.user.email}`} />}
                      >
                        <MoreHorizontal />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48">
                        <DropdownMenuGroup>
                          <DropdownMenuLabel>Change role</DropdownMenuLabel>
                          {assignable
                            .filter((role) => role !== m.role)
                            .map((role) => (
                              <DropdownMenuItem
                                key={role}
                                onClick={() => update.mutate({ id: m.id, data: { role } })}
                              >
                                Make {ORG_ROLE_LABELS[role]}
                              </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => update.mutate({ id: m.id, data: { is_active: !m.is_active } })}>
                          {m.is_active ? "Deactivate" : "Reactivate"}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => {
                            if (window.confirm(`Remove ${m.user.email} from the organization?`)) remove.mutate(m.id);
                          }}
                        >
                          Remove
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

function InvitationsTable({ orgId, canManage }: { orgId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const invitations = useOrgInvitations(orgId);
  const revoke = useMutation({
    mutationFn: (id: string) => api.post(`organizations/${orgId}/invitations/${id}/revoke`),
    onSuccess: () => {
      toast.success("Invitation revoked");
      void queryClient.invalidateQueries({ queryKey: queryKeys.orgInvitations(orgId) });
    },
    onError: (error) => toast.error(error.message),
  });

  if (invitations.isPending) return <TableSkeleton />;
  if (invitations.isError) return <ErrorState message={invitations.error.message} onRetry={() => invitations.refetch()} />;
  if (invitations.data.results.length === 0) {
    return (
      <EmptyState
        icon={<Users className="size-6" />}
        title="No pending invitations"
        description={canManage ? "Invite teammates to collaborate in your workspaces." : "There's nobody waiting to join."}
      />
    );
  }

  return (
    <Card className="overflow-hidden p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead className="hidden sm:table-cell">Expires</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {invitations.data.results.map((inv) => (
            <TableRow key={inv.id}>
              <TableCell className="pl-4 text-sm font-medium">{inv.email}</TableCell>
              <TableCell>
                <Badge variant="secondary">{ORG_ROLE_LABELS[inv.role]}</Badge>
              </TableCell>
              <TableCell className="hidden text-sm text-muted-foreground sm:table-cell">
                {inv.is_expired ? "Expired" : dateFmt.format(new Date(inv.expires_at))}
              </TableCell>
              <TableCell className="pr-4 text-right">
                {canManage ? (
                  <Button variant="ghost" size="sm" onClick={() => revoke.mutate(inv.id)} disabled={revoke.isPending}>
                    Revoke
                  </Button>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function AuditLogTable({ orgId }: { orgId: string }) {
  const logs = useOrgAuditLogs(orgId);
  if (logs.isPending) return <TableSkeleton />;
  if (logs.isError) return <ErrorState message={logs.error.message} onRetry={() => logs.refetch()} />;
  if (logs.data.results.length === 0) {
    return <EmptyState icon={<ShieldAlert className="size-6" />} title="No activity yet" description="" />;
  }
  return (
    <Card className="overflow-hidden p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">Action</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead className="hidden md:table-cell">IP</TableHead>
            <TableHead className="pr-4 text-right">When</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {logs.data.results.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell className="pl-4 font-mono text-xs">{entry.action}</TableCell>
              <TableCell className="text-sm">{entry.actor_email || "system"}</TableCell>
              <TableCell className="hidden font-mono text-xs text-muted-foreground md:table-cell">
                {entry.ip_address ?? "—"}
              </TableCell>
              <TableCell className="pr-4 text-right text-sm text-muted-foreground">
                {dateTimeFmt.format(new Date(entry.created_at))}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

export function EmptyState({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground">{icon}</div>
      <p className="font-medium">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-6 py-8 text-center text-sm">
      <p className="font-medium text-destructive">Couldn&apos;t load this data</p>
      <p className="mt-1 text-muted-foreground">{message}</p>
      <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="grid gap-2 rounded-xl border p-4" aria-busy="true" aria-label="Loading">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}
