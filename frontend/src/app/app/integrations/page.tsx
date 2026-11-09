import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { IntegrationsPage } from "@/components/app/integrations/integrations-page";

export const metadata: Metadata = { title: "Integrations" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={5} className="mx-auto max-w-5xl" />}>
      <IntegrationsPage />
    </Suspense>
  );
}
