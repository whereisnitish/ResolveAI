"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Loader2, Plug, Plus, Send, Trash2, Webhook } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { ListSkeleton, relativeTime } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { FormError } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api";
import { wsKeys, wsPath } from "@/lib/inbox-queries";
import { INTEGRATION_EVENTS, useDeliveries, useIntegrations, type Integration } from "@/lib/platform";
import { cn } from "@/lib/utils";

export function IntegrationsPage() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const integrations = useIntegrations(ws);
  const [secret, setSecret] = useState<string | null>(null);

  if (!canWorkspace("integrations.manage")) {
    return (
      <div className="mx-auto max-w-4xl">
        <PageHeader title="Integrations" />
        <EmptyState icon={<Plug className="size-6" />} title="Admins only" description="Ask a workspace admin to manage integrations." />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Integrations"
        description="Send conversation events to your own systems (signed webhooks) or to Slack."
        actions={<CreateIntegration onCreated={setSecret} />}
      />
      {secret ? (
        <Card className="mb-4 border-amber-300 bg-amber-50 p-4 text-sm">
          <p className="font-medium text-amber-950">Copy your signing secret now — it won&apos;t be shown again.</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-background px-2 py-1 font-mono text-xs">{secret}</code>
            <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(secret).then(() => toast.success("Copied"))}>
              <Copy /> Copy
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSecret(null)}>
              Done
            </Button>
          </div>
          <p className="mt-2 text-xs text-amber-900">
            Verify the <code>X-ResolveAI-Signature</code> header: <code>t=&lt;unix&gt;,v1=HMAC_SHA256(secret, &quot;t.body&quot;)</code>.
          </p>
        </Card>
      ) : null}
      {integrations.isPending ? (
        <ListSkeleton rows={2} />
      ) : integrations.isError ? (
        <ErrorState message={integrations.error.message} onRetry={() => integrations.refetch()} />
      ) : integrations.data.length === 0 ? (
        <EmptyState icon={<Webhook className="size-6" />} title="No integrations yet" description="Connect a webhook endpoint or a Slack channel." />
      ) : (
        <div className="grid gap-3">
          {integrations.data.map((i) => (
            <IntegrationCard key={i.id} integration={i} onSecret={setSecret} />
          ))}
        </div>
      )}
    </div>
  );
}

function IntegrationCard({ integration: i, onSecret }: { integration: Integration; onSecret: (s: string) => void }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const deliveries = useDeliveries(ws, i.id, open);
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "integrations"] });
  const update = useMutation({ mutationFn: (data: Partial<Integration>) => api.patch(`${wsPath(ws)}/integrations/${i.id}`, data), onSuccess: () => void refresh() });
  const test = useMutation({
    mutationFn: () => api.post(`${wsPath(ws)}/integrations/${i.id}/test`),
    onSuccess: () => (toast.success("Test event queued"), setOpen(true), void refresh()),
    onError: (e) => toast.error(e instanceof ApiError ? Object.values(e.fieldErrors)[0] ?? e.message : e.message),
  });
  const rotate = useMutation({
    mutationFn: () => api.post<{ signing_secret: string }>(`${wsPath(ws)}/integrations/${i.id}/rotate-secret`),
    onSuccess: (r) => onSecret(r.signing_secret),
  });
  const remove = useMutation({ mutationFn: () => api.delete(`${wsPath(ws)}/integrations/${i.id}`), onSuccess: () => void refresh() });

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="rounded-lg bg-muted p-2">{i.kind === "slack" ? <Plug className="size-5" /> : <Webhook className="size-5" />}</div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">{i.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {i.kind === "slack" ? "Slack" : "Webhook"} → {i.url_host} · {i.events.join(", ")}
          </p>
          {i.consecutive_failures > 0 ? (
            <p className="text-xs text-destructive">
              {i.consecutive_failures} failed deliveries in a row{!i.enabled ? " — disabled automatically" : ""}
            </p>
          ) : null}
        </div>
        <Switch checked={i.enabled} onCheckedChange={(v) => update.mutate({ enabled: Boolean(v) })} aria-label="Enabled" />
        <Button variant="outline" size="sm" onClick={() => test.mutate()} disabled={test.isPending}>
          <Send /> Test
        </Button>
        {i.kind === "webhook" ? (
          <Button variant="ghost" size="sm" onClick={() => window.confirm("Rotate the signing secret? The old one stops working immediately.") && rotate.mutate()}>
            Rotate secret
          </Button>
        ) : null}
        <Button variant="ghost" size="icon-sm" aria-label="Delete integration" onClick={() => window.confirm(`Delete ${i.name}?`) && remove.mutate()}>
          <Trash2 />
        </Button>
      </div>
      <button type="button" onClick={() => setOpen(!open)} className="mt-2 text-xs text-muted-foreground hover:text-foreground">
        {open ? "Hide" : "Show"} recent deliveries{i.last_delivery_at ? ` · last ${relativeTime(i.last_delivery_at)}` : ""}
      </button>
      {open ? (
        <ul className="mt-2 grid gap-1 border-t pt-2 text-xs">
          {deliveries.data?.length ? (
            deliveries.data.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 font-medium",
                      d.status === "succeeded" ? "bg-emerald-50 text-emerald-800" : d.status === "failed" ? "bg-red-50 text-red-800" : "bg-muted",
                    )}
                  >
                    {d.status}
                  </span>
                  {d.event} · {d.attempts} attempt(s){d.response_status ? ` · HTTP ${d.response_status}` : ""}
                  {d.error ? <span className="text-destructive">· {d.error}</span> : null}
                </span>
                <span className="text-muted-foreground">{relativeTime(d.created_at)}</span>
              </li>
            ))
          ) : (
            <li className="text-muted-foreground">No deliveries yet.</li>
          )}
        </ul>
      ) : null}
    </Card>
  );
}

function CreateIntegration({ onCreated }: { onCreated: (secret: string) => void }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"webhook" | "slack">("webhook");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["conversation.created"]);
  const create = useMutation({
    mutationFn: () => api.post<Integration & { signing_secret: string }>(`${wsPath(ws)}/integrations`, { kind, name, url, events }),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.all(ws), "integrations"] });
      if (r.signing_secret) onCreated(r.signing_secret);
      setOpen(false);
      setName("");
      setUrl("");
    },
  });
  const err = create.error instanceof ApiError ? Object.values(create.error.fieldErrors)[0] ?? create.error.message : null;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Plus /> Add integration
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add integration</DialogTitle>
          <DialogDescription>Destination URLs are encrypted at rest and must be public HTTPS endpoints.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <FormError message={err} />
          <div className="grid gap-1.5">
            <Label>Type</Label>
            <select className="h-9 rounded-lg border bg-background px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value as "webhook" | "slack")}>
              <option value="webhook">Outgoing webhook (signed JSON)</option>
              <option value="slack">Slack incoming webhook</option>
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="int-name">Name</Label>
            <Input id="int-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="int-url">URL</Label>
            <Input
              id="int-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder={kind === "slack" ? "https://hooks.slack.com/services/…" : "https://api.example.com/resolveai"}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>Events</Label>
            {INTEGRATION_EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-2 text-sm">
                <Checkbox checked={events.includes(ev)} onCheckedChange={(v) => setEvents(v ? [...events, ev] : events.filter((x) => x !== ev))} />
                <code className="text-xs">{ev}</code>
              </label>
            ))}
          </div>
          <Button type="submit" disabled={create.isPending || !events.length}>
            {create.isPending ? <Loader2 className="animate-spin" /> : null} Create
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
