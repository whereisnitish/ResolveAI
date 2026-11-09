import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { CustomerDetail } from "@/components/app/customers/customer-detail";

export const metadata: Metadata = { title: "Customer" };

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function CustomerPage() {
  return (
    <Suspense fallback={<ListSkeleton rows={6} className="mx-auto max-w-5xl" />}>
      <CustomerDetail />
    </Suspense>
  );
}
