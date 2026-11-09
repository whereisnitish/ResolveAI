"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { AgentForm, NEW_AGENT } from "@/components/app/ai/agent-form";
import { useApp } from "@/components/app/app-context";
import { PageHeader } from "@/components/app/page-header";

export function NewAgent() {
  const { canWorkspace } = useApp();
  return (
    <div className="mx-auto max-w-3xl">
      <Link href="/app/ai-agents" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> AI Agents
      </Link>
      <PageHeader title="New AI agent" description="Configure how the agent answers, then try it in the playground before deploying." />
      {canWorkspace("ai_agents.manage") ? (
        <AgentForm initial={NEW_AGENT} editable />
      ) : (
        <p className="text-sm text-muted-foreground">Only workspace admins can create AI agents.</p>
      )}
    </div>
  );
}
