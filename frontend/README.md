# ResolveAI — Frontend

Next.js 16 dashboard and public site. See the root [README](../README.md) and
[docs/architecture/ARCHITECTURE.md](../docs/architecture/ARCHITECTURE.md#8-frontend-architecture).

```bash
npm install
npm run dev        # http://localhost:3000 (proxies /api/* to BACKEND_INTERNAL_URL, default http://localhost:8000)
npm test           # vitest
npm run lint && npm run typecheck && npm run build
```

Read `AGENTS.md` before changing framework-level code: this Next.js version differs from older ones.
