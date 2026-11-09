import { Suspense } from "react";

import { ListSkeleton } from "@/components/app/common";
import { ConversationPane } from "@/components/app/inbox/conversation-pane";

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function ConversationPage() {
  // useParams() resolves at request time for this dynamic route, so it must sit inside Suspense.
  return (
    <Suspense fallback={<ListSkeleton rows={8} className="p-6" />}>
      <ConversationPane />
    </Suspense>
  );
}
