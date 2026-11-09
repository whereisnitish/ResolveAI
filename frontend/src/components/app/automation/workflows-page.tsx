"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Trash2, Workflow as WorkflowIcon, X, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { ListSkeleton, relativeTime } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { FormError } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useAssignees, useTags, useTeams, wsKeys, wsPath } from "@/lib/inbox-queries";
import {
  useWorkflowExecutions,
  useWorkflows,
  useWorkflowSchema,
  type Workflow,
  type WorkflowAction,
  type WorkflowRule,
} from "@/lib/platform";
import { PRIORITY_LABELS, STATUS_LABELS } from "@/lib/types";

const ACTION_LABELS: Record<string, string> = {
  assign_user: "Assign to teammate",
  assign_team: "Route to team",
  assign_round_robin: "Round-robin within team",
  add_tag: "Add tag",
  set_priority: "Set priority",
  set_status: "Set status",
  send_reply: "Send reply to customer",
  add_note: "Add internal note",
};
const OPERATOR_LABELS: Record<string, string> = {
  eq: "is",
  neq: "is not",
  contains: "contains any of",
  not_contains: "does not contain",
  in: "is one of",
  is_true: "is true",
  is_false: "is false",
};
const TEMPLATES: { label: string; workflow: Partial<Workflow> }[] = [
  {
    label: "Welcome message",
    workflow: { name: "Welcome message", trigger: "conversation_created", actions: [{ type: "send_reply", body: "Thanks for reaching out! A teammate will be with you shortly." }] },
  },
  {
    label: "Tag refund requests",
    workflow: {
      name: "Tag refund requests",
      trigger: "customer_message",
      conditions: { match: "any", rules: [{ field: "message.text", operator: "contains", value: "refund, money back, return" }] },
      actions: [{ type: "set_priority", priority: "high" }],
    },
  },
  {
    label: "Escalate after 15 min",
    workflow: { name: "Escalate unanswered", trigger: "conversation_unanswered", trigger_config: { minutes: 15 }, actions: [{ type: "set_priority", priority: "urgent" }] },
  },
];

const select = "h-9 rounded-lg border bg-background px-2 text-sm";

