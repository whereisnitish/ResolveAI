import type { Metadata } from "next";

import { CustomerList } from "@/components/app/customers/customer-list";

export const metadata: Metadata = { title: "Customers" };

// Dashboard pages render only after the client-side session check (/auth/me),
// so they can't be validated for instant navigation during server rendering.
export const instant = false;

export default function CustomersPage() {
  return <CustomerList />;
}
