import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { SourceDetail } from "@/components/app/knowledge/source-detail";

export const metadata: Metadata = { title: "Knowledge source" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={5} className="mx-auto max-w-4xl" />}>
      <SourceDetail />
    </Suspense>
  );
}
