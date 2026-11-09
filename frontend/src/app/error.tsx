"use client";

import { ErrorState } from "@/components/error-state";

export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <ErrorState
      title="Something went wrong"
      description="An unexpected error occurred. It has been logged; please try again."
      digest={error.digest}
      onRetry={reset}
    />
  );
}
