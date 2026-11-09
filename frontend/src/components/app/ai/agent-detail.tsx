"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, ChevronDown, Loader2, Rocket, Send, Trash2, User } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AgentForm, type AgentDraft } from "@/components/app/ai/agent-form";
import { useApp } from "@/components/app/app-context";
import { ListSkeleton, relativeTime } from "@/components/app/common";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import { useAgent, useAgentExecutions, type AIAgent, type AIExecution, type PlaygroundResult } from "@/lib/platform";
import { cn } from "@/lib/utils";

const TABS = ["settings", "playground", "activity"] as const;

export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>();
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const agent = useAgent(ws, agentId);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = TABS.includes(params.get("tab") as (typeof TABS)[number]) ? (params.get("tab") as string) : "settings";

  if (agent.isPending) return <ListSkeleton rows={6} className="mx-auto max-w-5xl" />;
  if (agent.isError) return <ErrorState message={agent.error.message} onRetry={() => agent.refetch()} />;
  const a = agent.data;
  const canManage = canWorkspace("ai_agents.manage");

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/app/ai-agents" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> AI Agents
      </Link>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/10 p-2.5 text-primary">
            <Bot className="size-6" />
          </div>
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              {a.name} {a.is_deployed ? <Badge>Live on widget</Badge> : null}
            </h1>
            <p className="font-mono text-xs text-muted-foreground">
              {a.provider} · {a.model}
              {a.stats ? ` · ${a.stats.total} conversations handled · ${a.stats.answered} answered · ${a.stats.handed_off} handed off` : ""}
            </p>
          </div>
        </div>
        {canManage ? <AgentActions agent={a} /> : null}
      </div>
      <Tabs value={tab} onValueChange={(v) => router.replace(`${pathname}?tab=${v}`, { scroll: false })}>
        <TabsList>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="playground">Playground</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
        <TabsContent value="settings" className="mt-4">
          <AgentForm initial={a as AgentDraft} agentId={a.id} editable={canManage} />
        </TabsContent>
        <TabsContent value="playground" className="mt-4">
          {canManage ? <Playground agent={a} /> : <p className="text-sm text-muted-foreground">Only workspace admins can use the playground.</p>}
        </TabsContent>
        <TabsContent value="activity" className="mt-4">
          <Activity ws={ws} agentId={a.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AgentActions({ agent }: { agent: AIAgent }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "ai-agents"] });
  const toggle = useMutation({
    mutationFn: () => api.post<AIAgent>(`${wsPath(ws)}/ai-agents/${agent.id}/${agent.is_deployed ? "undeploy" : "deploy"}`),
    onSuccess: (a) => {
      void refresh();
      toast.success(a.is_deployed ? `${a.name} now answers your website visitors` : `${a.name} was taken off the widget`);
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`${wsPath(ws)}/ai-agents/${agent.id}`),
    onSuccess: () => {
      void refresh();
      router.push("/app/ai-agents");
    },
  });
  return (
    <div className="flex gap-2">
      <Button variant={agent.is_deployed ? "outline" : "default"} onClick={() => toggle.mutate()} disabled={toggle.isPending}>
        <Rocket /> {agent.is_deployed ? "Take off widget" : "Deploy to widget"}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Delete agent"
        onClick={() => window.confirm(`Delete ${agent.name}? Its activity history is kept.`) && remove.mutate()}
      >
        <Trash2 />
      </Button>
    </div>
  );
}

interface Turn {
  role: "user" | "assistant";
  content: string;
  result?: PlaygroundResult;
}

