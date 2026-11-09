import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(window as unknown as { __RESOLVEAI_TEST__: boolean }).__RESOLVEAI_TEST__ = true;

import { WidgetApi, WidgetApiError } from "./api";
import { ResolveWidget } from "./app";
import { el, safeColor } from "./dom";
import { readConfig } from "./index";
import { loadVisitorToken, saveVisitorToken, storageKey } from "./storage";
import type { SessionResponse, WidgetMessage } from "./types";

const CONFIG = { workspaceId: "ws_abcdefghijkl", apiUrl: "http://api.test" };

const SESSION: SessionResponse = {
  session_token: "sess-1",
  expires_in: 3600,
  visitor_token: "visitor-1",
  visitor: { name: "", email: "" },
  settings: {
    brand_color: "#123456",
    team_name: "Acme Support",
    welcome_message: "Hi there!",
    launcher_position: "right",
    collect_email: true,
  },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function message(overrides: Partial<WidgetMessage> = {}): WidgetMessage {
  return {
    id: crypto.randomUUID(),
    conversation_id: "c1",
    body: "Hello",
    author_type: "agent",
    author_name: "Asha",
    attachments: [],
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML = "";
});
afterEach(() => vi.restoreAllMocks());

describe("readConfig", () => {
  const script = (attrs: Record<string, string>) => {
    const s = document.createElement("script");
    Object.assign(s.dataset, attrs);
    return s;
  };

  it("accepts a valid workspace id and strips trailing slashes", () => {
    expect(readConfig(script({ workspaceId: "ws_abcdefghijkl", apiUrl: "http://localhost:8000/" }))).toEqual({
      workspaceId: "ws_abcdefghijkl",
      apiUrl: "http://localhost:8000",
    });
  });

  it.each([{}, { workspaceId: "bad" }, { workspaceId: "ws_abcdefghijkl", apiUrl: "javascript:alert(1)" }])(
    "rejects %o",
    (attrs) => expect(readConfig(script(attrs as Record<string, string>))).toBeNull(),
  );
});

describe("storage", () => {
  it("round-trips the visitor token per workspace", () => {
    saveVisitorToken("ws_a", "tok");
    expect(localStorage.getItem(storageKey("ws_a"))).toBe("tok");
    expect(loadVisitorToken("ws_a")).toBe("tok");
    expect(loadVisitorToken("ws_b")).toBeNull();
  });

  it("survives a throwing localStorage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadVisitorToken("ws_a")).toBeNull();
  });
});

describe("WidgetApi", () => {
  it("never sends cookies and stores the visitor token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, SESSION));
    const api = new WidgetApi(CONFIG, fetchMock);
    await api.startSession();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/widget/session/");
    expect(init.credentials).toBe("omit");
    expect(loadVisitorToken(CONFIG.workspaceId)).toBe("visitor-1");
    api.stop();
  });

  it("refreshes the session once on 401 and retries", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(json(401, { error: { code: "widget_session_invalid", message: "expired" } }))
      .mockResolvedValueOnce(json(200, { ...SESSION, session_token: "sess-2" }))
      .mockResolvedValueOnce(json(200, []));
    const api = new WidgetApi(CONFIG, fetchMock);
    await api.startSession();
    await expect(api.listConversations()).resolves.toEqual([]);
    expect(fetchMock.mock.calls[3][1].headers.Authorization).toBe("Bearer sess-2");
    api.stop();
  });

  it("surfaces API errors with code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(403, { error: { code: "origin_not_allowed", message: "no" } }));
    const api = new WidgetApi(CONFIG, fetchMock);
    const error = await api.startSession().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(WidgetApiError);
    expect((error as WidgetApiError).code).toBe("origin_not_allowed");
  });
});

describe("dom safety", () => {
  it("el() renders strings as text and refuses inline handlers", () => {
    const node = el("div", {}, "<img src=x onerror=alert(1)>");
    expect(node.querySelector("img")).toBeNull();
    expect(node.textContent).toBe("<img src=x onerror=alert(1)>");
    expect(() => el("div", { onclick: "alert(1)" })).toThrow();
  });

  it("only accepts #rrggbb brand colours", () => {
    expect(safeColor("#abcdef")).toBe("#abcdef");
    expect(safeColor("red; background:url(x)")).toBe("#4f46e5");
  });
});

describe("ResolveWidget", () => {
  async function mount(conversations: unknown[] = []) {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(200, SESSION)).mockResolvedValueOnce(json(200, conversations));
    const api = new WidgetApi(CONFIG, fetchMock);
    const widget = new ResolveWidget(CONFIG, api);
    await widget.start();
    return { widget, fetchMock };
  }

  it("mounts a branded launcher in a shadow root with the welcome message", async () => {
    const { widget } = await mount();
    const root = widget.shadow.querySelector<HTMLElement>(".root")!;
    expect(root.style.getPropertyValue("--rai-brand")).toBe("#123456");
    expect(widget.shadow.querySelector(".launcher")?.getAttribute("aria-label")).toBe("Chat with Acme Support");
    expect(widget.shadow.textContent).toContain("Hi there!");
    expect(document.body.querySelector("[data-resolveai-widget]")).not.toBeNull();
    widget.destroy();
  });

  it("renders hostile message bodies as plain text", async () => {
    const { widget } = await mount();
    widget.handleEvent({
      type: "message.created",
      conversation_id: "c1",
      message: message({ body: '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>' }),
    });
    expect(widget.shadow.querySelector(".body img")).toBeNull();
    expect(widget.shadow.querySelector(".body script")).toBeNull();
    expect(widget.shadow.textContent).toContain("<script>window.pwned=1</script>");
    widget.destroy();
  });

  it("counts unread agent messages while closed and clears on open", async () => {
    const { widget } = await mount();
    widget.handleEvent({ type: "message.created", conversation_id: "c1", message: message() });
    const badge = widget.shadow.querySelector<HTMLElement>(".badge")!;
    expect(badge.hidden).toBe(false);
    expect(badge.textContent).toBe("1");
    widget.open();
    expect(badge.hidden).toBe(true);
    widget.destroy();
  });

  it("shows agent typing indicator", async () => {
    const { widget } = await mount();
    widget.handleEvent({ type: "typing", conversation_id: "c1", actor: "agent", name: "Asha" });
    expect(widget.shadow.querySelector(".typing")?.textContent).toBe("Asha is typing…");
    widget.destroy();
  });

  it("starts a conversation on first send", async () => {
    const { widget, fetchMock } = await mount();
    const conv = { id: "c9", number: 1, status: "open", last_message_preview: "Hi", last_message_at: "" };
    fetchMock
      .mockResolvedValueOnce(json(201, conv))
      .mockResolvedValueOnce(json(200, [message({ author_type: "customer", conversation_id: "c9", body: "Hi" })]));
    vi.stubGlobal("WebSocket", class { readyState = 0; send() {} close() {} });
    widget.shadow.querySelector<HTMLTextAreaElement>("textarea")!.value = "Hi";
    await widget.send();
    const [url, init] = fetchMock.mock.calls[2];
    expect(url).toBe("http://api.test/api/v1/widget/conversations/");
    expect(JSON.parse(init.body)).toEqual({ body: "Hi" });
    expect(widget.shadow.textContent).toContain("Get notified by email");
    widget.destroy();
    vi.unstubAllGlobals();
  });
});
