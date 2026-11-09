"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { wsKeys } from "@/lib/inbox-queries";

/**
 * Dashboard real-time connection (one socket per workspace).
 *
 * Server events carry only ids; we invalidate the matching TanStack Query
 * caches and let the REST API (which re-checks permissions) supply the data.
 */

export type ConnectionState = "connecting" | "open" | "closed";

interface TypingInfo {
  actor: "agent" | "customer";
  name?: string;
  userId?: string;
  note?: boolean;
  until: number;
}

interface RealtimeValue {
  state: ConnectionState;
  typing: Record<string, TypingInfo[]>;
  sendTyping: (conversationId: string, note: boolean) => void;
}

const RealtimeContext = createContext<RealtimeValue>({ state: "closed", typing: {}, sendTyping: () => undefined });

type ServerEvent =
  | { type: "conversation.created" | "conversation.updated"; conversation_id: string }
  | { type: "message.created"; conversation_id: string; message_id: string; kind: "reply" | "note" }
  | { type: "typing"; conversation_id: string; actor: "agent" | "customer"; name?: string; user_id?: string; note?: boolean };

const TYPING_TTL_MS = 5000;

function socketUrl(workspaceId: string): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  const base = configured
    ? configured.replace(/\/$/, "")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
  return `${base}/ws/workspaces/${workspaceId}/`;
}

export function RealtimeProvider({
  workspaceId,
  currentUserId,
  children,
}: {
  workspaceId: string;
  currentUserId: string;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ConnectionState>("connecting");
  const [typing, setTyping] = useState<Record<string, TypingInfo[]>>({});
  const socketRef = useRef<WebSocket | null>(null);

  const handle = useCallback(
    (event: ServerEvent) => {
      if (event.type === "typing") {
        if (event.user_id === currentUserId) return;
        setTyping((prev) => {
          const now = Date.now();
          const others = (prev[event.conversation_id] ?? []).filter(
            (t) => t.until > now && (t.userId ?? t.actor) !== (event.user_id ?? event.actor),
          );
          return {
            ...prev,
            [event.conversation_id]: [
              ...others,
              { actor: event.actor, name: event.name, userId: event.user_id, note: event.note, until: now + TYPING_TTL_MS },
            ],
          };
        });
        return;
      }
      if (event.type === "message.created") {
        setTyping((prev) => ({ ...prev, [event.conversation_id]: [] }));
        void queryClient.invalidateQueries({ queryKey: wsKeys.messages(workspaceId, event.conversation_id) });
      }
      void queryClient.invalidateQueries({ queryKey: wsKeys.conversation(workspaceId, event.conversation_id) });
      void queryClient.invalidateQueries({ queryKey: [...wsKeys.conversations(workspaceId), "list"] });
      void queryClient.invalidateQueries({ queryKey: wsKeys.counts(workspaceId) });
      void queryClient.invalidateQueries({ queryKey: wsKeys.events(workspaceId, event.conversation_id) });
    },
    [currentUserId, queryClient, workspaceId],
  );

  useEffect(() => {
    let disposed = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (disposed) return;
      setState("connecting");
      const ws = new WebSocket(socketUrl(workspaceId));
      socketRef.current = ws;
      ws.onopen = () => {
        attempts = 0;
        setState("open");
        // We may have missed events while disconnected.
        void queryClient.invalidateQueries({ queryKey: wsKeys.conversations(workspaceId) });
      };
      ws.onmessage = (message) => {
        try {
          handle(JSON.parse(String(message.data)) as ServerEvent);
        } catch {
          // ignore malformed frames
        }
      };
      ws.onclose = (event) => {
        socketRef.current = null;
        setState("closed");
        if (disposed || event.code === 4403) return; // no access: don't hammer the server
        const delay = Math.min(30_000, 1000 * 2 ** attempts) + Math.random() * 500;
        attempts += 1;
        timer = setTimeout(connect, delay);
      };
    };
    connect();

    // Expire stale typing indicators.
    const sweeper = setInterval(() => {
      setTyping((prev) => {
        const now = Date.now();
        let changed = false;
        const next: Record<string, TypingInfo[]> = {};
        for (const [id, list] of Object.entries(prev)) {
          const alive = list.filter((t) => t.until > now);
          if (alive.length !== list.length) changed = true;
          if (alive.length) next[id] = alive;
        }
        return changed ? next : prev;
      });
    }, 1000);

    return () => {
      disposed = true;
      clearTimeout(timer);
      clearInterval(sweeper);
      socketRef.current?.close();
    };
  }, [handle, queryClient, workspaceId]);

  const sendTyping = useCallback((conversationId: string, note: boolean) => {
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "typing", conversation_id: conversationId, note }));
    }
  }, []);

  return <RealtimeContext.Provider value={{ state, typing, sendTyping }}>{children}</RealtimeContext.Provider>;
}

export function useRealtime(): RealtimeValue {
  return useContext(RealtimeContext);
}
