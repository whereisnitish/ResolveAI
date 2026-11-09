import type { Metadata } from "next";
import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { InboxLayout } from "@/components/app/inbox/inbox-layout";

export const metadata: Metadata = { title: "Inbox" };

export default function Layout({ children }: LayoutProps<"/app/inbox">) {
  return (
    <Suspense fallback={<ListSkeleton rows={8} />}>
      <InboxLayout>{children}</InboxLayout>
    </Suspense>
  );
}
