"use client";

import { Bot, Plus, Rocket } from "lucide-react";
import Link from "next/link";

import { useApp } from "@/components/app/app-context";
import { ListSkeleton, relativeTime } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAgents } from "@/lib/platform";

export function AgentsList() {
  const { workspace, canWorkspace } = useApp();
  const agents = useAgents(workspace!.id);
  const canManage = canWorkspace("ai_agents.manage");

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="AI Agents"
        description="AI agents answer website visitors from your knowledge and hand off to your team when needed."
        actions={
          canManage ? (
            <Button render={<Link href="/app/ai-agents/new" />}>
              <Plus /> New agent
            </Button>
          ) : null
        }
      />
      {agents.isPending ? (
        <ListSkeleton rows={3} />
      ) : agents.isError ? (
        <ErrorState message={agents.error.message} onRetry={() => agents.refetch()} />
      ) : agents.data.length === 0 ? (
        <EmptyState
          icon={<Bot className="size-6" />}
          title="No AI agents yet"
          description="Create an agent, add knowledge, test it in the playground, then deploy it to your website widget."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {agents.data.map((a) => (
            <Link key={a.id} href={`/app/ai-agents/${a.id}`}>
              <Card className="h-full p-4 transition-colors hover:bg-muted/40">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-2 text-primary">
                    <Bot className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate font-medium">{a.name}</p>
                      {a.is_deployed ? (
                        <Badge className="gap-1">
                          <Rocket className="size-3" /> Live on widget
                        </Badge>
                      ) : !a.enabled ? (
                        <Badge variant="secondary">Disabled</Badge>
                      ) : null}
                    </div>
                    <p className="line-clamp-2 text-sm text-muted-foreground">{a.description || a.instructions}</p>
                    <p className="mt-2 font-mono text-xs text-muted-foreground">
                      {a.provider} · {a.model} · updated {relativeTime(a.updated_at)}
                    </p>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
