"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { TagPill } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAssignees, useTags, useTeams, wsKeys, wsPath } from "@/lib/inbox-queries";
import type { Tag, Team } from "@/lib/types";

const TAG_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#64748b"];

export function InboxSettingsPanel() {
  return (
    <div className="grid gap-6">
      <TagsCard />
      <TeamsCard />
    </div>
  );
}

function TagsCard() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const tags = useTags(ws);
  const queryClient = useQueryClient();
  const canManage = canWorkspace("conversations.manage");
  const [name, setName] = useState("");
  const [color, setColor] = useState(TAG_COLORS[0]);
  const refresh = () => queryClient.invalidateQueries({ queryKey: wsKeys.tags(ws) });
  const create = useMutation({
    mutationFn: () => api.post<Tag>(`${wsPath(ws)}/tags`, { name, color }),
    onSuccess: () => {
      setName("");
      void refresh();
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${wsPath(ws)}/tags/${id}`),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(e.message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tags</CardTitle>
        <CardDescription>Label conversations and customers to organise and report on them.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {canManage ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New tag name" maxLength={50} className="h-9 w-56" aria-label="Tag name" />
            <div className="flex gap-1" role="radiogroup" aria-label="Tag colour">
              {TAG_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={color === c}
                  aria-label={c}
                  onClick={() => setColor(c)}
                  className="size-6 rounded-full ring-offset-2 aria-checked:ring-2 aria-checked:ring-ring"
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
            <Button type="submit" size="sm" disabled={!name.trim() || create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : <Plus />} Add tag
            </Button>
          </form>
        ) : null}
        {tags.isPending ? (
          <Skeleton className="h-8 w-full" />
        ) : tags.data?.length ? (
          <ul className="flex flex-wrap gap-2">
            {tags.data.map((t) => (
              <li key={t.id}>
                <TagPill tag={t} onRemove={canManage ? () => remove.mutate(t.id) : undefined} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No tags yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function TeamsCard() {
  const { workspace, canWorkspace } = useApp();
  const ws = workspace!.id;
  const teams = useTeams(ws);
  const queryClient = useQueryClient();
  const canManage = canWorkspace("workspace.members.manage");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<Team>(`${wsPath(ws)}/teams`, { name }),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: wsKeys.teams(ws) });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Teams</CardTitle>
        <CardDescription>Group agents (e.g. Billing, Technical) and route conversations to them.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {canManage ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New team name" maxLength={80} className="h-9 w-56" aria-label="Team name" />
            <Button type="submit" size="sm" disabled={!name.trim() || create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : <Plus />} Add team
            </Button>
          </form>
        ) : null}
        {teams.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : teams.data?.length ? (
          <ul className="divide-y rounded-lg border">
            {teams.data.map((t) => (
              <TeamRow key={t.id} team={t} ws={ws} canManage={canManage} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No teams yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function TeamRow({ team, ws, canManage }: { team: Team; ws: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const assignees = useAssignees(ws);
  const refresh = () => queryClient.invalidateQueries({ queryKey: wsKeys.teams(ws) });
  const update = useMutation({
    mutationFn: (member_ids: string[]) => api.patch<Team>(`${wsPath(ws)}/teams/${team.id}`, { member_ids }),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`${wsPath(ws)}/teams/${team.id}`),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(e.message),
  });
  const memberIds = new Set(team.members.map((m) => m.id));

  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2.5">
      <Users className="size-4 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{team.name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {team.members.length ? team.members.map((m) => m.full_name || m.email).join(", ") : "No members"}
        </p>
      </div>
      {canManage ? (
        <>
          <Popover>
            <PopoverTrigger render={<Button variant="outline" size="sm" />}>Members</PopoverTrigger>
            <PopoverContent align="end" className="w-64 p-2">
              <ul className="grid max-h-64 gap-0.5 overflow-y-auto">
                {(assignees.data ?? []).map((u) => (
                  <li key={u.id}>
                    <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                      <Checkbox
                        checked={memberIds.has(u.id)}
                        onCheckedChange={() => {
                          const next = new Set(memberIds);
                          if (next.has(u.id)) next.delete(u.id);
                          else next.add(u.id);
                          update.mutate([...next]);
                        }}
                      />
                      <span className="truncate">{u.full_name || u.email}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </PopoverContent>
          </Popover>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Delete team ${team.name}`}
            onClick={() => {
              if (window.confirm(`Delete team "${team.name}"? Conversations stay but lose their team.`)) remove.mutate();
            }}
          >
            <Trash2 />
          </Button>
        </>
      ) : null}
    </li>
  );
}
