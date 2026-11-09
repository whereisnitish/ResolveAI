"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { formatBytes, formatDateTime, ListSkeleton } from "@/components/app/common";
import { KIND_ICON, StatusPill } from "@/components/app/knowledge/knowledge-hub";
import { ErrorState } from "@/components/app/team/team-page";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import { SOURCE_KIND_LABELS, useKnowledgeChunks, useKnowledgeSource, type KnowledgeSource } from "@/lib/platform";

export function SourceDetail() {
  const { sourceId } = useParams<{ sourceId: string }>();
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const source = useKnowledgeSource(ws, sourceId);
  const chunks = useKnowledgeChunks(ws, sourceId, source.data?.status === "ready");
  const canManage = canWorkspace("knowledge.manage");
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "knowledge"] });

  const reindex = useMutation({
    mutationFn: () => api.post(`${wsPath(ws)}/knowledge/sources/${sourceId}/reindex`),
    onSuccess: () => (void refresh(), toast.success("Re-indexing started")),
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.patch<KnowledgeSource>(`${wsPath(ws)}/knowledge/sources/${sourceId}`, { enabled }),
    onSuccess: () => void refresh(),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`${wsPath(ws)}/knowledge/sources/${sourceId}`),
    onSuccess: () => {
      void refresh();
      router.push("/app/knowledge");
    },
  });

  if (source.isPending) return <ListSkeleton rows={5} className="mx-auto max-w-4xl" />;
  if (source.isError) return <ErrorState message={source.error.message} onRetry={() => source.refetch()} />;
  const s = source.data;
  const Icon = KIND_ICON[s.kind];

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/app/knowledge" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Knowledge Hub
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Icon className="size-8 text-muted-foreground" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{s.title}</h1>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {SOURCE_KIND_LABELS[s.kind]} <StatusPill status={s.status} error={s.error} />
            </p>
          </div>
        </div>
        {canManage ? (
          <div className="flex items-center gap-2">
            <label className="mr-2 flex items-center gap-2 text-sm">
              <Switch checked={s.enabled} onCheckedChange={(v) => toggle.mutate(Boolean(v))} /> Used by AI
            </label>
            <Button variant="outline" onClick={() => reindex.mutate()} disabled={reindex.isPending || s.status === "processing"}>
              <RefreshCw /> Re-index
            </Button>
            <Button variant="ghost" size="icon" aria-label="Delete source" onClick={() => window.confirm("Delete this source and its passages?") && remove.mutate()}>
              <Trash2 />
            </Button>
          </div>
        ) : null}
      </div>
      {s.status === "failed" ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{s.error}</p> : null}
      <div className="grid gap-6 md:grid-cols-[260px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {s.url ? <Row label="URL" value={s.url} /> : null}
            {s.filename ? <Row label="File" value={`${s.filename} (${formatBytes(s.size)})`} /> : null}
            <Row label="Passages" value={String(s.chunk_count)} />
            <Row label="Characters" value={s.char_count.toLocaleString()} />
            <Row label="Embedding" value={s.embedding_model || "—"} />
            <Row label="Indexed" value={s.last_indexed_at ? formatDateTime(s.last_indexed_at) : "—"} />
            {Object.entries(s.metadata).map(([k, v]) => (
              <Row key={k} label={k} value={String(v)} />
            ))}
          </CardContent>
        </Card>
        <div>
          <h2 className="mb-2 text-sm font-semibold">Passages the AI can retrieve</h2>
          {s.status !== "ready" ? (
            <p className="text-sm text-muted-foreground">Passages appear once indexing finishes.</p>
          ) : chunks.isPending ? (
            <ListSkeleton rows={3} />
          ) : (
            <ol className="grid gap-2">
              {chunks.data?.results.map((c) => (
                <li key={c.id} className="rounded-lg border bg-card p-3 text-sm">
                  <p className="mb-1 text-xs text-muted-foreground">
                    #{c.position + 1} · ~{c.token_count} tokens
                    {typeof c.metadata.page === "number" ? ` · page ${c.metadata.page}` : ""}
                  </p>
                  <p className="line-clamp-6 whitespace-pre-wrap">{c.content}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate" title={value}>
        {value}
      </p>
    </div>
  );
}
