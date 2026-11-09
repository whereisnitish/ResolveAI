"use client";

import { Inbox, Loader2, Search, User, UserX, Users } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { useApp } from "@/components/app/app-context";
import { PriorityIcon, ListSkeleton, shortAgo, TagPill } from "@/components/app/common";
import { useRealtime } from "@/components/app/realtime";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConversationCounts, useConversationList, useTeams } from "@/lib/inbox-queries";
import { STATUS_LABELS, type Conversation, type ConversationStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUSES: ConversationStatus[] = ["open", "pending", "resolved", "closed"];

/** Map inbox URL state to API query params (pure; unit-tested). */
export function buildInboxFilters(view: string, status: string, q: string): Record<string, string> {
  const f: Record<string, string> = { status: STATUSES.includes(status as ConversationStatus) ? status : "open" };
  if (view === "mine") f.assignee = "me";
  else if (view === "unassigned") f.assignee = "unassigned";
  else if (view.startsWith("team:")) f.team = view.slice(5);
  if (q.trim()) f.q = q.trim();
  return f;
}

export function useInboxFilters() {
  const params = useSearchParams();
  const view = params.get("view") ?? "mine";
  const rawStatus = params.get("status") ?? "open";
  const status: ConversationStatus = STATUSES.includes(rawStatus as ConversationStatus)
    ? (rawStatus as ConversationStatus)
    : "open";
  const q = params.get("q") ?? "";
  const filters = useMemo(() => buildInboxFilters(view, status, q), [view, status, q]);
  return { view, status, q, filters, query: params.toString() };
}

export function InboxLayout({ children }: { children: ReactNode }) {
  const { conversationId } = useParams<{ conversationId?: string }>();
  return (
    <div className="flex h-full min-h-0">
      <InboxNav />
      <div
        className={cn(
          "flex w-full min-w-0 flex-col border-r md:w-80 md:shrink-0 lg:w-96",
          conversationId && "hidden md:flex",
        )}
      >
        <ConversationList activeId={conversationId} />
      </div>
      <section className={cn("min-w-0 flex-1", !conversationId && "hidden md:block")}>{children}</section>
    </div>
  );
}

function InboxNav() {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const { view, status } = useInboxFilters();
  const counts = useConversationCounts(ws);
  const teams = useTeams(ws);
  const link = (v: string) => `/app/inbox?view=${encodeURIComponent(v)}&status=${status}`;

  const item = (v: string, label: string, icon: ReactNode, count?: number) => (
    <Link
      key={v}
      href={link(v)}
      aria-current={view === v ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm",
        view === v ? "bg-accent font-medium text-accent-foreground" : "text-foreground/80 hover:bg-accent/60",
      )}
    >
      {icon}
      <span className="flex-1 truncate">{label}</span>
      {count ? <span className="text-xs text-muted-foreground tabular-nums">{count}</span> : null}
    </Link>
  );

  return (
    <nav aria-label="Inbox views" className="hidden w-56 shrink-0 flex-col gap-4 border-r bg-muted/30 p-3 lg:flex">
      <h1 className="px-2 text-lg font-semibold">Inbox</h1>
      <div className="grid gap-0.5">
        {item("mine", "Your inbox", <User className="size-4" />, counts.data?.mine)}
        {item("unassigned", "Unassigned", <UserX className="size-4" />, counts.data?.unassigned)}
        {item("all", "All", <Inbox className="size-4" />, counts.data?.all)}
      </div>
      {teams.data && teams.data.length > 0 ? (
        <div className="grid gap-0.5">
          <p className="px-2.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Teams</p>
          {teams.data.map((t) => item(`team:${t.id}`, t.name, <Users className="size-4" />, counts.data?.by_team[t.id]))}
        </div>
      ) : null}
    </nav>
  );
}

