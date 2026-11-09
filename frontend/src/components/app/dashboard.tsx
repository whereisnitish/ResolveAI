"use client";

import { CheckCircle2, Circle, Copy, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgMembers, useWorkspaceDetail } from "@/lib/queries";
import { ORG_ROLE_LABELS, WORKSPACE_ROLE_LABELS } from "@/lib/types";

interface ChecklistItem {
  label: string;
  description: string;
  done: boolean;
  href?: string;
  cta?: string;
  upcoming?: boolean;
}

export function Dashboard() {
  const { me, workspace, organization, canOrg } = useApp();
  const detail = useWorkspaceDetail(workspace?.id);
  const members = useOrgMembers(organization?.id, canOrg("org.members.view"));
  const firstName = me.user.full_name.split(" ")[0] || "there";

  const checklist: ChecklistItem[] = [
    {
      label: "Verify your email",
      description: "Confirms you own this address and secures account recovery.",
      done: me.user.email_verified,
    },
    {
      label: "Invite your team",
      description: "Bring teammates into your workspace with the right roles.",
      done: (members.data?.count ?? 0) > 1,
      href: "/app/team",
      cta: "Invite",
    },
    {
      label: "Review workspace settings",
      description: "Name your workspace and set its timezone for reporting.",
      done: Boolean(detail.data && detail.data.timezone !== "UTC"),
      href: "/app/settings?tab=workspace",
      cta: "Open settings",
    },
    {
      label: "Install the chat widget",
      description: "Add one script tag to your site to start receiving conversations.",
      done: false,
      upcoming: true,
    },
    {
      label: "Train your first AI agent",
      description: "Connect knowledge sources so AI can answer common questions.",
      done: false,
      upcoming: true,
    },
  ];
  const completed = checklist.filter((i) => i.done).length;

  const copyPublicId = async () => {
    if (!detail.data) return;
    try {
      await navigator.clipboard.writeText(detail.data.public_id);
      toast.success("Workspace ID copied");
    } catch {
      toast.error("Couldn't copy to clipboard");
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={`Welcome, ${firstName}`} description={`Here's how ${workspace?.name} is set up.`} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Get started</CardTitle>
            <CardDescription>
              {completed} of {checklist.length} steps complete
            </CardDescription>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${(completed / checklist.length) * 100}%` }}
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y">
              {checklist.map((item) => (
                <li key={item.label} className="flex items-start gap-3 px-6 py-4">
                  {item.done ? (
                    <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" aria-label="Done" />
                  ) : (
                    <Circle className="mt-0.5 size-5 shrink-0 text-muted-foreground/50" aria-label="Not done" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className={item.done ? "text-sm font-medium text-muted-foreground line-through" : "text-sm font-medium"}>
                      {item.label}
                    </p>
                    <p className="text-sm text-muted-foreground">{item.description}</p>
                  </div>
                  {item.upcoming ? (
                    <Badge variant="secondary">Coming soon</Badge>
                  ) : !item.done && item.href ? (
                    <Button variant="outline" size="sm" render={<Link href={item.href} />}>
                      {item.cta}
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <div className="grid content-start gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Workspace</CardTitle>
              <CardDescription>{organization?.name}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              <Row label="Name" value={workspace?.name} />
              <Row label="Your role" value={workspace ? WORKSPACE_ROLE_LABELS[workspace.role] : "—"} />
              <Row label="Organization role" value={organization ? ORG_ROLE_LABELS[organization.role] : "—"} />
              <Row label="Timezone" value={detail.data?.timezone} loading={detail.isPending} />
              <div className="grid gap-1">
                <span className="text-muted-foreground">Widget workspace ID</span>
                {detail.isPending ? (
                  <Skeleton className="h-8 w-full" />
                ) : (
                  <div className="flex items-center gap-2">
                    <code className="flex-1 truncate rounded-md bg-muted px-2 py-1.5 font-mono text-xs">
                      {detail.data?.public_id}
                    </code>
                    <Button variant="ghost" size="icon-sm" onClick={copyPublicId} aria-label="Copy workspace ID">
                      <Copy />
                    </Button>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex gap-3 pt-6 text-sm">
              <ShieldCheck className="size-5 shrink-0 text-primary" />
              <p className="text-muted-foreground">
                Data in this workspace is isolated from your other workspaces and organizations. Access is checked on
                every request.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, loading }: { label: string; value?: string; loading?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      {loading ? <Skeleton className="h-4 w-24" /> : <span className="truncate font-medium">{value ?? "—"}</span>}
    </div>
  );
}
