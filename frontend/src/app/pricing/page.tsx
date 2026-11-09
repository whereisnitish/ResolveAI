import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/brand";
import { PricingPlans } from "@/components/pricing-plans";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Simple monthly plans in INR or USD. Start with a 14-day free trial.",
};

export default function PricingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav className="flex items-center gap-2">
            <Button variant="ghost" render={<Link href="/login" />}>
              Sign in
            </Button>
            <Button render={<Link href="/signup" />}>Start free trial</Button>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-16 sm:px-6">
        <div className="mb-10 text-center">
          <h1 className="text-4xl font-semibold tracking-tight">Simple, predictable pricing</h1>
          <p className="mt-3 text-muted-foreground">
            Every plan starts with a 14-day free trial. Pay in INR via Razorpay or in USD via Stripe.
          </p>
        </div>
        <PricingPlans />
      </main>
    </div>
  );
}