function ConversationList({ activeId }: { activeId?: string }) {
  const { workspace } = useApp();
  const ws = workspace!.id;
  const router = useRouter();
  const pathname = usePathname();
  const { view, status, q, filters, query } = useInboxFilters();
  const list = useConversationList(ws, filters);
  const { typing } = useRealtime();
  const [search, setSearch] = useState(q);

  // Debounce search into the URL so results are shareable and survive reloads.
  useEffect(() => {
    const handle = setTimeout(() => {
      if (search === q) return;
      const next = new URLSearchParams(query);
      if (search) next.set("q", search);
      else next.delete("q");
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }, 300);
    return () => clearTimeout(handle);
  }, [search, q, query, pathname, router]);

  const setStatus = (s: ConversationStatus) => {
    const next = new URLSearchParams(query);
    next.set("status", s);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const conversations = list.data?.pages.flatMap((p) => p.results) ?? [];
  const title =
    view === "mine" ? "Your inbox" : view === "unassigned" ? "Unassigned" : view === "all" ? "All conversations" : "Team";

  return (
    <>
      <div className="space-y-3 border-b p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">{title}</h2>
          <ViewSwitcherMobile />
        </div>
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search messages, customers, #id"
            className="h-8 pl-8"
            aria-label="Search conversations"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Status">
          {STATUSES.map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={status === s}
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-md px-2 py-1 text-xs font-medium whitespace-nowrap",
                status === s ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {STATUS_LABELS[s]}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {list.isPending ? (
          <ListSkeleton />
        ) : list.isError ? (
          <div className="p-3">
            <ErrorState message={list.error.message} onRetry={() => list.refetch()} />
          </div>
        ) : conversations.length === 0 ? (
          <div className="p-3">
            <EmptyState
              icon={<Inbox className="size-6" />}
              title={q ? "No matching conversations" : `No ${STATUS_LABELS[status].toLowerCase()} conversations`}
              description={
                q
                  ? "Try a different search."
                  : "New conversations from your website widget will appear here in real time."
              }
            />
          </div>
        ) : (
          <ul className="divide-y">
            {conversations.map((c) => (
              <ConversationRow
                key={c.id}
                conversation={c}
                active={c.id === activeId}
                href={`/app/inbox/${c.id}?${query}`}
                customerTyping={(typing[c.id] ?? []).some((t) => t.actor === "customer")}
              />
            ))}
          </ul>
        )}
        {list.hasNextPage ? (
          <div className="p-3">
            <Button variant="outline" className="w-full" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
              {list.isFetchingNextPage ? <Loader2 className="animate-spin" /> : null}
              Load more
            </Button>
          </div>
        ) : null}
      </div>
    </>
  );
}

function ConversationRow({
  conversation: c,
  active,
  href,
  customerTyping,
}: {
  conversation: Conversation;
  active: boolean;
  href: string;
  customerTyping: boolean;
}) {
  const fromAgent = c.last_message_author_type === "agent";
  return (
    <li>
      <Link
        href={href}
        aria-current={active ? "true" : undefined}
        className={cn(
          "block border-l-2 px-3 py-3 transition-colors",
          active ? "border-l-primary bg-accent/70" : "border-l-transparent hover:bg-muted/50",
        )}
      >
        <div className="flex items-center gap-2">
          {c.is_unread ? <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="Unread" /> : null}
          <span className={cn("min-w-0 flex-1 truncate text-sm", c.is_unread ? "font-semibold" : "font-medium")}>
            {c.customer.display_name}
          </span>
          <PriorityIcon priority={c.priority} />
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{shortAgo(c.last_message_at)}</span>
        </div>
        <p className={cn("mt-1 line-clamp-2 text-sm", c.is_unread ? "text-foreground" : "text-muted-foreground")}>
          {customerTyping ? (
            <span className="text-primary italic">typing…</span>
          ) : (
            <>
              {fromAgent ? <span className="text-muted-foreground">You: </span> : null}
              {c.last_message_preview || "No messages yet"}
            </>
          )}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span>#{c.number}</span>
          {c.assignee ? <span>· {c.assignee.name.split(" ")[0]}</span> : <span>· Unassigned</span>}
          {c.team ? <span>· {c.team.name}</span> : null}
          {c.tags.slice(0, 2).map((t) => (
            <TagPill key={t.id} tag={t} />
          ))}
        </div>
      </Link>
    </li>
  );
}

function ViewSwitcherMobile() {
  const { view, status } = useInboxFilters();
  const router = useRouter();
  return (
    <select
      aria-label="Inbox view"
      className="h-7 rounded-md border bg-background px-1.5 text-xs lg:hidden"
      value={view.startsWith("team:") ? "all" : view}
      onChange={(e) => router.replace(`/app/inbox?view=${e.target.value}&status=${status}`)}
    >
      <option value="mine">Your inbox</option>
      <option value="unassigned">Unassigned</option>
      <option value="all">All</option>
    </select>
  );
}
