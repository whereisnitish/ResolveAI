import { MessagesSquare } from "lucide-react";

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function InboxIndexPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center p-8 text-center">
      <div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground">
        <MessagesSquare className="size-6" />
      </div>
      <p className="font-medium">Select a conversation</p>
      <p className="mt-1 max-w-xs text-sm text-muted-foreground">
        Pick a conversation from the list to read and reply. New messages arrive in real time.
      </p>
    </div>
  );
}
