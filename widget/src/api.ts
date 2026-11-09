import { loadVisitorToken, saveVisitorToken } from "./storage";
import type { SessionResponse, Visitor, WidgetConfig, WidgetConversation, WidgetMessage } from "./types";

export class WidgetApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/**
 * Talks to the public widget API with a short-lived bearer session token.
 * Never sends cookies (credentials: "omit"), so it can't ride a dashboard session.
 */
export class WidgetApi {
  private session: SessionResponse | null = null;
  private refreshing: Promise<SessionResponse> | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly config: WidgetConfig,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  get sessionToken(): string | null {
    return this.session?.session_token ?? null;
  }

  async startSession(): Promise<SessionResponse> {
    this.refreshing ??= this.createSession().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  private async createSession(): Promise<SessionResponse> {
    const body = {
      workspace_id: this.config.workspaceId,
      visitor_token: loadVisitorToken(this.config.workspaceId) ?? "",
      page_url: window.location.href.slice(0, 500),
    };
    const session = await this.raw<SessionResponse>("POST", "session/", body, false);
    saveVisitorToken(this.config.workspaceId, session.visitor_token);
    this.session = session;
    this.scheduleRefresh(session.expires_in);
    return session;
  }

  private scheduleRefresh(expiresIn: number): void {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    const ms = Math.max(30, expiresIn - 120) * 1000;
    this.refreshTimer = setTimeout(() => void this.startSession().catch(() => undefined), ms);
  }

  stop(): void {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
  }

  listConversations(): Promise<WidgetConversation[]> {
    return this.authed("GET", "conversations/");
  }

  startConversation(body: string): Promise<WidgetConversation> {
    return this.authed("POST", "conversations/", { body });
  }

  listMessages(conversationId: string): Promise<WidgetMessage[]> {
    return this.authed("GET", `conversations/${encodeURIComponent(conversationId)}/messages/`);
  }

  sendMessage(conversationId: string, body: string): Promise<WidgetMessage> {
    return this.authed("POST", `conversations/${encodeURIComponent(conversationId)}/messages/`, { body });
  }

  identify(data: Partial<Visitor>): Promise<{ visitor: Visitor }> {
    return this.authed("POST", "identify/", data);
  }

  async downloadAttachment(id: string): Promise<Blob> {
    const response = await this.request("GET", `attachments/${encodeURIComponent(id)}/`, undefined, true);
    return response.blob();
  }

  private async authed<T>(method: string, path: string, body?: unknown): Promise<T> {
    try {
      return await this.raw<T>(method, path, body, true);
    } catch (error) {
      // Session expired or revoked: get a fresh one once and retry.
      if (error instanceof WidgetApiError && error.status === 401) {
        await this.startSession();
        return this.raw<T>(method, path, body, true);
      }
      throw error;
    }
  }

  private async raw<T>(method: string, path: string, body: unknown, auth: boolean): Promise<T> {
    const response = await this.request(method, path, body, auth);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private async request(method: string, path: string, body: unknown, auth: boolean): Promise<Response> {
    if (auth && !this.session) await this.startSession();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && this.session) headers.Authorization = `Bearer ${this.session.session_token}`;
    const response = await this.fetchImpl(`${this.config.apiUrl}/api/v1/widget/${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "omit",
      mode: "cors",
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
      throw new WidgetApiError(
        response.status,
        payload?.error?.code ?? "error",
        payload?.error?.message ?? "Something went wrong.",
      );
    }
    return response;
  }
}
