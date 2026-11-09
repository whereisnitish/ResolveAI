import type { Metadata } from "next";
import { Suspense } from "react";

import { AcceptInvitation } from "@/components/auth/accept-invitation";
import { AuthCardSkeleton } from "@/components/auth/auth-card";

export const metadata: Metadata = { title: "Accept invitation" };

export default function InvitePage() {
  return (
    <Suspense fallback={<AuthCardSkeleton />}>
      <AcceptInvitation />
    </Suspense>
  );
}
