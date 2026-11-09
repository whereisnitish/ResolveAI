// Scoped to the widget's shadow root; host page CSS can't leak in or out.
export const STYLES = `
:host { all: initial; }
* { box-sizing: border-box; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.root { position: fixed; bottom: 20px; z-index: 2147483000; }
.root.right { right: 20px; } .root.left { left: 20px; }
.launcher { width: 56px; height: 56px; border-radius: 50%; border: 0; cursor: pointer; color: #fff;
  background: var(--rai-brand); box-shadow: 0 8px 24px rgba(15,23,42,.24); display: grid; place-items: center;
  transition: transform .15s ease; position: relative; }
.launcher:hover { transform: scale(1.05); }
.launcher:focus-visible, button:focus-visible, textarea:focus-visible, input:focus-visible { outline: 3px solid color-mix(in srgb, var(--rai-brand) 45%, transparent); outline-offset: 2px; }
.badge { position: absolute; top: -2px; right: -2px; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px;
  background: #ef4444; color: #fff; font-size: 12px; font-weight: 600; line-height: 20px; text-align: center; }
.panel { position: absolute; bottom: 72px; width: 372px; height: min(600px, calc(100vh - 112px)); background: #fff;
  border-radius: 16px; box-shadow: 0 16px 48px rgba(15,23,42,.22); display: flex; flex-direction: column; overflow: hidden;
  color: #0f172a; font-size: 14px; }
.root.right .panel { right: 0; } .root.left .panel { left: 0; }
.panel[hidden] { display: none; }
.header { background: var(--rai-brand); color: #fff; padding: 18px 16px 16px; display: flex; align-items: flex-start; gap: 12px; }
.header h2 { margin: 0; font-size: 16px; font-weight: 600; }
.header p { margin: 4px 0 0; font-size: 13px; opacity: .85; }
.header .grow { flex: 1; min-width: 0; }
.icon-btn { background: transparent; border: 0; color: inherit; cursor: pointer; padding: 4px; border-radius: 8px; display: grid; place-items: center; }
.icon-btn:hover { background: rgba(255,255,255,.15); }
.body { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; background: #f8fafc; }
.row { display: flex; flex-direction: column; max-width: 82%; }
.row.me { align-self: flex-end; align-items: flex-end; }
.row.them { align-self: flex-start; align-items: flex-start; }
.bubble { padding: 9px 12px; border-radius: 14px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.me .bubble { background: var(--rai-brand); color: #fff; border-bottom-right-radius: 4px; }
.them .bubble { background: #fff; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; }
.meta { font-size: 11px; color: #64748b; margin: 3px 4px 0; }
.attachment { margin-top: 4px; background: none; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 10px; cursor: pointer;
  font-size: 12px; color: #0f172a; display: inline-flex; align-items: center; gap: 6px; background: #fff; }
.typing { font-size: 12px; color: #64748b; padding: 0 4px; min-height: 16px; }
.notice { align-self: center; text-align: center; font-size: 12px; color: #64748b; padding: 8px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; display: grid; gap: 8px; }
.card label { font-size: 12px; color: #475569; }
.card form { display: flex; gap: 6px; }
.card input { flex: 1; min-width: 0; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; font-size: 14px; }
.btn { border: 0; border-radius: 8px; padding: 8px 12px; background: var(--rai-brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.btn.secondary { background: #e2e8f0; color: #0f172a; }
.composer { border-top: 1px solid #e2e8f0; padding: 10px; display: flex; gap: 8px; align-items: flex-end; background: #fff; }
.composer textarea { flex: 1; resize: none; border: 1px solid #cbd5e1; border-radius: 12px; padding: 9px 12px; font-size: 14px;
  max-height: 120px; min-height: 40px; line-height: 1.4; color: #0f172a; }
.send { width: 40px; height: 40px; border-radius: 12px; border: 0; background: var(--rai-brand); color: #fff; cursor: pointer; display: grid; place-items: center; }
.send:disabled { opacity: .5; cursor: default; }
.error { color: #b91c1c; font-size: 12px; padding: 0 12px 8px; }
.footer { text-align: center; font-size: 11px; color: #94a3b8; padding: 0 0 8px; background: #fff; }
@media (max-width: 480px) {
  .root { bottom: 16px; } .root.right { right: 16px; } .root.left { left: 16px; }
  .panel { position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0; bottom: 0; }
}
@media (prefers-reduced-motion: reduce) { .launcher { transition: none; } }
`;
