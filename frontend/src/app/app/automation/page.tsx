import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { WorkflowsPage } from "@/components/app/automation/workflows-page";

export const metadata: Metadata = { title: "Automation" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={5} className="mx-auto max-w-5xl" />}>
      <WorkflowsPage />
    </Suspense>
  );
}
