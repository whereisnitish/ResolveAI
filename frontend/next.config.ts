import type { NextConfig } from "next";

// Server-side only: where the Next.js server forwards /api/* requests.
// The browser always talks to the same origin, so the Django session cookie
// stays first-party, HttpOnly and SameSite=Lax.
const backendUrl = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

const isDev = process.env.NODE_ENV !== "production";

function origin(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

// Content-Security-Policy. Scripts are limited to our own origin; 'unsafe-inline'
// is still required for Next's inline bootstrap and the theme script (a nonce-based
// policy would force every page to render dynamically — see docs/architecture/SECURITY.md).
// connect-src lists the realtime socket and, if separate, the API origin.
const connectSrc = new Set(["'self'"]);
const wsOrigin = origin(process.env.NEXT_PUBLIC_WS_URL);
if (wsOrigin) connectSrc.add(wsOrigin.replace(/^http/, "ws"));
if (isDev) connectSrc.add("ws:"); // Turbopack HMR

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src ${[...connectSrc].join(" ")}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // Self-contained server bundle for the production image (no node_modules copy).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  // Django URLs end with "/"; don't let Next strip the slash before proxying.
  skipTrailingSlashRedirect: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/api/:path*/", destination: `${backendUrl}/api/:path*/` },
        { source: "/api/:path*", destination: `${backendUrl}/api/:path*/` },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
