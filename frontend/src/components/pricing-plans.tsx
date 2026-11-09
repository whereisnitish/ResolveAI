"use client";

import Link from "next/link";
import { useState } from "react";

import { PlanGrid } from "@/components/app/billing/billing-page";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlans } from "@/lib/platform";
import { cn } from "@/lib/utils";

export function PricingPlans() {
  const plans = usePlans();
  const [currency, setCurrency] = useState<"INR" | "USD">("USD");
  return (
    <div>
      <div className="mb-6 flex justify-center">
        <div className="flex rounded-lg border p-0.5" role="group" aria-label="Currency">
          {(["USD", "INR"] as const).map((c) => (
            <button key={c} aria-pressed={currency === c} onClick={() => setCurrency(c)} className={cn("rounded-md px-3 py-1 text-sm font-medium", currency === c ? "bg-primary text-primary-foreground" : "text-muted-foreground")}>
              {c === "USD" ? "USD $" : "INR ₹"}
            </button>
          ))}
        </div>
      </div>
      {plans.isPending ? (
        <div className="grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-80" />
          ))}
        </div>
      ) : plans.isError ? (
        <p className="text-center text-sm text-muted-foreground">Pricing is unavailable right now. Please try again shortly.</p>
      ) : (
        <PlanGrid
          plans={plans.data}
          currency={currency}
          currentCode={null}
          action={() => (
            <Button className="w-full" render={<Link href="/signup" />}>
              Start free trial
            </Button>
          )}
        />
      )}
    </div>
  );
}
