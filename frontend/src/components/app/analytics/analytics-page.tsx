"use client";

import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";

import { TrendChart, type Series } from "@/components/app/analytics/trend-chart";
import { useApp } from "@/components/app/app-context";
import { ListSkeleton } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { compact, formatDuration, useAnalytics } from "@/lib/platform";
import { cn } from "@/lib/utils";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const SERIES: Series[] = [
  { key: "created", label: "New", color: "var(--viz-1)" },
  { key: "resolved", label: "Resolved", color: "var(--viz-2)" },
  { key: "ai_replies", label: "AI replies", color: "var(--viz-3)" },
];

const iso = (d: Date) => d.toISOString().slice(0, 10);
const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export function AnalyticsPage() {
  const { workspace } = useApp();
  const [days, setDays] = useState(30);
  const [view, setView] = useState<"chart" | "table">("chart");
  const { start, end } = useMemo(() => {
    const e = new Date();
    const s = new Date();
    s.setDate(e.getDate() - (days - 1));
    return { start: iso(s), end: iso(e) };
  }, [days]);
  const analytics = useAnalytics(workspace!.id, start, end);
  const d = analytics.data;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Analytics"
        description={`Support performance for ${workspace!.name}.`}
        actions={
          <div className="flex rounded-lg border p-0.5" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button
                key={r.days}
                aria-pressed={days === r.days}
                onClick={() => setDays(r.days)}
                className={cn("rounded-md px-2.5 py-1 text-xs font-medium", days === r.days ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />
      {analytics.isPending ? (
        <ListSkeleton rows={6} />
      ) : analytics.isError ? (
        <ErrorState message={analytics.error.message} onRetry={() => analytics.refetch()} />
      ) : !d ? null : d.conversations.total === 0 && d.ai.executions === 0 ? (
        <EmptyState icon={<BarChart3 className="size-6" />} title="No activity in this period" description="Metrics appear once conversations start coming in." />
      ) : (
        <div className={cn("grid gap-6", analytics.isPlaceholderData && "opacity-60")}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Tile label="Conversations" value={compact.format(d.conversations.total)} sub={`${d.conversations.open} open now`} />
            <Tile label="Resolved" value={compact.format(d.conversations.resolved)} sub={`${d.conversations.pending} pending`} />
            <Tile label="AI resolution rate" value={pct(d.ai.resolution_rate)} sub={`${d.ai.resolved_without_human} without a human`} />
            <Tile label="Handoff rate" value={pct(d.ai.handoff_rate)} sub={`of ${d.ai.involved_conversations} AI conversations`} />
            <Tile label="First response" value={formatDuration(d.response_times.avg_first_response_seconds)} sub={`resolve in ${formatDuration(d.response_times.avg_resolution_seconds)}`} />
            <Tile label="AI tokens" value={compact.format(d.ai.input_tokens + d.ai.output_tokens)} sub={`${d.ai.executions} AI runs`} />
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Daily volume</CardTitle>
              <div className="flex items-center gap-4">
                <ul className="flex gap-3 text-xs" aria-label="Legend">
                  {SERIES.map((s) => (
                    <li key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
                      <span className="h-0.5 w-3 rounded" style={{ backgroundColor: s.color }} />
                      {s.label}
                    </li>
                  ))}
                </ul>
                <button className="text-xs font-medium text-primary hover:underline" onClick={() => setView(view === "chart" ? "table" : "chart")}>
                  {view === "chart" ? "View as table" : "View as chart"}
                </button>
              </div>
            </CardHeader>
            <CardContent>
              {view === "chart" ? (
                <TrendChart data={d.daily} series={SERIES} />
              ) : (
                <div className="max-h-72 overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        {SERIES.map((s) => (
                          <TableHead key={s.key} className="text-right">
                            {s.label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.daily.map((row) => (
                        <TableRow key={row.date}>
                          <TableCell>{row.date}</TableCell>
                          <TableCell className="text-right tabular-nums">{row.created}</TableCell>
                          <TableCell className="text-right tabular-nums">{row.resolved}</TableCell>
                          <TableCell className="text-right tabular-nums">{row.ai_replies}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Agent performance</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {d.agents.length === 0 ? (
                  <p className="px-6 pb-6 text-sm text-muted-foreground">No teammate replies in this period.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Teammate</TableHead>
                        <TableHead className="text-right">Replies</TableHead>
                        <TableHead className="text-right">Conversations</TableHead>
                        <TableHead className="pr-6 text-right">Resolved</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.agents.map((a) => (
                        <TableRow key={a.user_id}>
                          <TableCell className="pl-6 font-medium">{a.name}</TableCell>
                          <TableCell className="text-right tabular-nums">{a.replies}</TableCell>
                          <TableCell className="text-right tabular-nums">{a.conversations}</TableCell>
                          <TableCell className="pr-6 text-right tabular-nums">{a.resolved}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">AI usage</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 text-sm">
                <Row label="Answered" value={d.ai.answered} />
                <Row label="Handed off" value={d.ai.handed_off} />
                <Row label="Failed" value={d.ai.failed} />
                <Row label="Input tokens" value={d.ai.input_tokens} />
                <Row label="Output tokens" value={d.ai.output_tokens} />
                <Row label="Avg latency" value={d.ai.avg_latency_ms != null ? `${d.ai.avg_latency_ms} ms` : "—"} />
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <Card className="gap-1 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="truncate text-xs text-muted-foreground">{sub}</p>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{typeof value === "number" ? value.toLocaleString() : value}</span>
    </div>
  );
}
