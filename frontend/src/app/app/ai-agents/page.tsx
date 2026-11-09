import type { Metadata } from "next";

import { AgentsList } from "@/components/app/ai/agents-list";

export const metadata: Metadata = { title: "AI Agents" };

// Dashboard pages render after the client-side session check (see app/layout).
export const instant = false;

export default function Page() {
  return <AgentsList />;
}