export function WorkflowsPage() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const workflows = useWorkflows(ws);
  const schema = useWorkflowSchema(ws);
  const queryClient = useQueryClient();
  const canManage = canWorkspace("workflows.manage");
  const [editing, setEditing] = useState<Partial<Workflow> | null>(null);
  const toggle = useMutation({
    mutationFn: (w: Workflow) => api.patch(`${wsPath(ws)}/workflows/${w.id}`, { enabled: !w.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "workflows"] }),
  });
  const triggerLabel = (id: string) => schema.data?.triggers.find((t) => t.id === id)?.label ?? id;

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Automation"
        description="Workflows run in the background: WHEN something happens, IF conditions match, THEN take actions."
        actions={
          canManage ? (
            <Button onClick={() => setEditing({ name: "", trigger: "conversation_created", conditions: { match: "all", rules: [] }, actions: [] })}>
              <Plus /> New workflow
            </Button>
          ) : null
        }
      />
      {canManage ? (
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="self-center text-xs text-muted-foreground">Start from a template:</span>
          {TEMPLATES.map((t) => (
            <Button key={t.label} variant="outline" size="sm" onClick={() => setEditing({ conditions: { match: "all", rules: [] }, ...t.workflow })}>
              <Zap /> {t.label}
            </Button>
          ))}
        </div>
      ) : null}
      {workflows.isPending || schema.isPending ? (
        <ListSkeleton rows={3} />
      ) : workflows.isError ? (
        <ErrorState message={workflows.error.message} onRetry={() => workflows.refetch()} />
      ) : workflows.data.length === 0 ? (
        <EmptyState icon={<WorkflowIcon className="size-6" />} title="No workflows yet" description="Automate greetings, routing, tagging and escalations." />
      ) : (
        <div className="grid gap-3">
          {workflows.data.map((w) => (
            <WorkflowCard
              key={w.id}
              workflow={w}
              triggerLabel={triggerLabel(w.trigger)}
              canManage={canManage}
              onEdit={() => setEditing(w)}
              onToggle={() => toggle.mutate(w)}
            />
          ))}
        </div>
      )}
      {editing && schema.data ? <WorkflowEditor initial={editing} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

function WorkflowCard({
  workflow: w,
  triggerLabel,
  canManage,
  onEdit,
  onToggle,
}: {
  workflow: Workflow;
  triggerLabel: string;
  canManage: boolean;
  onEdit: () => void;
  onToggle: () => void;
}) {
  const { workspace } = useApp();
  const [showRuns, setShowRuns] = useState(false);
  const runs = useWorkflowExecutions(workspace!.id, w.id, showRuns);
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{w.name}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">When</span> {triggerLabel.toLowerCase()}
            {w.trigger_config.minutes ? ` for ${w.trigger_config.minutes} min` : ""}
            {w.conditions.rules?.length ? ` · if ${w.conditions.rules.length} condition(s)` : ""} ·{" "}
            <span className="font-medium text-foreground">then</span> {w.actions.map((a) => ACTION_LABELS[a.type]?.toLowerCase() ?? a.type).join(", ")}
          </p>
          <button type="button" className="mt-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => setShowRuns(!showRuns)}>
            Ran {w.run_count} time(s){w.last_run_at ? `, last ${relativeTime(w.last_run_at)}` : ""} · {showRuns ? "hide runs" : "show runs"}
          </button>
        </div>
        {canManage ? (
          <div className="flex items-center gap-2">
            <Switch checked={w.enabled} onCheckedChange={onToggle} aria-label={w.enabled ? "Disable workflow" : "Enable workflow"} />
            <Button variant="ghost" size="icon-sm" onClick={onEdit} aria-label="Edit workflow">
              <Pencil />
            </Button>
          </div>
        ) : null}
      </div>
      {showRuns ? (
        <ul className="mt-3 grid gap-1 border-t pt-3 text-xs">
          {runs.data?.length ? (
            runs.data.map((r) => (
              <li key={r.id} className="flex justify-between gap-2">
                <span>
                  {r.conversation_number ? `#${r.conversation_number}` : "—"} · {r.status} · {r.results.map((x) => x.detail).join("; ")}
                </span>
                <span className="text-muted-foreground">{relativeTime(r.created_at)}</span>
              </li>
            ))
          ) : (
            <li className="text-muted-foreground">No runs yet.</li>
          )}
        </ul>
      ) : null}
    </Card>
  );
}

