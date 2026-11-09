import type { ServerEvent } from "./types";

type Listener = (event: ServerEvent) => void;

/**
 * Real-time connection. The session token is sent as the first frame (never in
 * the URL). Reconnects with exponential backoff; on auth failure asks for a
 * fresh session token first.
 */
export class WidgetSocket {
  private ws: WebSocket | null = null;
  private attempts = 0;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly url: string,
    private readonly getToken: (forceRefresh: boolean) => Promise<string | null>,
    private readonly onEvent: Listener,
  ) {}

  async connect(forceRefresh = false): Promise<void> {
    this.closedByUser = false;
    const token = await this.getToken(forceRefresh).catch(() => null);
    if (!token || this.closedByUser) return this.scheduleReconnect();

    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(String(message.data)) as ServerEvent;
        if (event.type === "ready") this.attempts = 0;
        this.onEvent(event);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = (event) => {
      this.ws = null;
      if (this.closedByUser) return;
      this.scheduleReconnect(event.code === 4401);
    };
  }

  send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(payload));
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  private scheduleReconnect(refresh = false): void {
    if (this.closedByUser) return;
    const delay = Math.min(30_000, 1000 * 2 ** this.attempts) + Math.random() * 500;
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => void this.connect(refresh), delay);
  }
}
