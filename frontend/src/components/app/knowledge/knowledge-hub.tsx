"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Globe, HelpCircle, Loader2, Plus, Search, Trash2, Type } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { formatBytes, ListSkeleton, relativeTime } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { FormError } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import { SOURCE_KIND_LABELS, useKnowledgeSources, type KnowledgeSource, type SearchHit, type SourceKind } from "@/lib/platform";
import { cn } from "@/lib/utils";

export const KIND_ICON: Record<SourceKind, typeof FileText> = { file: FileText, url: Globe, faq: HelpCircle, text: Type };

export function StatusPill({ status, error }: { status: KnowledgeSource["status"]; error?: string }) {
  const styles = {
    pending: "bg-muted text-muted-foreground",
    processing: "bg-blue-50 text-blue-700",
    ready: "bg-emerald-50 text-emerald-700",
    failed: "bg-red-50 text-red-700",
  }[status];
  return (
    <span title={error || undefined} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", styles)}>
      {status === "processing" || status === "pending" ? <Loader2 className="size-3 animate-spin" /> : null}
      {status === "ready" ? "Ready" : status === "failed" ? "Failed" : status === "pending" ? "Queued" : "Indexing"}
    </span>
  );
}

export function KnowledgeHub() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const sources = useKnowledgeSources(ws);
  const canManage = canWorkspace("knowledge.manage");

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Knowledge Hub"
        description="Everything your AI agents can learn from. Sources are processed in the background and stay private to this workspace."
        actions={canManage ? <AddSourceDialog /> : null}
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div>
          {sources.isPending ? (
            <ListSkeleton rows={4} />
          ) : sources.isError ? (
            <ErrorState message={sources.error.message} onRetry={() => sources.refetch()} />
          ) : sources.data.results.length === 0 ? (
            <EmptyState
              icon={<BookOpen className="size-6" />}
              title="No knowledge yet"
              description="Upload help docs (PDF, TXT, Markdown), add website pages, write FAQs, or paste text."
            />
          ) : (
            <Card className="divide-y p-0">
              {sources.data.results.map((s) => {
                const Icon = KIND_ICON[s.kind];
                return (
                  <Link key={s.id} href={`/app/knowledge/${s.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40">
                    <Icon className="size-5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className={cn("truncate text-sm font-medium", !s.enabled && "text-muted-foreground line-through")}>{s.title}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {SOURCE_KIND_LABELS[s.kind]}
                        {s.size ? ` · ${formatBytes(s.size)}` : ""}
                        {s.chunk_count ? ` · ${s.chunk_count} passages` : ""} · added {relativeTime(s.created_at)}
                      </p>
                      {s.status === "failed" ? <p className="truncate text-xs text-destructive">{s.error}</p> : null}
                    </div>
                    <StatusPill status={s.status} error={s.error} />
                  </Link>
                );
              })}
            </Card>
          )}
        </div>
        <RetrievalTester ws={ws} />
      </div>
    </div>
  );
}

function RetrievalTester({ ws }: { ws: string }) {
  const [query, setQuery] = useState("");
  const search = useMutation({ mutationFn: () => api.post<SearchHit[]>(`${wsPath(ws)}/knowledge/search`, { query, k: 5 }) });
  return (
    <Card className="h-fit p-4">
      <p className="font-medium">Test retrieval</p>
      <p className="mb-3 text-xs text-muted-foreground">See which passages an AI agent would read for a customer question.</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate();
        }}
      >
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. how do refunds work?" aria-label="Test question" />
        <Button type="submit" size="icon" disabled={search.isPending} aria-label="Search">
          {search.isPending ? <Loader2 className="animate-spin" /> : <Search />}
        </Button>
      </form>
      {search.data ? (
        search.data.length ? (
          <ol className="mt-3 grid gap-2">
            {search.data.map((h) => (
              <li key={h.chunk_id} className="rounded-md border p-2 text-xs">
                <p className="flex justify-between gap-2 font-medium">
                  <span className="truncate">{h.source_title}</span>
                  <span className="tabular-nums text-muted-foreground">{h.score.toFixed(2)}</span>
                </p>
                <p className="mt-1 line-clamp-4 text-muted-foreground">{h.content}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">Nothing relevant found.</p>
        )
      ) : null}
    </Card>
  );
}

function AddSourceDialog() {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<SourceKind>("file");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [faq, setFaq] = useState([{ question: "", answer: "" }]);

  const reset = () => {
    setTitle("");
    setFile(null);
    setUrl("");
    setText("");
    setFaq([{ question: "", answer: "" }]);
  };

  const create = useMutation({
    mutationFn: () => {
      if (kind === "file") {
        const form = new FormData();
        form.append("kind", "file");
        if (title) form.append("title", title);
        if (file) form.append("file", file);
        return api.upload<KnowledgeSource>(`${wsPath(ws)}/knowledge/sources`, form);
      }
      return api.post<KnowledgeSource>(`${wsPath(ws)}/knowledge/sources`, {
        kind,
        title: title || (kind === "url" ? url : ""),
        url,
        text,
        faq: faq.filter((f) => f.question.trim() && f.answer.trim()),
      });
    },
    onSuccess: (s) => {
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "knowledge"] });
      toast.success(`“${s.title}” added — indexing in the background`);
      reset();
      setOpen(false);
    },
  });
  const fieldErrors = create.error instanceof ApiError ? create.error.fieldErrors : {};
  const firstError = Object.values(fieldErrors)[0] ?? (create.error ? create.error.message : null);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> Add knowledge
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add knowledge</DialogTitle>
          <DialogDescription>Content is stored privately and processed in the background.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <FormError message={firstError} />
          <Tabs value={kind} onValueChange={(v) => setKind(v as SourceKind)}>
            <TabsList className="w-full">
              <TabsTrigger value="file">File</TabsTrigger>
              <TabsTrigger value="url">Website</TabsTrigger>
              <TabsTrigger value="faq">FAQ</TabsTrigger>
              <TabsTrigger value="text">Text</TabsTrigger>
            </TabsList>
            <TabsContent value="file" className="mt-3 grid gap-2">
              <Label htmlFor="k-file">PDF, TXT or Markdown (max 20 MB)</Label>
              <Input id="k-file" type="file" accept=".pdf,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </TabsContent>
            <TabsContent value="url" className="mt-3 grid gap-2">
              <Label htmlFor="k-url">Page URL</Label>
              <Input id="k-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.example.com/help/shipping" />
              <p className="text-xs text-muted-foreground">We fetch this single page over HTTPS. Private and internal addresses are blocked.</p>
            </TabsContent>
            <TabsContent value="faq" className="mt-3 grid max-h-72 gap-3 overflow-y-auto">
              {faq.map((item, i) => (
                <div key={i} className="grid gap-1.5 rounded-lg border p-2">
                  <Input
                    value={item.question}
                    placeholder="Question"
                    onChange={(e) => setFaq(faq.map((f, j) => (j === i ? { ...f, question: e.target.value } : f)))}
                    aria-label={`Question ${i + 1}`}
                  />
                  <Textarea
                    value={item.answer}
                    placeholder="Answer"
                    onChange={(e) => setFaq(faq.map((f, j) => (j === i ? { ...f, answer: e.target.value } : f)))}
                    aria-label={`Answer ${i + 1}`}
                  />
                  {faq.length > 1 ? (
                    <Button type="button" variant="ghost" size="sm" className="justify-self-end" onClick={() => setFaq(faq.filter((_, j) => j !== i))}>
                      <Trash2 /> Remove
                    </Button>
                  ) : null}
                </div>
              ))}
              <Button type="button" variant="outline" size="sm" onClick={() => setFaq([...faq, { question: "", answer: "" }])}>
                <Plus /> Add question
              </Button>
            </TabsContent>
            <TabsContent value="text" className="mt-3">
              <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-40" placeholder="Paste policies, product details, troubleshooting steps…" />
            </TabsContent>
          </Tabs>
          <div className="grid gap-1.5">
            <Label htmlFor="k-title">Title {kind === "file" || kind === "url" ? "(optional)" : ""}</Label>
            <Input id="k-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          </div>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" /> : null} Add source
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