function WorkflowEditor({ initial, onClose }: { initial: Partial<Workflow>; onClose: () => void }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const schema = useWorkflowSchema(ws).data!;
  const tags = useTags(ws);
  const teams = useTeams(ws);
  const assignees = useAssignees(ws);
  const queryClient = useQueryClient();
  const [name, setName] = useState(initial.name ?? "");
  const [trigger, setTrigger] = useState(initial.trigger ?? "conversation_created");
  const [minutes, setMinutes] = useState(initial.trigger_config?.minutes ?? 15);
  const [match, setMatch] = useState<"all" | "any">(initial.conditions?.match ?? "all");
  const [rules, setRules] = useState<WorkflowRule[]>(initial.conditions?.rules ?? []);
  const [actions, setActions] = useState<WorkflowAction[]>(initial.actions?.length ? initial.actions : [{ type: "add_note", body: "" }]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        trigger,
        trigger_config: trigger === "conversation_unanswered" ? { minutes } : {},
        conditions: { match, rules },
        actions,
      };
      return initial.id ? api.patch(`${wsPath(ws)}/workflows/${initial.id}`, body) : api.post(`${wsPath(ws)}/workflows`, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "workflows"] });
      toast.success("Workflow saved");
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`${wsPath(ws)}/workflows/${initial.id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "workflows"] });
      onClose();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors : {};
  const setAction = (i: number, patch: Partial<WorkflowAction>) => setActions(actions.map((a, j) => (j === i ? ({ ...a, ...patch } as WorkflowAction) : a)));

  const paramInput = (a: WorkflowAction, i: number) => {
    switch (a.type) {
      case "assign_user":
        return (
          <select className={select} value={a.user_id ?? ""} onChange={(e) => setAction(i, { user_id: e.target.value })} aria-label="Teammate">
            <option value="">Choose teammate…</option>
            {assignees.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name || u.email}
              </option>
            ))}
          </select>
        );
      case "assign_team":
      case "assign_round_robin":
        return (
          <select className={select} value={a.team_id ?? ""} onChange={(e) => setAction(i, { team_id: e.target.value })} aria-label="Team">
            <option value="">Choose team…</option>
            {teams.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        );
      case "add_tag":
        return (
          <select className={select} value={a.tag_id ?? ""} onChange={(e) => setAction(i, { tag_id: e.target.value })} aria-label="Tag">
            <option value="">Choose tag…</option>
            {tags.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        );
      case "set_priority":
        return (
          <select className={select} value={a.priority ?? ""} onChange={(e) => setAction(i, { priority: e.target.value })} aria-label="Priority">
            <option value="">Choose…</option>
            {Object.entries(PRIORITY_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        );
      case "set_status":
        return (
          <select className={select} value={a.status ?? ""} onChange={(e) => setAction(i, { status: e.target.value })} aria-label="Status">
            <option value="">Choose…</option>
            {Object.entries(STATUS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        );
      default:
        return <Textarea value={a.body ?? ""} onChange={(e) => setAction(i, { body: e.target.value })} maxLength={2000} placeholder="Message" className="min-h-16" />;
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{initial.id ? "Edit workflow" : "New workflow"}</DialogTitle>
          <DialogDescription>Workflows never trigger other workflows, and each runs at most once per event.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <FormError message={save.error ? Object.values(errors).join(" ") || save.error.message : null} />
          <div className="grid gap-1.5">
            <Label htmlFor="wf-name">Name</Label>
            <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          </div>
          <div className="grid gap-1.5">
            <Label>When</Label>
            <div className="flex flex-wrap items-center gap-2">
              <select className={select} value={trigger} onChange={(e) => setTrigger(e.target.value)} aria-label="Trigger">
                {schema.triggers.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
              {trigger === "conversation_unanswered" ? (
                <>
                  <span className="text-sm">for</span>
                  <Input type="number" min={1} max={10080} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="w-24" aria-label="Minutes" />
                  <span className="text-sm">minutes</span>
                </>
              ) : null}
            </div>
          </div>
          <div className="grid gap-2">
            <div className="flex items-center gap-2">
              <Label>If</Label>
              <select className={`${select} h-7`} value={match} onChange={(e) => setMatch(e.target.value as "all" | "any")} aria-label="Match">
                <option value="all">all conditions match</option>
                <option value="any">any condition matches</option>
              </select>
            </div>
            {rules.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select className={select} value={r.field} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))} aria-label="Field">
                  {schema.fields.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                    </option>
                  ))}
                </select>
                <select className={select} value={r.operator} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, operator: e.target.value } : x)))} aria-label="Operator">
                  {schema.operators.map((o) => (
                    <option key={o} value={o}>
                      {OPERATOR_LABELS[o] ?? o}
                    </option>
                  ))}
                </select>
                {r.operator !== "is_true" && r.operator !== "is_false" ? (
                  <Input value={r.value ?? ""} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} className="w-56" placeholder="value (comma-separate alternatives)" aria-label="Value" />
                ) : null}
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => setRules(rules.filter((_, j) => j !== i))} aria-label="Remove condition">
                  <X />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setRules([...rules, { field: "message.text", operator: "contains", value: "" }])}>
              <Plus /> Add condition
            </Button>
          </div>
          <div className="grid gap-2">
            <Label>Then</Label>
            {actions.map((a, i) => (
              <div key={i} className="grid gap-2 rounded-lg border p-2 sm:grid-cols-[200px_1fr_auto]">
                <select className={select} value={a.type} onChange={(e) => setAction(i, { type: e.target.value })} aria-label="Action">
                  {schema.actions.map((x) => (
                    <option key={x.id} value={x.id}>
                      {ACTION_LABELS[x.id] ?? x.id}
                    </option>
                  ))}
                </select>
                {paramInput(a, i)}
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => setActions(actions.filter((_, j) => j !== i))} aria-label="Remove action" disabled={actions.length === 1}>
                  <X />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setActions([...actions, { type: "add_tag" }])}>
              <Plus /> Add action
            </Button>
          </div>
          <div className="flex justify-between">
            {initial.id ? (
              <Button type="button" variant="ghost" onClick={() => window.confirm("Delete this workflow?") && remove.mutate()}>
                <Trash2 /> Delete
              </Button>
            ) : (
              <span />
            )}
            <Button type="submit" disabled={save.isPending || !name.trim()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null} Save workflow
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
