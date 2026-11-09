import { WidgetApi, WidgetApiError } from "./api";
import { ICONS, el, formatTime, safeColor, svgIcon } from "./dom";
import { WidgetSocket } from "./socket";
import { STYLES } from "./styles";
import type {
  ServerEvent,
  Visitor,
  WidgetConfig,
  WidgetConversation,
  WidgetMessage,
  WidgetSettings,
} from "./types";

const TYPING_SEND_INTERVAL = 2000;
const TYPING_DISPLAY_MS = 5000;

export class ResolveWidget {
  readonly host: HTMLElement;
  readonly shadow: ShadowRoot;
  private readonly api: WidgetApi;
  private socket: WidgetSocket | null = null;

  private settings: WidgetSettings | null = null;
  private visitor: Visitor = { name: "", email: "" };
  private conversation: WidgetConversation | null = null;
  private messages = new Map<string, WidgetMessage>();
  private isOpen = false;
  private unread = 0;
  private lastTypingSent = 0;
  private typingTimer: ReturnType<typeof setTimeout> | null = null;
  private emailDismissed = false;
  private sending = false;

  // DOM
  private root!: HTMLDivElement;
  private panel!: HTMLDivElement;
  private body!: HTMLDivElement;
  private badge!: HTMLSpanElement;
  private typingEl!: HTMLDivElement;
  private textarea!: HTMLTextAreaElement;
  private sendBtn!: HTMLButtonElement;
  private errorEl!: HTMLDivElement;

  constructor(
    private readonly config: WidgetConfig,
    api?: WidgetApi,
  ) {
    this.api = api ?? new WidgetApi(config);
    this.host = document.createElement("div");
    this.host.setAttribute("data-resolveai-widget", "");
    this.shadow = this.host.attachShadow({ mode: "open" });
  }

  async start(): Promise<void> {
    const session = await this.api.startSession();
    this.settings = session.settings;
    this.visitor = session.visitor;
    this.render();
    document.body.append(this.host);
    const conversations = await this.api.listConversations().catch(() => []);
    this.conversation = conversations[0] ?? null;
    if (this.conversation) this.connectSocket();
  }

  destroy(): void {
    this.socket?.close();
    this.api.stop();
    this.host.remove();
  }

  open(): void {
    if (!this.settings) return;
    this.isOpen = true;
    this.unread = 0;
    this.updateBadge();
    this.panel.hidden = false;
    this.root.querySelector(".launcher")?.setAttribute("aria-expanded", "true");
    void this.loadMessages();
    this.textarea.focus();
  }

  close(): void {
    this.isOpen = false;
    this.panel.hidden = true;
    this.root.querySelector(".launcher")?.setAttribute("aria-expanded", "false");
  }

