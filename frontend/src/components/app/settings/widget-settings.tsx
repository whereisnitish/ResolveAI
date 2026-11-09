"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Loader2, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { FormError } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useWidgetSettings, useWorkspaceDetailScoped, wsKeys, wsPath } from "@/lib/inbox-queries";
import type { WidgetSettings } from "@/lib/types";

const WIDGET_SCRIPT_URL = process.env.NEXT_PUBLIC_WIDGET_SCRIPT_URL ?? "https://cdn.resolveai.com/widget.js";
const WIDGET_API_URL = process.env.NEXT_PUBLIC_WIDGET_API_URL ?? "https://api.resolveai.com";

export function WidgetSettingsPanel() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const settings = useWidgetSettings(ws);
  const detail = useWorkspaceDetailScoped(ws);

  if (settings.isPending || detail.isPending) return <Skeleton className="h-96 w-full rounded-xl" />;
  if (settings.isError) return <p className="text-sm text-destructive">{settings.error.message}</p>;

  const snippet = `<script src="${WIDGET_SCRIPT_URL}"\n  data-workspace-id="${detail.data?.public_id ?? ""}"\n  data-api-url="${WIDGET_API_URL}" async></script>`;

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Install the chat widget</CardTitle>
          <CardDescription>Paste this snippet before the closing &lt;/body&gt; tag on every page of your website.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="relative">
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-12 font-mono text-xs leading-relaxed">{snippet}</pre>
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute top-2 right-2"
              aria-label="Copy snippet"
              onClick={() =>
                navigator.clipboard.writeText(snippet).then(
                  () => toast.success("Snippet copied"),
                  () => toast.error("Couldn't copy"),
                )
              }
            >
              <Copy />
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Optional JavaScript API: <code>ResolveAI.open()</code>, <code>ResolveAI.close()</code>,{" "}
            <code>ResolveAI.identify({"{ name, email }"})</code>.
          </p>
        </CardContent>
      </Card>
      <WidgetForm ws={ws} initial={settings.data} editable={canWorkspace("workspace.update")} />
    </div>
  );
}

function WidgetForm({ ws, initial, editable }: { ws: string; initial: WidgetSettings; editable: boolean }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initial);
  const [origins, setOrigins] = useState(initial.allowed_origins.join("\n"));
  const set = <K extends keyof WidgetSettings>(key: K, value: WidgetSettings[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const save = useMutation({
    mutationFn: () =>
      api.patch<WidgetSettings>(`${wsPath(ws)}/widget-settings`, {
        enabled: draft.enabled,
        team_name: draft.team_name,
        welcome_message: draft.welcome_message,
        brand_color: draft.brand_color,
        launcher_position: draft.launcher_position,
        collect_email: draft.collect_email,
        allowed_origins: origins
          .split(/[\n,]/)
          .map((o) => o.trim())
          .filter(Boolean),
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(wsKeys.widgetSettings(ws), saved);
      setDraft(saved);
      setOrigins(saved.allowed_origins.join("\n"));
      toast.success("Widget settings saved");
    },
  });

  const fieldErrors = save.error instanceof ApiError ? save.error.fieldErrors : {};
  const originList = origins.split(/[\n,]/).filter((o) => o.trim());

  return (
    <Card>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <CardHeader>
          <CardTitle>Appearance &amp; security</CardTitle>
          <CardDescription>{editable ? "Changes apply to the widget immediately." : "Only workspace admins can change these settings."}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 pt-4">
          <FormError message={save.error && !Object.keys(fieldErrors).length ? save.error.message : null} />
          <Toggle
            id="w-enabled"
            label="Widget enabled"
            description="When off, the widget doesn't load and existing visitor sessions stop working."
            checked={draft.enabled}
            disabled={!editable}
            onChange={(v) => set("enabled", v)}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="w-team">Team name shown to visitors</Label>
              <Input id="w-team" value={draft.team_name} maxLength={80} disabled={!editable} placeholder="Defaults to workspace name" onChange={(e) => set("team_name", e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="w-color">Brand colour</Label>
              <div className="flex items-center gap-2">
                <input
                  id="w-color"
                  type="color"
                  value={draft.brand_color}
                  disabled={!editable}
                  onChange={(e) => set("brand_color", e.target.value)}
                  className="h-9 w-12 cursor-pointer rounded-md border bg-background p-1"
                />
                <Input value={draft.brand_color} disabled={!editable} onChange={(e) => set("brand_color", e.target.value)} className="font-mono" aria-label="Brand colour hex" />
              </div>
              {fieldErrors.brand_color ? <p className="text-xs text-destructive">{fieldErrors.brand_color}</p> : null}
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="w-welcome">Welcome message</Label>
            <Textarea id="w-welcome" value={draft.welcome_message} maxLength={300} disabled={!editable} onChange={(e) => set("welcome_message", e.target.value)} />
          </div>
          <div className="grid gap-1.5 sm:w-64">
            <Label htmlFor="w-position">Launcher position</Label>
            <select
              id="w-position"
              value={draft.launcher_position}
              disabled={!editable}
              onChange={(e) => set("launcher_position", e.target.value as WidgetSettings["launcher_position"])}
              className="h-9 rounded-lg border bg-background px-2 text-sm"
            >
              <option value="right">Bottom right</option>
              <option value="left">Bottom left</option>
            </select>
          </div>
          <Toggle
            id="w-email"
            label="Ask visitors for their email"
            description="After their first message, visitors can leave an email to be notified of replies."
            checked={draft.collect_email}
            disabled={!editable}
            onChange={(v) => set("collect_email", v)}
          />
          <div className="grid gap-1.5">
            <Label htmlFor="w-origins">Allowed websites</Label>
            <Textarea
              id="w-origins"
              value={origins}
              disabled={!editable}
              onChange={(e) => setOrigins(e.target.value)}
              placeholder={"https://www.example.com\nhttps://app.example.com"}
              className="min-h-24 font-mono text-xs"
            />
            {fieldErrors.allowed_origins ? (
              <p className="text-xs text-destructive">{fieldErrors.allowed_origins}</p>
            ) : (
              <p className="text-xs text-muted-foreground">One origin per line (scheme://host[:port]). Only these sites can load your widget.</p>
            )}
            {originList.length === 0 ? (
              <p className="flex items-center gap-1.5 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">
                <ShieldAlert className="size-4 shrink-0" /> No restriction set — any website could embed your widget. Add your domains before going live.
              </p>
            ) : null}
          </div>
        </CardContent>
        {editable ? (
          <CardFooter className="mt-4 justify-end border-t pt-4">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null} Save changes
            </Button>
          </CardFooter>
        ) : null}
      </form>
    </Card>
  );
}

function Toggle({
  id,
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={(v) => onChange(Boolean(v))} />
    </div>
  );
}
