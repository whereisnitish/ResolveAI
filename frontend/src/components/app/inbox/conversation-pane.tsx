"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CircleCheck,
  Clock,
  ExternalLink,
  FileText,
  Loader2,
  Lock,
  Paperclip,
  RotateCcw,
  Send,
  Tag as TagIcon,
  UserPlus,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import {
  formatBytes,
  formatDateTime,
  formatTime,
  ListSkeleton,
  PriorityIcon,
  relativeTime,
  SectionTitle,
  StatusBadge,
  TagPill,
} from "@/components/app/common";
import { AIBar } from "@/components/app/inbox/ai-bar";
import { useRealtime } from "@/components/app/realtime";
import { ErrorState } from "@/components/app/team/team-page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import {
  useAssignees,
  useConversation,
  useConversationEvents,
  useConversationList,
  useCustomer,
  useMessages,
  useTags,
  useTeams,
  wsKeys,
  wsPath,
} from "@/lib/inbox-queries";
import {
  PRIORITY_LABELS,
  type Conversation,
  type ConversationEvent,
  type ConversationPriority,
  type Message,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPTED_FILES = ".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.csv,.md,.docx,.xlsx";
const MAX_FILES = 5;
const TYPING_SEND_INTERVAL = 2000;

export function ConversationPane() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { workspace } = useApp();
  const ws = workspace!.id;
  const conversation = useConversation(ws, conversationId);

  if (conversation.isPending) return <ListSkeleton rows={8} className="p-6" />;
  if (conversation.isError) {
    return (
      <div className="p-6">
        <ErrorState
          message={
            conversation.error instanceof ApiError && conversation.error.status === 404
              ? "This conversation doesn't exist or you no longer have access to it."
              : conversation.error.message
          }
          onRetry={() => conversation.refetch()}
        />
      </div>
    );
  }
  return <ConversationView key={conversation.data.id} conversation={conversation.data} />;
}

function useConversationMutations(ws: string, id: string) {
  const queryClient = useQueryClient();
  const refresh = (updated?: Conversation) => {
    if (updated) queryClient.setQueryData(wsKeys.conversation(ws, id), updated);
    void queryClient.invalidateQueries({ queryKey: [...wsKeys.conversations(ws), "list"] });
    void queryClient.invalidateQueries({ queryKey: wsKeys.counts(ws) });
    void queryClient.invalidateQueries({ queryKey: wsKeys.events(ws, id) });
  };
  const onError = (error: Error) => toast.error(error.message);
  const update = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.patch<Conversation>(`${wsPath(ws)}/conversations/${id}`, data),
    onSuccess: refresh,
    onError,
  });
  const assign = useMutation({
    mutationFn: (data: { assignee_id?: string | null; team_id?: string | null }) =>
      api.post<Conversation>(`${wsPath(ws)}/conversations/${id}/assign`, data),
    onSuccess: refresh,
    onError,
  });
  return { update, assign };
}

function ConversationView({ conversation: c }: { conversation: Conversation }) {
  const { workspace, me, canWorkspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const query = useSearchParams().toString();
  const { update } = useConversationMutations(ws, c.id);
  const canReply = canWorkspace("conversations.reply");

  // Mark as read when opened and whenever new customer messages arrive while open.
  useEffect(() => {
    if (!c.is_unread) return;
    void api.post(`${wsPath(ws)}/conversations/${c.id}/read`).then(() => {
      queryClient.setQueryData<Conversation>(wsKeys.conversation(ws, c.id), (old) => (old ? { ...old, is_unread: false } : old));
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.conversations(ws), "list"] });
    });
  }, [c.id, c.is_unread, c.last_customer_message_at, queryClient, ws]);

  const isClosed = c.status === "resolved" || c.status === "closed";

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            render={<Link href={`/app/inbox?${query}`} />}
            aria-label="Back to conversations"
          >
            <ArrowLeft />
          </Button>
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-semibold">{c.customer.display_name}</h2>
            <p className="truncate text-xs text-muted-foreground">
              #{c.number}
              {c.subject ? ` · ${c.subject}` : ""} · <StatusBadge status={c.status} className="py-0" />
            </p>
          </div>
          {canReply ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <AssignMenu conversation={c} />
              <PriorityMenu conversation={c} />
              {isClosed ? (
                <Button size="sm" variant="outline" onClick={() => update.mutate({ status: "open" })} disabled={update.isPending}>
                  <RotateCcw /> Reopen
                </Button>
              ) : (
                <div className="flex">
                  <Button
                    size="sm"
                    className="rounded-r-none"
                    onClick={() => update.mutate({ status: "resolved" })}
                    disabled={update.isPending}
                  >
                    <CircleCheck /> Resolve
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={<Button size="sm" className="rounded-l-none border-l border-primary-foreground/20 px-1.5" aria-label="More status options" />}
                    >
                      <ChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {c.status !== "pending" ? (
                        <DropdownMenuItem onClick={() => update.mutate({ status: "pending" })}>
                          <Clock /> Mark as pending
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem onClick={() => update.mutate({ status: "open" })}>
                          <RotateCcw /> Mark as open
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem onClick={() => update.mutate({ status: "closed" })}>
                        <X /> Close
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )}
            </div>
          ) : null}
        </header>
        <AIBar conversation={c} canReply={canReply} />
        <Thread conversation={c} currentUserId={me.user.id} />
        {canReply ? (
          <Composer conversation={c} />
        ) : (
          <p className="border-t px-4 py-3 text-center text-sm text-muted-foreground">
            You have view-only access to this workspace.
          </p>
        )}
      </div>
      <CustomerSidebar conversation={c} canEdit={canReply} />
    </div>
  );
}

