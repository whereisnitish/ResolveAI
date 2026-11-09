import type { Metadata } from "next";

import { KnowledgeHub } from "@/components/app/knowledge/knowledge-hub";

export const metadata: Metadata = { title: "Knowledge Hub" };

export const instant = false;

export default function Page() {
  return <KnowledgeHub />;
}
