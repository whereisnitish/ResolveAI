"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { FormError } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useTeams, wsKeys, wsPath } from "@/lib/inbox-queries";
import { useKnowledgeSources, useProviders, type AIAgent, type ProviderId } from "@/lib/platform";

export type AgentDraft = Omit<AIAgent, "id" | "is_deployed" | "created_at" | "updated_at" | "stats">;

export const NEW_AGENT: AgentDraft = {
  name: "",
  description: "",
  instructions:
    "Help customers with questions about our products, orders and policies. Be concise and friendly. " +
    "If you can't find the answer in the knowledge base, offer to connect them with the team.",
  provider: "anthropic",
  model: "claude-opus-5-5",
  effort: "medium",
  max_output_tokens: 8000,
  use_all_knowledge: true,
  knowledge_source_ids: [],
  retrieval_top_k: 5,
  min_relevance: 0.15,
  answer_only_from_knowledge: true,
  tone: "Friendly, concise and professional.",
  greeting: "",
  handoff_confidence_threshold: 0.5,
  handoff_on_no_knowledge: true,
  handoff_keywords: ["human", "agent", "person", "representative", "real person", "talk to someone"],
  max_ai_replies: 10,
  handoff_team_id: null,
  handoff_message: "I'm connecting you with a member of our team. They'll reply here shortly.",
  allow_after_human_takeover: false,
  enabled: true,
};

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="grid gap-4">{children}</CardContent>
    </Card>
  );
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span>
        <span className="text-sm font-medium">{label}</span>
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
      <Switch checked={checked} onCheckedChange={(v) => onChange(Boolean(v))} />
    </label>
  );
}

