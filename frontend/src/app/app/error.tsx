"use client";

import { ErrorState } from "@/components/error-state";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <ErrorState
      title="This page failed to load"
      description="Something went wrong while loading this view. Your data is safe — try again, or go back to the inbox."
      digest={error.digest}
      onRetry={reset}
      homeHref="/app/inbox"
    />
  );
}
