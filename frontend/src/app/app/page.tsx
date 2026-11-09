import type { Metadata } from "next";

import { Dashboard } from "@/components/app/dashboard";

export const metadata: Metadata = { title: "Dashboard" };

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function DashboardPage() {
  return <Dashboard />;
}
