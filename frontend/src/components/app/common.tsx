"use client";

import { ArrowDown, ArrowUp, Minus, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  PRIORITY_LABELS,
  STATUS_LABELS,
  type ConversationPriority,
  type ConversationStatus,
  type Tag,
} from "@/lib/types";

const rtf = typeof Intl !== "undefined" ? new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }) : null;
const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const timeFmt = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

/** Compact relative time: "now", "5m", "3h", "2d", then a date. */
export function shortAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d`;
  return dateFmt.format(new Date(iso));
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  if (!rtf) return dateTimeFmt.format(new Date(iso));
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  if (abs < 30 * 86400) return rtf.format(Math.round(seconds / 86400), "day");
  return dateFmt.format(new Date(iso));
}

export const formatDateTime = (iso: string) => dateTimeFmt.format(new Date(iso));
export const formatTime = (iso: string) => timeFmt.format(new Date(iso));

const STATUS_STYLES: Record<ConversationStatus, string> = {
  open: "bg-blue-50 text-blue-700 ring-blue-200",
  pending: "bg-amber-50 text-amber-800 ring-amber-200",
  resolved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  closed: "bg-muted text-muted-foreground ring-border",
};

export function StatusBadge({ status, className }: { status: ConversationStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_STYLES[status],
        className,
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

export function PriorityIcon({ priority, className }: { priority: ConversationPriority; className?: string }) {
  const label = `${PRIORITY_LABELS[priority]} priority`;
  const props = { className: cn("size-3.5", className), "aria-label": label };
  if (priority === "urgent") return <TriangleAlert {...props} className={cn(props.className, "text-red-600")} />;
  if (priority === "high") return <ArrowUp {...props} className={cn(props.className, "text-orange-600")} />;
  if (priority === "low") return <ArrowDown {...props} className={cn(props.className, "text-muted-foreground")} />;
  return <Minus {...props} className={cn(props.className, "text-muted-foreground/60")} />;
}

export function TagPill({ tag, onRemove }: { tag: Tag; onRemove?: () => void }) {
  return (
    <span className="inline-flex max-w-40 items-center gap-1 rounded-md border bg-background px-1.5 py-0.5 text-xs">
      <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: tag.color }} />
      <span className="truncate">{tag.name}</span>
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 text-muted-foreground hover:text-foreground"
          aria-label={`Remove tag ${tag.name}`}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}

export function ListSkeleton({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("grid gap-2 p-3", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-14 w-full" />
      ))}
    </div>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{children}</h3>
      {action}
    </div>
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