function AssignMenu({ conversation: c }: { conversation: Conversation }) {
  const { workspace, me } = useApp();
  const ws = workspace!.id;
  const assignees = useAssignees(ws);
  const teams = useTeams(ws);
  const { assign } = useConversationMutations(ws, c.id);
  const label = c.assignee ? c.assignee.name.split(" ")[0] : "Unassigned";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button size="sm" variant="outline" aria-label="Assign conversation" />}>
        <UserPlus /> <span className="max-w-24 truncate">{label}</span>
        {c.team ? <span className="max-w-24 truncate text-muted-foreground">· {c.team.name}</span> : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80 w-60 overflow-y-auto">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Assignee</DropdownMenuLabel>
          {c.assignee?.id !== me.user.id ? (
            <DropdownMenuItem onClick={() => assign.mutate({ assignee_id: me.user.id })}>Assign to me</DropdownMenuItem>
          ) : null}
          {(assignees.data ?? []).map((u) => (
            <DropdownMenuItem key={u.id} onClick={() => assign.mutate({ assignee_id: u.id })}>
              <span className="flex-1 truncate">{u.full_name || u.email}</span>
              {c.assignee?.id === u.id ? <Check className="text-primary" /> : null}
            </DropdownMenuItem>
          ))}
          {c.assignee ? (
            <DropdownMenuItem onClick={() => assign.mutate({ assignee_id: null })}>Unassign</DropdownMenuItem>
          ) : null}
        </DropdownMenuGroup>
        {teams.data && teams.data.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>Team</DropdownMenuLabel>
              {teams.data.map((t) => (
                <DropdownMenuItem key={t.id} onClick={() => assign.mutate({ team_id: t.id })}>
                  <span className="flex-1 truncate">{t.name}</span>
                  {c.team?.id === t.id ? <Check className="text-primary" /> : null}
                </DropdownMenuItem>
              ))}
              {c.team ? <DropdownMenuItem onClick={() => assign.mutate({ team_id: null })}>No team</DropdownMenuItem> : null}
            </DropdownMenuGroup>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PriorityMenu({ conversation: c }: { conversation: Conversation }) {
  const { workspace } = useApp();
  const { update } = useConversationMutations(workspace!.id, c.id);
  const priorities: ConversationPriority[] = ["urgent", "high", "normal", "low"];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button size="sm" variant="outline" aria-label={`Priority: ${PRIORITY_LABELS[c.priority]}`} />}>
        <PriorityIcon priority={c.priority} /> <span className="hidden sm:inline">{PRIORITY_LABELS[c.priority]}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {priorities.map((p) => (
          <DropdownMenuItem key={p} onClick={() => update.mutate({ priority: p })}>
            <PriorityIcon priority={p} /> <span className="flex-1">{PRIORITY_LABELS[p]}</span>
            {c.priority === p ? <Check className="text-primary" /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// -----------------------------------------------------------------------------
// Thread
// -----------------------------------------------------------------------------
type ThreadItem = { kind: "message"; at: string; message: Message } | { kind: "event"; at: string; event: ConversationEvent };

function describeEvent(e: ConversationEvent): string | null {
  const who = e.actor?.name ?? (e.actor_type === "customer" ? "Customer" : "System");
  const d = e.data as Record<string, string | string[] | null>;
  switch (e.type) {
    case "status_changed":
      return `${who} marked this ${d.to}`;
    case "reopened":
      return "Customer replied — conversation reopened";
    case "handoff":
      return `AI handed off${d.reason ? `: ${d.reason}` : ""}`;
    case "human_takeover":
      return `${who} took over from the AI`;
    case "ai_resumed":
      return `${who} let the AI resume`;
    case "priority_changed":
      return `${who} set priority to ${d.to}`;
    case "assigned":
      return d.assignee_name ? `${who} assigned to ${d.assignee_name}` : `${who} unassigned`;
    case "team_assigned":
      return d.team_name ? `${who} routed to team ${d.team_name}` : `${who} removed the team`;
    case "tags_changed": {
      const added = (d.added as string[]) ?? [];
      const removed = (d.removed as string[]) ?? [];
      return [added.length ? `added ${added.join(", ")}` : "", removed.length ? `removed ${removed.join(", ")}` : ""]
        .filter(Boolean)
        .map((part, i) => (i === 0 ? `${who} ${part}` : part))
        .join(" and ");
    }
    default:
      return null;
  }
}

function Thread({ conversation: c, currentUserId }: { conversation: Conversation; currentUserId: string }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const messages = useMessages(ws, c.id);
  const events = useConversationEvents(ws, c.id);
  const { typing } = useRealtime();
  const bottomRef = useRef<HTMLDivElement>(null);

  const items = useMemo<ThreadItem[]>(() => {
    const msgs = (messages.data?.pages.flatMap((p) => p.results) ?? []).map(
      (m): ThreadItem => ({ kind: "message", at: m.created_at, message: m }),
    );
    const oldest = msgs.length ? msgs.reduce((min, m) => (m.at < min ? m.at : min), msgs[0].at) : null;
    const evts = (events.data ?? [])
      .filter((e) => e.type !== "created" && (!messages.hasNextPage || (oldest && e.created_at >= oldest)))
      .map((e): ThreadItem => ({ kind: "event", at: e.created_at, event: e }));
    return [...msgs, ...evts].sort((a, b) => a.at.localeCompare(b.at));
  }, [events.data, messages.data, messages.hasNextPage]);

  const lastId = items.at(-1) && (items.at(-1)!.kind === "message" ? (items.at(-1) as { message: Message }).message.id : "");
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lastId]);

  const typers = (typing[c.id] ?? []).filter((t) => t.userId !== currentUserId);

  if (messages.isPending) return <ListSkeleton rows={5} className="flex-1 p-6" />;
  if (messages.isError) {
    return (
      <div className="flex-1 p-6">
        <ErrorState message={messages.error.message} onRetry={() => messages.refetch()} />
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-muted/20 px-4 py-4 sm:px-6" role="log" aria-label="Conversation messages">
      {messages.hasNextPage ? (
        <div className="mb-4 text-center">
          <Button variant="ghost" size="sm" onClick={() => messages.fetchNextPage()} disabled={messages.isFetchingNextPage}>
            {messages.isFetchingNextPage ? <Loader2 className="animate-spin" /> : null} Load earlier messages
          </Button>
        </div>
      ) : (
        <p className="mb-4 text-center text-xs text-muted-foreground">
          Conversation started {formatDateTime(c.created_at)} via {c.channel === "widget" ? "website widget" : "dashboard"}
        </p>
      )}
      <div className="mx-auto grid max-w-3xl gap-3">
        {items.map((item) =>
          item.kind === "event" ? (
            <EventLine key={item.event.id} event={item.event} />
          ) : (
            <MessageBubble key={item.message.id} message={item.message} ws={ws} />
          ),
        )}
        {typers.length > 0 ? (
          <p className="text-xs text-muted-foreground italic" aria-live="polite">
            {typers
              .map((t) => (t.actor === "customer" ? c.customer.display_name : `${t.name ?? "A teammate"}${t.note ? " (note)" : ""}`))
              .join(", ")}{" "}
            {typers.length > 1 ? "are" : "is"} typing…
          </p>
        ) : null}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function EventLine({ event }: { event: ConversationEvent }) {
  const text = describeEvent(event);
  if (!text) return null;
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      <span>
        {text} · {formatTime(event.created_at)}
      </span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function MessageBubble({ message: m, ws }: { message: Message; ws: string }) {
  const fromCustomer = m.author_type === "customer";
  const isNote = m.kind === "note";
  const isAI = m.author_type === "ai";
  const isSystem = m.author_type === "system" && !isNote;
  return (
    <div className={cn("flex flex-col", fromCustomer ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm shadow-xs",
          fromCustomer && "rounded-bl-md border bg-background",
          !fromCustomer && !isNote && !isAI && !isSystem && "rounded-br-md bg-primary text-primary-foreground",
          isAI && "rounded-br-md border border-violet-200 bg-violet-50 text-violet-950",
          isSystem && "rounded-br-md border bg-muted text-foreground",
          isNote && "rounded-br-md border border-amber-200 bg-amber-50 text-amber-950",
        )}
      >
        {isNote ? (
          <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold tracking-wide text-amber-700 uppercase">
            <Lock className="size-3" /> Internal note
          </p>
        ) : null}
        {m.body ? <p className="break-words whitespace-pre-wrap">{m.body}</p> : null}
        {m.attachments.length > 0 ? (
          <div className="mt-2 grid gap-1.5">
            {m.attachments.map((a) => {
              const url = `/api/v1/${wsPath(ws)}/attachments/${a.id}/download/`;
              return a.content_type.startsWith("image/") ? (
                <a key={a.id} href={url} target="_blank" rel="noopener noreferrer" className="block">
                  {/* eslint-disable-next-line @next/next/no-img-element -- authenticated, same-origin download */}
                  <img src={url} alt={a.filename} className="max-h-60 rounded-lg border bg-background object-contain" />
                </a>
              ) : (
                <a
                  key={a.id}
                  href={url}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs",
                    fromCustomer || isNote || isAI || isSystem ? "bg-background hover:bg-muted" : "border-primary-foreground/30 hover:bg-primary-foreground/10",
                  )}
                >
                  <FileText className="size-4 shrink-0" />
                  <span className="truncate">{a.filename}</span>
                  <span className="shrink-0 opacity-70">{formatBytes(a.size)}</span>
                </a>
              );
            })}
          </div>
        ) : null}
      </div>
      <p className="mt-1 px-1 text-[11px] text-muted-foreground">
        {m.author?.name ?? (isAI ? "AI assistant" : "Automation")} · {formatTime(m.created_at)}
      </p>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Composer
// -----------------------------------------------------------------------------
function Composer({ conversation: c }: { conversation: Conversation }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const queryClient = useQueryClient();
  const { sendTyping } = useRealtime();
  const [mode, setMode] = useState<"reply" | "note">("reply");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const lastTyping = useRef(0);

  const send = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("body", body.trim());
      form.append("kind", mode);
      files.forEach((f) => form.append("files", f));
      return api.upload<Message>(`${wsPath(ws)}/conversations/${c.id}/messages`, form);
    },
    onSuccess: () => {
      setBody("");
      setFiles([]);
      void queryClient.invalidateQueries({ queryKey: wsKeys.messages(ws, c.id) });
      void queryClient.invalidateQueries({ queryKey: wsKeys.conversation(ws, c.id) });
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.conversations(ws), "list"] });
    },
    onError: (error) => {
      const fileError = error instanceof ApiError ? error.fieldErrors.files : undefined;
      toast.error(fileError ?? error.message);
    },
  });

  const canSend = (body.trim().length > 0 || files.length > 0) && !send.isPending;

  const onInput = (value: string) => {
    setBody(value);
    const now = Date.now();
    if (value && now - lastTyping.current > TYPING_SEND_INTERVAL) {
      lastTyping.current = now;
      sendTyping(c.id, mode === "note");
    }
  };

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const next = [...files, ...Array.from(list)].slice(0, MAX_FILES);
    if (files.length + list.length > MAX_FILES) toast.warning(`At most ${MAX_FILES} files per message.`);
    setFiles(next);
  };

  return (
    <div className={cn("border-t p-3", mode === "note" && "bg-amber-50/60")}>
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex gap-1" role="tablist" aria-label="Message type">
          {(["reply", "note"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium",
                mode === m
                  ? m === "note"
                    ? "bg-amber-200/70 text-amber-950"
                    : "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {m === "reply" ? "Reply" : "Internal note"}
            </button>
          ))}
        </div>
        <Textarea
          value={body}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (canSend) send.mutate();
            }
          }}
          placeholder={
            mode === "reply"
              ? `Reply to ${c.customer.display_name}… (Enter to send, Shift+Enter for a new line)`
              : "Write an internal note — only your team can see this"
          }
          aria-label={mode === "reply" ? "Reply" : "Internal note"}
          className="max-h-48 min-h-20 resize-none bg-background"
          maxLength={10000}
        />
        {files.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs">
                <Paperclip className="size-3" />
                <span className="max-w-40 truncate">{f.name}</span>
                <button
                  type="button"
                  aria-label={`Remove ${f.name}`}
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-2 flex items-center justify-between">
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPTED_FILES}
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <Button variant="ghost" size="sm" onClick={() => fileInput.current?.click()} aria-label="Attach files">
            <Paperclip /> Attach
          </Button>
          <Button size="sm" onClick={() => send.mutate()} disabled={!canSend}>
            {send.isPending ? <Loader2 className="animate-spin" /> : <Send />}
            {mode === "reply" ? "Send" : "Add note"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Customer sidebar
// -----------------------------------------------------------------------------
function CustomerSidebar({ conversation: c, canEdit }: { conversation: Conversation; canEdit: boolean }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const customer = useCustomer(ws, c.customer.id);
  const others = useConversationList(ws, { customer: c.customer.id, status: "all" });
  const otherConversations = (others.data?.pages.flatMap((p) => p.results) ?? []).filter((o) => o.id !== c.id).slice(0, 5);

  return (
    <aside className="hidden w-72 shrink-0 overflow-y-auto border-l bg-background p-4 xl:block" aria-label="Customer details">
      <SectionTitle
        action={
          <Link href={`/app/customers/${c.customer.id}`} className="text-xs text-primary hover:underline">
            Profile <ExternalLink className="inline size-3" />
          </Link>
        }
      >
        Customer
      </SectionTitle>
      <p className="font-medium">{c.customer.display_name}</p>
      {c.customer.is_anonymous ? <p className="text-xs text-muted-foreground">Anonymous visitor</p> : null}
      <dl className="mt-3 grid gap-2 text-sm">
        <Field label="Email" value={customer.data?.email || "—"} />
        <Field label="Last seen" value={relativeTime(customer.data?.last_seen_at)} />
        {customer.data?.last_seen_url ? <Field label="Last page" value={customer.data.last_seen_url} truncate /> : null}
      </dl>

      <div className="mt-6">
        <SectionTitle>Conversation</SectionTitle>
        <dl className="grid gap-2 text-sm">
          <Field label="Started" value={formatDateTime(c.created_at)} />
          <Field label="First response" value={c.first_response_at ? relativeTime(c.first_response_at) : "Awaiting reply"} />
          {c.resolved_at ? <Field label="Resolved" value={relativeTime(c.resolved_at)} /> : null}
        </dl>
      </div>

      <div className="mt-6">
        <SectionTitle action={canEdit ? <TagEditor conversation={c} /> : null}>Tags</SectionTitle>
        {c.tags.length ? (
          <div className="flex flex-wrap gap-1.5">
            {c.tags.map((t) => (
              <TagPill key={t.id} tag={t} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No tags</p>
        )}
      </div>

      <div className="mt-6">
        <SectionTitle>Other conversations</SectionTitle>
        {otherConversations.length === 0 ? (
          <p className="text-sm text-muted-foreground">None</p>
        ) : (
          <ul className="grid gap-1">
            {otherConversations.map((o) => (
              <li key={o.id}>
                <Link href={`/app/inbox/${o.id}`} className="block rounded-md p-2 text-sm hover:bg-muted">
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium">#{o.number}</span>
                    <StatusBadge status={o.status} />
                  </span>
                  <span className="line-clamp-1 text-xs text-muted-foreground">{o.last_message_preview}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function Field({ label, value, truncate }: { label: string; value: string; truncate?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("text-sm", truncate && "truncate")} title={truncate ? value : undefined}>
        {value}
      </dd>
    </div>
  );
}

function TagEditor({ conversation: c }: { conversation: Conversation }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const tags = useTags(ws);
  const { update } = useConversationMutations(ws, c.id);
  const selected = new Set(c.tags.map((t) => t.id));

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update.mutate({ tag_ids: [...next] });
  };

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="ghost" size="icon-xs" aria-label="Edit tags" />}>
        <TagIcon />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        {tags.data?.length ? (
          <ul className="grid max-h-64 gap-0.5 overflow-y-auto">
            {tags.data.map((t) => (
              <li key={t.id}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                  <Checkbox checked={selected.has(t.id)} onCheckedChange={() => toggle(t.id)} />
                  <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: t.color }} />
                  <span className="truncate">{t.name}</span>
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-2 text-sm text-muted-foreground">
            No tags yet. Create them in{" "}
            <Link href="/app/settings?tab=inbox" className="text-primary hover:underline">
              Settings → Inbox
            </Link>
            .
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
