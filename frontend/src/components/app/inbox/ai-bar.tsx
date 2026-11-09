"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Hand, Loader2, Play, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { relativeTime } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import { useAgents } from "@/lib/platform";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATE_COPY: Record<Conversation["ai_state"], { label: string; tone: string }> = {
  active: { label: "AI is handling this conversation", tone: "bg-violet-50 text-violet-900" },
  paused: { label: "A teammate took over — AI is paused", tone: "bg-muted text-muted-foreground" },
  handed_off: { label: "AI handed this conversation to the team", tone: "bg-amber-50 text-amber-900" },
};

/** AI handling status + controls (take over / resume / summarize) for a conversation. */
export function AIBar({ conversation: c, canReply }: { conversation: Conversation; canReply: boolean }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const agents = useAgents(ws);
  const deployed = agents.data?.find((a) => a.is_deployed);

  const op = useMutation({
    mutationFn: (operation: "take-over" | "resume" | "summarize") =>
      api.post<Pick<Conversation, "ai_state" | "ai_summary" | "ai_summary_at">>(`${wsPath(ws)}/conversations/${c.id}/ai/${operation}`),
    onSuccess: (r) => {
      queryClient.setQueryData<Conversation>(wsKeys.conversation(ws, c.id), (old) => (old ? { ...old, ...r } : old));
      void queryClient.invalidateQueries({ queryKey: wsKeys.events(ws, c.id) });
    },
    onError: (e) => toast.error(e.message),
  });

  const showState = Boolean(deployed) || c.ai_state !== "active";
  const copy = STATE_COPY[c.ai_state];

  return (
    <div className="border-b">
      {showState ? (
        <div className={cn("flex flex-wrap items-center gap-2 px-4 py-1.5 text-xs", copy.tone)}>
          <Bot className="size-3.5" />
          <span className="flex-1">
            {copy.label}
            {deployed && c.ai_state === "active" ? ` (${deployed.name})` : ""}
          </span>
          {canReply && c.ai_state === "active" && deployed ? (
            <Button size="xs" variant="outline" onClick={() => op.mutate("take-over")} disabled={op.isPending}>
              <Hand /> Take over
            </Button>
          ) : null}
          {canReply && c.ai_state !== "active" && deployed ? (
            <Button size="xs" variant="outline" onClick={() => op.mutate("resume")} disabled={op.isPending}>
              <Play /> Let AI resume
            </Button>
          ) : null}
          {canReply ? (
            <Button size="xs" variant="ghost" onClick={() => op.mutate("summarize")} disabled={op.isPending}>
              {op.isPending && op.variables === "summarize" ? <Loader2 className="animate-spin" /> : <Sparkles />} Summarize
            </Button>
          ) : null}
        </div>
      ) : canReply ? (
        <div className="flex justify-end px-4 py-1">
          <Button size="xs" variant="ghost" onClick={() => op.mutate("summarize")} disabled={op.isPending}>
            {op.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} Summarize
          </Button>
        </div>
      ) : null}
      {c.ai_summary ? (
        <div className="flex gap-2 border-t bg-violet-50/40 px-4 py-2 text-sm">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-violet-600" />
          <p>
            {c.ai_summary}
            {c.ai_summary_at ? <span className="ml-1 text-xs text-muted-foreground">· {relativeTime(c.ai_summary_at)}</span> : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
