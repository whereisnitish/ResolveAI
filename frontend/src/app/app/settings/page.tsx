import type { Metadata } from "next";
import { Suspense } from "react";

import { SettingsPage } from "@/components/app/settings/settings-page";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Settings" };

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="mx-auto h-96 max-w-3xl rounded-xl" />}>
      <SettingsPage />
    </Suspense>
  );
}
