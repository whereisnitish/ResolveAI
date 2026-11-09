import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { BillingPage } from "@/components/app/billing/billing-page";

export const metadata: Metadata = { title: "Billing" };

export const instant = false;

export default function Page() {
  return (
    <Suspense fallback={<ListSkeleton rows={5} className="mx-auto max-w-5xl" />}>
      <BillingPage />
    </Suspense>
  );
}
