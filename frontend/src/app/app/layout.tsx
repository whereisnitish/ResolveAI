import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell, ShellSkeleton } from "@/components/app/app-shell";

export const metadata: Metadata = { title: { default: "Dashboard", template: "%s · ResolveAI" } };

export default function AppLayout({ children }: LayoutProps<"/app">) {
  // The shell reads the pathname (active nav, inbox layout); on dynamic routes
  // that's request-time data, so it streams in behind this boundary.
  return (
    <Suspense fallback={<ShellSkeleton />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
