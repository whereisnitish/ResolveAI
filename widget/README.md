# ResolveAI website widget

An embeddable chat widget written in vanilla TypeScript with no runtime dependencies. It is bundled into a single file, `dist/widget.js` (~17 KB, ~6 KB gzipped).

## Install on a website

```html
<script src="https://cdn.resolveai.com/widget.js"
        data-workspace-id="ws_XXXXXXXX"
        data-api-url="https://api.resolveai.com" async></script>
```

You can copy the exact snippet for a workspace from **Dashboard → Settings → Widget**.

JavaScript API:

```js
ResolveAI.open();
ResolveAI.close();
ResolveAI.identify({ name: "Asha", email: "asha@example.com" }); // unverified, own record only
ResolveAI.shutdown();
```

## Security model

* The snippet contains only the public workspace id; there are no API keys.
* The visitor token (in localStorage) is exchanged for a 1-hour bearer session token, which is refreshed automatically.
* Requests never send cookies (`credentials: "omit"`). The WebSocket authenticates with a first frame, not the URL.
* Everything renders inside a Shadow DOM, and message text is inserted with `textContent` only.
* The backend enforces the workspace's allowed origins, per-visitor isolation and rate limits. See `docs/decisions/0006-widget-auth-and-identity.md`.

## Development

```bash
npm install
npm run dev        # builds on change and serves demo/ on http://localhost:3002
# open http://localhost:3002/?ws=<public workspace id>&api=http://localhost:8000
npm test           # vitest (jsdom)
npm run typecheck
npm run build      # dist/widget.js
```

If you restrict **Allowed websites** in the dashboard, add `http://localhost:3002` while testing locally.
