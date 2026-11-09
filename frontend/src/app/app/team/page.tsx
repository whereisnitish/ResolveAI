import type { Metadata } from "next";

import { TeamPage } from "@/components/app/team/team-page";

export const metadata: Metadata = { title: "Team" };

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function Page() {
  return <TeamPage />;
}
