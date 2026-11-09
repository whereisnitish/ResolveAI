"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  Assignee,
  Conversation,
  ConversationCounts,
  ConversationEvent,
  CursorPage,
  Customer,
  CustomerNote,
  Message,
  Paginated,
  Tag,
  Team,
  TimelineItem,
  WidgetSettings,
  Workspace,
} from "@/lib/types";

/** All workspace-scoped keys start with ["ws", workspaceId] so switching workspaces never mixes data. */
export const wsKeys = {
  all: (ws: string) => ["ws", ws] as const,
  conversations: (ws: string) => ["ws", ws, "conversations"] as const,
  conversationList: (ws: string, filters: Record<string, string>) =>
    ["ws", ws, "conversations", "list", filters] as const,
  conversation: (ws: string, id: string) => ["ws", ws, "conversations", "detail", id] as const,
  messages: (ws: string, id: string) => ["ws", ws, "conversations", "messages", id] as const,
  events: (ws: string, id: string) => ["ws", ws, "conversations", "events", id] as const,
  counts: (ws: string) => ["ws", ws, "conversations", "counts"] as const,
  customers: (ws: string) => ["ws", ws, "customers"] as const,
  customerList: (ws: string, filters: Record<string, string | number>) =>
    ["ws", ws, "customers", "list", filters] as const,
  customer: (ws: string, id: string) => ["ws", ws, "customers", "detail", id] as const,
  customerNotes: (ws: string, id: string) => ["ws", ws, "customers", "notes", id] as const,
  customerTimeline: (ws: string, id: string) => ["ws", ws, "customers", "timeline", id] as const,
  tags: (ws: string) => ["ws", ws, "tags"] as const,
  teams: (ws: string) => ["ws", ws, "teams"] as const,
  assignees: (ws: string) => ["ws", ws, "assignees"] as const,
  widgetSettings: (ws: string) => ["ws", ws, "widget-settings"] as const,
};

export const wsPath = (ws: string) => `workspaces/${ws}`;

export function useConversationList(ws: string, filters: Record<string, string>) {
  return useInfiniteQuery({
    queryKey: wsKeys.conversationList(ws, filters),
    queryFn: ({ pageParam }) =>
      api.get<Paginated<Conversation>>(`${wsPath(ws)}/conversations`, { ...filters, page: pageParam, page_size: 30 }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  });
}

export function useConversation(ws: string, id: string | undefined) {
  return useQuery({
    queryKey: wsKeys.conversation(ws, id ?? ""),
    queryFn: () => api.get<Conversation>(`${wsPath(ws)}/conversations/${id}`),
    enabled: Boolean(id),
  });
}

export function useMessages(ws: string, id: string) {
  return useInfiniteQuery({
    queryKey: wsKeys.messages(ws, id),
    queryFn: ({ pageParam }) =>
      pageParam
        ? api.getUrl<CursorPage<Message>>(pageParam)
        : api.get<CursorPage<Message>>(`${wsPath(ws)}/conversations/${id}/messages`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next ?? undefined,
  });
}

export function useConversationEvents(ws: string, id: string) {
  return useQuery({
    queryKey: wsKeys.events(ws, id),
    queryFn: () => api.get<ConversationEvent[]>(`${wsPath(ws)}/conversations/${id}/events`),
  });
}

export function useConversationCounts(ws: string | undefined, enabled = true) {
  return useQuery({
    queryKey: wsKeys.counts(ws ?? ""),
    queryFn: () => api.get<ConversationCounts>(`${wsPath(ws ?? "")}/conversations/counts`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useCustomerList(ws: string, filters: Record<string, string | number>) {
  return useQuery({
    queryKey: wsKeys.customerList(ws, filters),
    queryFn: () => api.get<Paginated<Customer>>(`${wsPath(ws)}/customers`, { ...filters, page_size: 25 }),
    placeholderData: (previous) => previous,
  });
}

export function useCustomer(ws: string, id: string | undefined) {
  return useQuery({
    queryKey: wsKeys.customer(ws, id ?? ""),
    queryFn: () => api.get<Customer>(`${wsPath(ws)}/customers/${id}`),
    enabled: Boolean(id),
  });
}

export function useCustomerNotes(ws: string, id: string) {
  return useQuery({
    queryKey: wsKeys.customerNotes(ws, id),
    queryFn: () => api.get<CustomerNote[]>(`${wsPath(ws)}/customers/${id}/notes`),
  });
}

export function useCustomerTimeline(ws: string, id: string) {
  return useQuery({
    queryKey: wsKeys.customerTimeline(ws, id),
    queryFn: () => api.get<TimelineItem[]>(`${wsPath(ws)}/customers/${id}/timeline`),
  });
}

export function useTags(ws: string) {
  return useQuery({ queryKey: wsKeys.tags(ws), queryFn: () => api.get<Tag[]>(`${wsPath(ws)}/tags`), staleTime: 60_000 });
}

export function useTeams(ws: string) {
  return useQuery({
    queryKey: wsKeys.teams(ws),
    queryFn: () => api.get<Team[]>(`${wsPath(ws)}/teams`),
    staleTime: 60_000,
  });
}

export function useAssignees(ws: string) {
  return useQuery({
    queryKey: wsKeys.assignees(ws),
    queryFn: () => api.get<Assignee[]>(`${wsPath(ws)}/assignees`),
    staleTime: 60_000,
  });
}

export function useWidgetSettings(ws: string) {
  return useQuery({
    queryKey: wsKeys.widgetSettings(ws),
    queryFn: () => api.get<WidgetSettings>(`${wsPath(ws)}/widget-settings`),
  });
}

/** Workspace detail (incl. widget public_id) under the ws-scoped key. */
export function useWorkspaceDetailScoped(ws: string) {
  return useQuery({
    queryKey: [...wsKeys.all(ws), "detail"] as const,
    queryFn: () => api.get<Workspace>(`workspaces/${ws}`),
  });
}