function Playground({ agent }: { agent: AIAgent }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState<PlaygroundResult | null>(null);
  const run = useMutation({
    mutationFn: (history: Turn[]) =>
      api.post<PlaygroundResult>(`${wsPath(ws)}/ai-agents/${agent.id}/playground`, {
        messages: history.map(({ role, content }) => ({ role, content })),
      }),
    onSuccess: (result, history) => {
      setTurns([...history, { role: "assistant", content: result.answer, result }]);
      setSelected(result);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Playground failed"),
  });

  const send = () => {
    const text = input.trim();
    if (!text || run.isPending) return;
    const history: Turn[] = [...turns, { role: "user", content: text }];
    setTurns(history);
    setInput("");
    run.mutate(history);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card className="flex h-[560px] flex-col p-0">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {turns.length === 0 ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              Ask a question the way a customer would. Nothing here is sent to real customers.
            </p>
          ) : null}
          {turns.map((t, i) => (
            <div key={i} className={cn("flex gap-2", t.role === "user" ? "justify-end" : "justify-start")}>
              {t.role === "assistant" ? <Bot className="mt-1 size-5 shrink-0 text-primary" /> : null}
              <button
                type="button"
                disabled={!t.result}
                onClick={() => t.result && setSelected(t.result)}
                className={cn(
                  "max-w-[80%] rounded-2xl px-3.5 py-2 text-left text-sm whitespace-pre-wrap",
                  t.role === "user" ? "bg-primary text-primary-foreground" : "border bg-background",
                  t.result?.decision === "handoff" && "border-amber-300 bg-amber-50",
                  t.result && selected === t.result && "ring-2 ring-primary/30",
                )}
              >
                {t.content}
                {t.result?.decision === "handoff" ? (
                  <span className="mt-1 block text-xs font-medium text-amber-800">Handoff: {t.result.handoff_reason}</span>
                ) : null}
              </button>
              {t.role === "user" ? <User className="mt-1 size-5 shrink-0 text-muted-foreground" /> : null}
            </div>
          ))}
          {run.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Thinking…
            </p>
          ) : null}
        </div>
        <div className="flex gap-2 border-t p-3">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask something…"
            className="min-h-10 resize-none"
            aria-label="Playground message"
          />
          <div className="flex flex-col gap-1">
            <Button onClick={send} disabled={!input.trim() || run.isPending} aria-label="Send">
              <Send />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => (setTurns([]), setSelected(null))}>
              Reset
            </Button>
          </div>
        </div>
      </Card>
      <Card className="h-[560px] overflow-y-auto p-4 text-sm">
        <p className="mb-3 font-medium">How the agent decided</p>
        {!selected ? (
          <p className="text-muted-foreground">Send a message to see retrieved sources, confidence, tokens and each pipeline step.</p>
        ) : (
          <div className="grid gap-4">
            <dl className="grid grid-cols-2 gap-2">
              <Stat label="Decision" value={selected.decision === "answer" ? "Answered" : "Handed off"} />
              <Stat label="Confidence" value={selected.confidence != null ? `${Math.round(selected.confidence * 100)}%` : "—"} />
              <Stat label="Latency" value={`${selected.latency_ms} ms`} />
              <Stat label="Tokens" value={`${selected.input_tokens} in / ${selected.output_tokens} out`} />
            </dl>
            <p className="font-mono text-xs text-muted-foreground">
              {selected.provider || "—"} · {selected.model || "—"}
            </p>
            <div>
              <p className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Sources</p>
              {selected.sources.length ? (
                <ul className="grid gap-2">
                  {selected.sources.map((s, i) => (
                    <li key={i} className="rounded-md border p-2">
                      <p className="flex justify-between text-xs font-medium">
                        <span className="truncate">{s.title}</span>
                        <span className="tabular-nums text-muted-foreground">{s.score.toFixed(2)}</span>
                      </p>
                      <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{s.excerpt}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">No relevant knowledge retrieved.</p>
              )}
            </div>
            {selected.tool_calls.length ? (
              <div>
                <p className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Tool calls</p>
                {selected.tool_calls.map((t, i) => (
                  <p key={i} className="font-mono text-xs">
                    {t.name} — {t.status}
                  </p>
                ))}
              </div>
            ) : null}
            <div>
              <p className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Pipeline</p>
              <ol className="grid gap-1">
                {selected.steps.map((s, i) => (
                  <li key={i} className="flex justify-between font-mono text-xs">
                    <span>
                      {s.node}
                      {s.note ? <span className="text-muted-foreground"> · {s.note}</span> : null}
                    </span>
                    <span className="tabular-nums text-muted-foreground">{s.ms}ms</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/50 p-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

const STATUS_STYLE: Record<AIExecution["status"], string> = {
  answered: "bg-emerald-50 text-emerald-800",
  handed_off: "bg-amber-50 text-amber-900",
  skipped: "bg-muted text-muted-foreground",
  quota_exceeded: "bg-red-50 text-red-800",
  failed: "bg-red-50 text-red-800",
};

function Activity({ ws, agentId }: { ws: string; agentId: string }) {
  const executions = useAgentExecutions(ws, agentId);
  const [open, setOpen] = useState<string | null>(null);
  if (executions.isPending) return <ListSkeleton rows={4} />;
  if (executions.isError) return <ErrorState message={executions.error.message} onRetry={() => executions.refetch()} />;
  if (!executions.data.results.length) {
    return <EmptyState icon={<Bot className="size-6" />} title="No activity yet" description="Executions from conversations and the playground appear here." />;
  }
  return (
    <Card className="divide-y p-0">
      {executions.data.results.map((e) => (
        <div key={e.id}>
          <button type="button" onClick={() => setOpen(open === e.id ? null : e.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40">
            <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", STATUS_STYLE[e.status])}>{e.status.replace("_", " ")}</span>
            <span className="min-w-0 flex-1 truncate text-sm">{e.query || "—"}</span>
            <span className="hidden text-xs text-muted-foreground sm:inline">{e.source}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{relativeTime(e.created_at)}</span>
            <ChevronDown className={cn("size-4 transition-transform", open === e.id && "rotate-180")} />
          </button>
          {open === e.id ? (
            <div className="grid gap-2 bg-muted/20 px-4 pb-4 text-sm">
              {e.answer ? <p className="whitespace-pre-wrap">{e.answer}</p> : null}
              {e.handoff_reason ? <p className="text-amber-800">Handoff reason: {e.handoff_reason}</p> : null}
              {e.skip_reason ? <p className="text-muted-foreground">Skipped: {e.skip_reason.replaceAll("_", " ")}</p> : null}
              {e.error ? <p className="text-destructive">Error: {e.error}</p> : null}
              <p className="font-mono text-xs text-muted-foreground">
                {e.provider} · {e.model} · {e.input_tokens}/{e.output_tokens} tokens · {e.latency_ms} ms
                {e.confidence != null ? ` · confidence ${e.confidence.toFixed(2)}` : ""}
              </p>
              {e.retrieved.length ? (
                <p className="text-xs text-muted-foreground">Sources: {e.retrieved.map((r) => `${r.title} (${r.score.toFixed(2)})`).join(", ")}</p>
              ) : null}
              {e.conversation ? (
                <Link href={`/app/inbox/${e.conversation}?view=all&status=all`} className="text-xs text-primary hover:underline">
                  Open conversation
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
      ))}
    </Card>
  );
}