export function AgentForm({ initial, agentId, editable }: { initial: AgentDraft; agentId?: string; editable: boolean }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const providers = useProviders(ws);
  const sources = useKnowledgeSources(ws);
  const teams = useTeams(ws);
  const [draft, setDraft] = useState<AgentDraft>(initial);
  const [keywords, setKeywords] = useState(initial.handoff_keywords.join(", "));
  const set = <K extends keyof AgentDraft>(key: K, value: AgentDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body = { ...draft, handoff_keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean) };
      return agentId
        ? api.patch<AIAgent>(`${wsPath(ws)}/ai-agents/${agentId}`, body)
        : api.post<AIAgent>(`${wsPath(ws)}/ai-agents`, body);
    },
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "ai-agents"] });
      toast.success(agentId ? "Agent saved" : "Agent created");
      if (!agentId) router.push(`/app/ai-agents/${agent.id}?tab=playground`);
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors : {};
  const providerInfo = providers.data?.providers.find((p) => p.id === draft.provider);

  const changeProvider = (id: ProviderId) => {
    const info = providers.data?.providers.find((p) => p.id === id);
    setDraft((d) => ({ ...d, provider: id, model: info?.default_model ?? d.model }));
  };

  return (
    <form
      className="grid gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <fieldset disabled={!editable} className="grid gap-6">
        <FormError message={save.error && !Object.keys(errors).length ? save.error.message : null} />
        <Section title="Identity" description="Customers see the agent's replies as “AI assistant”.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" error={errors.name}>
              <Input value={draft.name} onChange={(e) => set("name", e.target.value)} maxLength={80} required placeholder="e.g. Ava" />
            </Field>
            <Field label="Description">
              <Input value={draft.description} onChange={(e) => set("description", e.target.value)} maxLength={300} />
            </Field>
          </div>
          <Field label="Instructions" hint="Private system instructions. Never shown to customers; answers that leak them are blocked." error={errors.instructions}>
            <Textarea value={draft.instructions} onChange={(e) => set("instructions", e.target.value)} className="min-h-32" maxLength={20000} />
          </Field>
          <Field label="Tone">
            <Input value={draft.tone} onChange={(e) => set("tone", e.target.value)} maxLength={200} />
          </Field>
        </Section>

        <Section title="Model" description="Choose the LLM provider. Providers without an API key fall back to the offline mock in development.">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Provider">
              <select
                className="h-9 rounded-lg border bg-background px-2 text-sm"
                value={draft.provider}
                onChange={(e) => changeProvider(e.target.value as ProviderId)}
              >
                {(providers.data?.providers ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                    {p.configured ? "" : " — no API key"}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Model" error={errors.model}>
              <Input value={draft.model} onChange={(e) => set("model", e.target.value)} className="font-mono text-xs" />
            </Field>
            <Field label="Reasoning effort">
              <select
                className="h-9 rounded-lg border bg-background px-2 text-sm"
                value={draft.effort}
                onChange={(e) => set("effort", e.target.value as AgentDraft["effort"])}
              >
                {(providers.data?.efforts ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {providerInfo && !providerInfo.configured && draft.provider !== "mock" ? (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {providerInfo.label} has no API key configured on the server
              {providers.data?.mock_fallback_enabled ? " — the offline mock will answer instead (development only)." : "; replies will hand off to humans."}
            </p>
          ) : null}
        </Section>

        <Section title="Knowledge" description="What the agent may use to answer.">
          <Toggle label="Use all knowledge sources" checked={draft.use_all_knowledge} onChange={(v) => set("use_all_knowledge", v)} />
          {!draft.use_all_knowledge ? (
            <div className="grid max-h-56 gap-1 overflow-y-auto rounded-lg border p-2">
              {(sources.data?.results ?? []).map((s) => (
                <label key={s.id} className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted">
                  <Checkbox
                    checked={draft.knowledge_source_ids.includes(s.id)}
                    onCheckedChange={(v) =>
                      set("knowledge_source_ids", v ? [...draft.knowledge_source_ids, s.id] : draft.knowledge_source_ids.filter((x) => x !== s.id))
                    }
                  />
                  <span className="truncate">{s.title}</span>
                </label>
              ))}
              {sources.data?.results.length === 0 ? <p className="p-2 text-sm text-muted-foreground">No knowledge sources yet.</p> : null}
            </div>
          ) : null}
          <Toggle
            label="Answer only from knowledge"
            hint="Recommended. Prevents the model from improvising policies or prices."
            checked={draft.answer_only_from_knowledge}
            onChange={(v) => set("answer_only_from_knowledge", v)}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Passages retrieved per question">
              <Input type="number" min={1} max={20} value={draft.retrieval_top_k} onChange={(e) => set("retrieval_top_k", Number(e.target.value))} />
            </Field>
            <Field label="Minimum relevance (0–1)">
              <Input type="number" step={0.05} min={0} max={1} value={draft.min_relevance} onChange={(e) => set("min_relevance", Number(e.target.value))} />
            </Field>
          </div>
        </Section>

        <Section title="Human handoff" description="When the AI should step aside for your team.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Hand off below confidence" hint="0–1. Answers below this go to a human.">
              <Input
                type="number"
                step={0.05}
                min={0}
                max={1}
                value={draft.handoff_confidence_threshold}
                onChange={(e) => set("handoff_confidence_threshold", Number(e.target.value))}
              />
            </Field>
            <Field label="Max AI replies per conversation">
              <Input type="number" min={1} max={100} value={draft.max_ai_replies} onChange={(e) => set("max_ai_replies", Number(e.target.value))} />
            </Field>
          </div>
          <Field label="Customer phrases that request a human" hint="Comma-separated.">
            <Input value={keywords} onChange={(e) => setKeywords(e.target.value)} />
          </Field>
          <Field label="Handoff message">
            <Input value={draft.handoff_message} onChange={(e) => set("handoff_message", e.target.value)} maxLength={300} />
          </Field>
          <Field label="Route handoffs to team">
            <select
              className="h-9 rounded-lg border bg-background px-2 text-sm"
              value={draft.handoff_team_id ?? ""}
              onChange={(e) => set("handoff_team_id", e.target.value || null)}
            >
              <option value="">No team</option>
              {(teams.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
          <Toggle label="Hand off when no relevant knowledge is found" checked={draft.handoff_on_no_knowledge} onChange={(v) => set("handoff_on_no_knowledge", v)} />
          <Toggle
            label="Keep answering after a teammate replies"
            hint="Off by default: once a human takes over, the AI stays silent until resumed."
            checked={draft.allow_after_human_takeover}
            onChange={(v) => set("allow_after_human_takeover", v)}
          />
        </Section>
      </fieldset>
      {editable ? (
        <div className="flex justify-end">
          <Button type="submit" disabled={save.isPending || !draft.name.trim()}>
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            {agentId ? "Save changes" : "Create agent"}
          </Button>
        </div>
      ) : null}
    </form>
  );
}
