"use client";

// Last-resort boundary: replaces the root layout, so it must render <html>/<body>
// and cannot rely on app styles or providers.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <main role="alert" style={{ textAlign: "center", padding: 24 }}>
          <h1 style={{ fontSize: 20 }}>ResolveAI is having trouble</h1>
          <p style={{ color: "#555" }}>An unexpected error occurred. Please try again.</p>
          {error.digest ? <p style={{ color: "#777", fontSize: 12 }}>Reference: {error.digest}</p> : null}
          <button type="button" onClick={reset} style={{ marginTop: 12, padding: "8px 16px" }}>
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
