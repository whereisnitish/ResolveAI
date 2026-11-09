/**
 * ResolveAI website widget bootstrap.
 *
 *   <script src="https://cdn.resolveai.com/widget.js"
 *           data-workspace-id="ws_XXXX"
 *           data-api-url="https://api.resolveai.com" async></script>
 *
 * Public API (window.ResolveAI): open(), close(), identify({ name, email }), shutdown().
 */
import { ResolveWidget } from "./app";
import type { Visitor, WidgetConfig } from "./types";

const DEFAULT_API_URL = "https://api.resolveai.com";

export function readConfig(script: HTMLScriptElement | null): WidgetConfig | null {
  const workspaceId = script?.dataset.workspaceId?.trim();
  if (!workspaceId || !/^ws_[A-Za-z0-9_-]{8,40}$/.test(workspaceId)) return null;
  const apiUrl = (script?.dataset.apiUrl?.trim() || DEFAULT_API_URL).replace(/\/+$/, "");
  if (!/^https?:\/\//.test(apiUrl)) return null;
  return { workspaceId, apiUrl };
}

interface PublicApi {
  open(): void;
  close(): void;
  identify(data: Partial<Visitor>): Promise<void>;
  shutdown(): void;
}

declare global {
  interface Window {
    ResolveAI?: PublicApi;
  }
}

function boot(): void {
  if (window.ResolveAI) return; // already loaded on this page
  const script =
    (document.currentScript as HTMLScriptElement | null) ??
    document.querySelector<HTMLScriptElement>("script[data-workspace-id]");
  const config = readConfig(script);
  if (!config) {
    console.warn("[ResolveAI] Missing or invalid data-workspace-id on the widget script tag.");
    return;
  }
  const widget = new ResolveWidget(config);
  window.ResolveAI = {
    open: () => widget.open(),
    close: () => widget.close(),
    identify: (data) => widget.identify(data),
    shutdown: () => {
      widget.destroy();
      delete window.ResolveAI;
    },
  };
  const start = () =>
    widget.start().catch((error: unknown) => {
      console.warn("[ResolveAI] Chat is unavailable.", error);
    });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else void start();
}

if (typeof window !== "undefined" && !(window as { __RESOLVEAI_TEST__?: boolean }).__RESOLVEAI_TEST__) boot();
