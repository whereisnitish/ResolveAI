"use client";

/** Types + query hooks for Phase 3/4: AI agents, knowledge, workflows, integrations, analytics, billing. */
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import type { Paginated } from "@/lib/types";

// ---------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------
export type SourceKind = "file" | "url" | "faq" | "text";
export type SourceStatus = "pending" | "processing" | "ready" | "failed";

export interface KnowledgeSource {
  id: string;
  kind: SourceKind;
  title: string;
  status: SourceStatus;
  error: string;
  enabled: boolean;
  filename: string;
  content_type: string;
  size: number;
  url: string;
  faq: { question: string; answer: string }[];
  text: string;
  metadata: Record<string, string | number | boolean>;
  char_count: number;
  chunk_count: number;
  embedding_model: string;
  last_indexed_at: string | null;
  created_at: string;
}

export interface KnowledgeChunk {
  id: string;
  position: number;
  content: string;
  token_count: number;
  metadata: Record<string, unknown>;
}

export interface SearchHit {
  chunk_id: string;
  source_id: string;
  source_title: string;
  content: string;
  score: number;
}

export const SOURCE_KIND_LABELS: Record<SourceKind, string> = {
  file: "File",
  url: "Website",
  faq: "FAQ",
  text: "Text",
};

const isBusy = (s: KnowledgeSource) => s.status === "pending" || s.status === "processing";

export function useKnowledgeSources(ws: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "knowledge", "sources"],
    queryFn: () => api.get<Paginated<KnowledgeSource>>(`${wsPath(ws)}/knowledge/sources`, { page_size: 100 }),
    // Poll while anything is still ingesting.
    refetchInterval: (q) => (q.state.data?.results.some(isBusy) ? 2000 : false),
  });
}

export function useKnowledgeSource(ws: string, id: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "knowledge", "source", id],
    queryFn: () => api.get<KnowledgeSource>(`${wsPath(ws)}/knowledge/sources/${id}`),
    refetchInterval: (q) => (q.state.data && isBusy(q.state.data) ? 2000 : false),
  });
}

export function useKnowledgeChunks(ws: string, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "knowledge", "chunks", id],
    queryFn: () => api.get<Paginated<KnowledgeChunk>>(`${wsPath(ws)}/knowledge/sources/${id}/chunks`, { page_size: 50 }),
    enabled,
  });
}

// ---------------------------------------------------------------------------
// AI agents
// ---------------------------------------------------------------------------
export type ProviderId = "anthropic" | "openai" | "mock";

export interface AIAgent {
  id: string;
  name: string;
  description: string;
  instructions: string;
  provider: ProviderId;
  model: string;
  effort: "low" | "medium" | "high";
  max_output_tokens: number;
  use_all_knowledge: boolean;
  knowledge_source_ids: string[];
  retrieval_top_k: number;
  min_relevance: number;
  answer_only_from_knowledge: boolean;
  tone: string;
  greeting: string;
  handoff_confidence_threshold: number;
  handoff_on_no_knowledge: boolean;
  handoff_keywords: string[];
  max_ai_replies: number;
  handoff_team_id: string | null;
  handoff_message: string;
  allow_after_human_takeover: boolean;
  enabled: boolean;
  is_deployed: boolean;
  created_at: string;
  updated_at: string;
  stats?: { total: number; answered: number; handed_off: number; avg_latency_ms: number | null; tokens: number | null };
}

export interface ProviderInfo {
  providers: { id: ProviderId; label: string; default_model: string; configured: boolean }[];
  efforts: { id: string; label: string }[];
  mock_fallback_enabled: boolean;
}

export interface AIExecution {
  id: string;
  agent: string | null;
  agent_name: string | null;
  source: "conversation" | "playground" | "summary";
  conversation: string | null;
  status: "answered" | "handed_off" | "skipped" | "quota_exceeded" | "failed";
  skip_reason: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  confidence: number | null;
  handoff_reason: string;
  query: string;
  answer: string;
  retrieved: { chunk_id: string; source_id: string; title: string; score: number }[];
  steps: { node: string; ms: number; note: string }[];
  error: string;
  tool_executions: { id: string; tool_name: string; arguments: unknown; result: unknown; status: string; latency_ms: number }[];
  created_at: string;
}

export interface PlaygroundResult {
  execution_id: string;
  decision: "answer" | "handoff";
  answer: string;
  handoff_reason: string;
  confidence: number | null;
  sources: { source_id: string; title: string; score: number; excerpt: string }[];
  tool_calls: { name: string; arguments: unknown; status: string; result: unknown }[];
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  provider: string;
  model: string;
  steps: { node: string; ms: number; note: string }[];
}

export function useAgents(ws: string) {
  return useQuery({ queryKey: [...wsKeys.all(ws), "ai-agents"], queryFn: () => api.get<AIAgent[]>(`${wsPath(ws)}/ai-agents`) });
}

export function useAgent(ws: string, id: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "ai-agents", id],
    queryFn: () => api.get<AIAgent>(`${wsPath(ws)}/ai-agents/${id}`),
  });
}

export function useProviders(ws: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "ai-providers"],
    queryFn: () => api.get<ProviderInfo>(`${wsPath(ws)}/ai-agents/providers`),
    staleTime: 300_000,
  });
}

export function useAgentExecutions(ws: string, id: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "ai-agents", id, "executions"],
    queryFn: () => api.get<Paginated<AIExecution>>(`${wsPath(ws)}/ai-agents/${id}/executions`, { page_size: 50 }),
  });
}

