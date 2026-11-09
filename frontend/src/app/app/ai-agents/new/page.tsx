import type { Metadata } from "next";

import { NewAgent } from "@/components/app/ai/new-agent";

export const metadata: Metadata = { title: "New AI agent" };

export const instant = false;

export default function Page() {
  return <NewAgent />;
}
