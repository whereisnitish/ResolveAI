import type { Metadata } from "next";
import { Suspense } from "react";

import { AgentDetail } from "@/components/app/ai/agent-detail";
import { ListSkeleton } from "@/components/app/common";

export const metadata: Metadata = { title: "AI agent" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={6} className="mx-auto max-w-5xl" />}>
      <AgentDetail />
    </Suspense>
  );
}