export function useConversationAI(ws: string, conversationId: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "ai-executions", conversationId],
    queryFn: () => api.get<AIExecution[]>(`${wsPath(ws)}/ai-executions`, { conversation: conversationId }),
  });
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------
export interface WorkflowRule {
  field: string;
  operator: string;
  value?: string;
}
export interface WorkflowAction {
  type: string;
  [param: string]: string | undefined;
}
export interface Workflow {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  trigger: string;
  trigger_config: { minutes?: number };
  conditions: { match?: "all" | "any"; rules?: WorkflowRule[] };
  actions: WorkflowAction[];
  run_count: number;
  last_run_at: string | null;
  created_at: string;
}
export interface WorkflowSchema {
  triggers: { id: string; label: string }[];
  fields: { id: string; label: string }[];
  operators: string[];
  actions: { id: string; params: string[] }[];
}
export interface WorkflowExecution {
  id: string;
  conversation: string | null;
  conversation_number: number | null;
  status: string;
  results: { type: string; status: string; detail: string }[];
  created_at: string;
}

export function useWorkflows(ws: string) {
  return useQuery({ queryKey: [...wsKeys.all(ws), "workflows"], queryFn: () => api.get<Workflow[]>(`${wsPath(ws)}/workflows`) });
}
export function useWorkflowSchema(ws: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "workflow-schema"],
    queryFn: () => api.get<WorkflowSchema>(`${wsPath(ws)}/workflows/schema`),
    staleTime: Infinity,
  });
}
export function useWorkflowExecutions(ws: string, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "workflows", id, "executions"],
    queryFn: () => api.get<WorkflowExecution[]>(`${wsPath(ws)}/workflows/${id}/executions`),
    enabled,
  });
}

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------
export interface Integration {
  id: string;
  kind: "webhook" | "slack";
  name: string;
  enabled: boolean;
  url_host: string;
  events: string[];
  consecutive_failures: number;
  last_delivery_at: string | null;
  created_at: string;
}
export interface Delivery {
  id: string;
  event: string;
  status: "pending" | "succeeded" | "failed";
  attempts: number;
  response_status: number | null;
  error: string;
  created_at: string;
}
export const INTEGRATION_EVENTS = ["conversation.created", "conversation.resolved", "conversation.assigned", "message.created"];

export function useIntegrations(ws: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "integrations"],
    queryFn: () => api.get<Integration[]>(`${wsPath(ws)}/integrations`),
  });
}
export function useDeliveries(ws: string, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "integrations", id, "deliveries"],
    queryFn: () => api.get<Delivery[]>(`${wsPath(ws)}/integrations/${id}/deliveries`),
    enabled,
    refetchInterval: enabled ? 5000 : false,
  });
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------
export interface AnalyticsData {
  range: { start: string; end: string };
  conversations: { total: number; open: number; pending: number; resolved: number; by_channel: Record<string, number> };
  ai: {
    involved_conversations: number;
    resolved_without_human: number;
    resolution_rate: number | null;
    handoff_rate: number | null;
    executions: number;
    answered: number;
    handed_off: number;
    failed: number;
    input_tokens: number;
    output_tokens: number;
    avg_latency_ms: number | null;
  };
  response_times: { avg_first_response_seconds: number | null; avg_resolution_seconds: number | null };
  agents: { user_id: string; name: string; replies: number; conversations: number; resolved: number }[];
  daily: { date: string; created: number; resolved: number; ai_replies: number }[];
}

export function useAnalytics(ws: string, start: string, end: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "analytics", start, end],
    queryFn: () => api.get<AnalyticsData>(`${wsPath(ws)}/analytics`, { start, end }),
    placeholderData: (prev) => prev,
  });
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------
export interface Plan {
  code: string;
  name: string;
  description: string;
  prices: Record<"INR" | "USD", number>;
  limits: { seats: number; workspaces: number; ai_executions_per_month: number; knowledge_mb: number };
  features: string[];
  trial_days: number;
}
export interface BillingOverview {
  subscription: {
    plan: Plan;
    status: "trialing" | "active" | "past_due" | "canceled" | "expired";
    is_active: boolean;
    provider: string;
    currency: "INR" | "USD";
    trial_ends_at: string | null;
    trial_days_left: number | null;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  };
  checkout_provider: string | null;
  period_start: string;
  period_end: string;
  limits: Plan["limits"];
  usage: {
    ai_executions: number;
    ai_conversations: number;
    ai_input_tokens: number;
    ai_output_tokens: number;
    embedding_tokens: number;
    seats: number;
    workspaces: number;
    knowledge_mb: number;
  };
}
export interface InvoiceRow {
  id: string;
  provider: string;
  amount_minor: number;
  currency: string;
  status: string;
  hosted_url: string;
  issued_at: string;
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: () => api.get<Plan[]>("billing/plans"), staleTime: 300_000 });
}
export function useBilling(orgId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["organizations", orgId, "billing"],
    queryFn: () => api.get<BillingOverview>(`organizations/${orgId}/billing`),
    enabled: Boolean(orgId) && enabled,
  });
}
export function useInvoices(orgId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["organizations", orgId, "invoices"],
    queryFn: () => api.get<InvoiceRow[]>(`organizations/${orgId}/billing/invoices`),
    enabled: Boolean(orgId) && enabled,
  });
}

export function formatMoney(minor: number, currency: string): string {
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: minor % 100 === 0 ? 0 : 2,
  }).format(minor / 100);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