  async identify(data: Partial<Visitor>): Promise<void> {
    const result = await this.api.identify(data);
    this.visitor = result.visitor;
    this.renderMessages();
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  private render(): void {
    const settings = this.settings!;
    const style = el("style");
    style.textContent = STYLES;

    const launcher = el("button", {
      class: "launcher",
      type: "button",
      "aria-label": `Chat with ${settings.team_name}`,
      "aria-expanded": "false",
      "aria-haspopup": "dialog",
    });
    launcher.append(svgIcon(ICONS.chat, 26));
    this.badge = el("span", { class: "badge", hidden: true, "aria-live": "polite" });
    launcher.append(this.badge);
    launcher.addEventListener("click", () => (this.isOpen ? this.close() : this.open()));

    const closeBtn = el("button", { class: "icon-btn", type: "button", "aria-label": "Close chat" });
    closeBtn.append(svgIcon(ICONS.close, 20));
    closeBtn.addEventListener("click", () => this.close());

    this.body = el("div", { class: "body", role: "log", "aria-live": "polite" });
    this.typingEl = el("div", { class: "typing", "aria-live": "polite" });
    this.errorEl = el("div", { class: "error", role: "alert", hidden: true });

    this.textarea = el("textarea", { rows: "1", placeholder: "Write a message…", "aria-label": "Message", maxlength: "5000" });
    this.textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void this.send();
      }
    });
    this.textarea.addEventListener("input", () => {
      this.autoGrow();
      this.sendTyping();
    });
    this.sendBtn = el("button", { class: "send", type: "button", "aria-label": "Send message" });
    this.sendBtn.append(svgIcon(ICONS.send, 18));
    this.sendBtn.addEventListener("click", () => void this.send());

    this.panel = el(
      "div",
      { class: "panel", role: "dialog", "aria-label": `Chat with ${settings.team_name}`, hidden: true },
      el(
        "div",
        { class: "header" },
        el("div", { class: "grow" }, el("h2", {}, settings.team_name), el("p", {}, "We usually reply in a few minutes")),
        closeBtn,
      ),
      this.body,
      this.typingEl,
      this.errorEl,
      el("div", { class: "composer" }, this.textarea, this.sendBtn),
      el("div", { class: "footer" }, "Powered by ResolveAI"),
    );

    this.root = el("div", { class: `root ${settings.launcher_position === "left" ? "left" : "right"}` }, this.panel, launcher);
    this.root.style.setProperty("--rai-brand", safeColor(settings.brand_color));
    this.shadow.replaceChildren(style, this.root);
    this.renderMessages();
  }

  private renderMessages(): void {
    if (!this.body || !this.settings) return;
    const nodes: Node[] = [];
    nodes.push(this.messageRow({ me: false, body: this.settings.welcome_message, meta: this.settings.team_name }));

    const sorted = [...this.messages.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const m of sorted) {
      const me = m.author_type === "customer";
      const row = this.messageRow({ me, body: m.body, meta: `${me ? "You" : m.author_name || this.settings.team_name} · ${formatTime(m.created_at)}` });
      for (const att of m.attachments) {
        const btn = el("button", { class: "attachment", type: "button" });
        btn.append(svgIcon(ICONS.paperclip, 14), document.createTextNode(att.filename));
        btn.addEventListener("click", () => void this.openAttachment(att.id, att.filename));
        row.append(btn);
      }
      nodes.push(row);
    }

    const status = this.conversation?.status;
    if (status === "resolved" || status === "closed") {
      nodes.push(el("div", { class: "notice" }, "This conversation has been resolved. Send a message to start a new one."));
    }
    const hasCustomerMessage = sorted.some((m) => m.author_type === "customer");
    if (this.settings.collect_email && hasCustomerMessage && !this.visitor.email && !this.emailDismissed) {
      nodes.push(this.emailCard());
    }
    this.body.replaceChildren(...nodes);
    this.body.scrollTop = this.body.scrollHeight;
  }

  private messageRow({ me, body, meta }: { me: boolean; body: string; meta: string }): HTMLDivElement {
    return el("div", { class: `row ${me ? "me" : "them"}` }, el("div", { class: "bubble" }, body), el("div", { class: "meta" }, meta));
  }

  private emailCard(): HTMLDivElement {
    const input = el("input", { type: "email", placeholder: "you@example.com", "aria-label": "Your email", autocomplete: "email", required: true });
    const form = el("form", {}, input, el("button", { class: "btn", type: "submit" }, "Save"));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const email = input.value.trim();
      if (!email) return;
      this.identify({ email }).catch(() => this.showError("Please enter a valid email address."));
    });
    const dismiss = el("button", { class: "btn secondary", type: "button" }, "No thanks");
    dismiss.addEventListener("click", () => {
      this.emailDismissed = true;
      this.renderMessages();
    });
    return el("div", { class: "card" }, el("label", {}, "Get notified by email when we reply"), form, dismiss);
  }

  private updateBadge(): void {
    this.badge.hidden = this.unread === 0;
    this.badge.textContent = this.unread > 9 ? "9+" : String(this.unread);
  }

  private autoGrow(): void {
    this.textarea.style.height = "auto";
    this.textarea.style.height = `${Math.min(this.textarea.scrollHeight, 120)}px`;
  }

  private showError(message: string | null): void {
    this.errorEl.hidden = !message;
    this.errorEl.textContent = message ?? "";
  }

  // ---------------------------------------------------------------------------
  // Data
  // ---------------------------------------------------------------------------
  private async loadMessages(): Promise<void> {
    if (!this.conversation) return this.renderMessages();
    try {
      const messages = await this.api.listMessages(this.conversation.id);
      this.messages = new Map(messages.map((m) => [m.id, m]));
      this.renderMessages();
    } catch {
      this.showError("Couldn't load messages. Please try again.");
    }
  }

  async send(): Promise<void> {
    const body = this.textarea.value.trim();
    if (!body || this.sending) return;
    this.sending = true;
    this.sendBtn.disabled = true;
    this.showError(null);
    try {
      const reuse = this.conversation && this.conversation.status !== "resolved" && this.conversation.status !== "closed";
      if (reuse && this.conversation) {
        const message = await this.api.sendMessage(this.conversation.id, body);
        this.messages.set(message.id, message);
      } else {
        this.conversation = await this.api.startConversation(body);
        this.messages.clear();
        await this.loadMessages();
        this.connectSocket();
      }
      this.textarea.value = "";
      this.autoGrow();
      this.renderMessages();
    } catch (error) {
      this.showError(
        error instanceof WidgetApiError && error.status === 429
          ? "You're sending messages too quickly. Please wait a moment."
          : "Message not sent. Please try again.",
      );
    } finally {
      this.sending = false;
      this.sendBtn.disabled = false;
    }
  }

  private async openAttachment(id: string, filename: string): Promise<void> {
    try {
      const blob = await this.api.downloadAttachment(id);
      const url = URL.createObjectURL(blob);
      const a = el("a", { href: url, download: filename, rel: "noopener" });
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      this.showError("Couldn't download the file.");
    }
  }

  // ---------------------------------------------------------------------------
  // Real-time
  // ---------------------------------------------------------------------------
  private connectSocket(): void {
    if (this.socket) return;
    const wsUrl = `${this.config.apiUrl.replace(/^http/, "ws")}/ws/widget/`;
    this.socket = new WidgetSocket(
      wsUrl,
      async (refresh) => {
        if (refresh || !this.api.sessionToken) await this.api.startSession();
        return this.api.sessionToken;
      },
      (event) => this.handleEvent(event),
    );
    void this.socket.connect();
  }

  handleEvent(event: ServerEvent): void {
    if (event.type === "message.created") {
      if (this.conversation && event.conversation_id !== this.conversation.id) return;
      const isNew = !this.messages.has(event.message.id);
      this.messages.set(event.message.id, event.message);
      if (this.conversation) this.conversation = { ...this.conversation, status: event.message.author_type === "customer" ? "open" : this.conversation.status };
      if (isNew && event.message.author_type !== "customer") {
        this.typingEl.textContent = "";
        if (!this.isOpen) {
          this.unread += 1;
          this.updateBadge();
        }
      }
      this.renderMessages();
    } else if (event.type === "typing" && event.actor === "agent") {
      if (this.conversation && event.conversation_id !== this.conversation.id) return;
      this.typingEl.textContent = `${event.name || "Support"} is typing…`;
      if (this.typingTimer) clearTimeout(this.typingTimer);
      this.typingTimer = setTimeout(() => (this.typingEl.textContent = ""), TYPING_DISPLAY_MS);
    }
  }

  private sendTyping(): void {
    if (!this.conversation || !this.socket) return;
    const now = Date.now();
    if (now - this.lastTypingSent < TYPING_SEND_INTERVAL) return;
    this.lastTypingSent = now;
    this.socket.send({ type: "typing", conversation_id: this.conversation.id });
  }
}
