import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { AnalyticsPage } from "@/components/app/analytics/analytics-page";

export const metadata: Metadata = { title: "Analytics" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={5} className="mx-auto max-w-5xl" />}>
      <AnalyticsPage />
    </Suspense>
  );
}
