"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CreditCard, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { formatDateTime, ListSkeleton } from "@/components/app/common";
import { PageHeader } from "@/components/app/page-header";
import { EmptyState, ErrorState } from "@/components/app/team/team-page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { compact, formatMoney, useBilling, useInvoices, usePlans, type BillingOverview, type Plan } from "@/lib/platform";
import { cn } from "@/lib/utils";

const STATUS_COPY: Record<BillingOverview["subscription"]["status"], { label: string; tone: string }> = {
  trialing: { label: "Free trial", tone: "bg-blue-50 text-blue-800" },
  active: { label: "Active", tone: "bg-emerald-50 text-emerald-800" },
  past_due: { label: "Payment due", tone: "bg-amber-50 text-amber-900" },
  canceled: { label: "Canceled", tone: "bg-muted text-muted-foreground" },
  expired: { label: "Trial ended", tone: "bg-red-50 text-red-800" },
};

export function BillingPage() {
  const { organization, canOrg } = useApp();
  const orgId = organization?.id;
  const canView = canOrg("org.billing.view");
  const canManage = canOrg("org.billing.manage");
  const billing = useBilling(orgId, canView);
  const invoices = useInvoices(orgId, canView);
  const plans = usePlans();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [currency, setCurrency] = useState<"INR" | "USD" | null>(null);

  useEffect(() => {
    const result = params.get("checkout");
    if (result === "success") toast.success("Payment received — your plan is active.");
    if (result === "cancelled") toast.info("Checkout cancelled.");
  }, [params]);

  const checkout = useMutation({
    mutationFn: (plan: string) =>
      api.post<{ provider: string; checkout_url: string }>(`organizations/${orgId}/billing/checkout`, { plan, currency: currency ?? billing.data?.subscription.currency }),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: ["organizations", orgId] });
      if (r.provider === "mock") toast.success("Plan updated (development mock payment).");
      else window.location.assign(r.checkout_url);
    },
    onError: (e) => toast.error(e.message),
  });

  if (!canView) {
    return (
      <div className="mx-auto max-w-5xl">
        <PageHeader title="Billing" />
        <EmptyState icon={<CreditCard className="size-6" />} title="No billing access" description="Ask an owner or billing admin." />
      </div>
    );
  }
  if (billing.isPending) return <ListSkeleton rows={6} className="mx-auto max-w-5xl" />;
  if (billing.isError) return <ErrorState message={billing.error.message} onRetry={() => billing.refetch()} />;

  const b = billing.data;
  const cur = currency ?? b.subscription.currency;
  const status = STATUS_COPY[b.subscription.status];
  const meters: { label: string; used: number; limit: number; unit?: string }[] = [
    { label: "AI replies this period", used: b.usage.ai_executions, limit: b.limits.ai_executions_per_month },
    { label: "Seats (members + invites)", used: b.usage.seats, limit: b.limits.seats },
    { label: "Workspaces", used: b.usage.workspaces, limit: b.limits.workspaces },
    { label: "Knowledge storage", used: b.usage.knowledge_mb, limit: b.limits.knowledge_mb, unit: "MB" },
  ];

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Billing" description={`Plan and usage for ${organization?.name}.`} />
      <div className="grid gap-6">
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-4 pt-6">
            <div>
              <p className="flex items-center gap-2 text-lg font-semibold">
                {b.subscription.plan.name}
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", status.tone)}>{status.label}</span>
              </p>
              <p className="text-sm text-muted-foreground">
                {b.subscription.status === "trialing" && b.subscription.trial_days_left != null
                  ? `${b.subscription.trial_days_left} day(s) left in your trial.`
                  : b.subscription.current_period_end
                    ? `Current period ends ${formatDateTime(b.subscription.current_period_end)}.`
                    : ""}
                {!b.subscription.is_active ? " AI replies are paused until you choose a plan; the inbox keeps working." : ""}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              Payments via {b.checkout_provider === "razorpay" ? "Razorpay (India)" : b.checkout_provider === "stripe" ? "Stripe" : b.checkout_provider === "mock" ? "development mock" : "—"}
            </p>
          </CardContent>
        </Card>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {meters.map((m) => {
            const ratio = m.limit > 0 ? Math.min(1, m.used / m.limit) : 1;
            return (
              <Card key={m.label} className="gap-2 p-4">
                <p className="text-xs text-muted-foreground">{m.label}</p>
                <p className="text-lg font-semibold tabular-nums">
                  {compact.format(m.used)}
                  <span className="text-sm font-normal text-muted-foreground">
                    {" "}
                    / {compact.format(m.limit)} {m.unit ?? ""}
                  </span>
                </p>
                <div
                  className="h-1.5 overflow-hidden rounded-full bg-muted"
                  role="meter"
                  aria-valuenow={m.used}
                  aria-valuemin={0}
                  aria-valuemax={m.limit}
                  aria-label={m.label}
                >
                  <div className={cn("h-full rounded-full", ratio >= 1 ? "bg-destructive" : ratio > 0.8 ? "bg-amber-500" : "bg-primary")} style={{ width: `${ratio * 100}%` }} />
                </div>
              </Card>
            );
          })}
        </div>
        <p className="-mt-3 text-xs text-muted-foreground">
          Tokens this period: {compact.format(b.usage.ai_input_tokens)} in · {compact.format(b.usage.ai_output_tokens)} out · {compact.format(b.usage.embedding_tokens)} embedding.
        </p>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Plans</h2>
            <div className="flex rounded-lg border p-0.5" role="group" aria-label="Currency">
              {(["INR", "USD"] as const).map((c) => (
                <button key={c} aria-pressed={cur === c} onClick={() => setCurrency(c)} className={cn("rounded-md px-2.5 py-1 text-xs font-medium", cur === c ? "bg-primary text-primary-foreground" : "text-muted-foreground")}>
                  {c}
                </button>
              ))}
            </div>
          </div>
          <PlanGrid
            plans={plans.data ?? []}
            currency={cur}
            currentCode={b.subscription.is_active ? b.subscription.plan.code : null}
            action={(p) =>
              canManage ? (
                <Button className="w-full" onClick={() => checkout.mutate(p.code)} disabled={checkout.isPending}>
                  {checkout.isPending && checkout.variables === p.code ? <Loader2 className="animate-spin" /> : null}
                  Choose {p.name}
                </Button>
              ) : null
            }
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Billing history</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {!invoices.data?.length ? (
              <p className="px-6 pb-6 text-sm text-muted-foreground">No invoices yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">Date</TableHead>
                    <TableHead>Amount</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="pr-6 text-right">Invoice</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invoices.data.map((inv) => (
                    <TableRow key={inv.id}>
                      <TableCell className="pl-6">{formatDateTime(inv.issued_at)}</TableCell>
                      <TableCell className="tabular-nums">{formatMoney(inv.amount_minor, inv.currency)}</TableCell>
                      <TableCell>
                        <Badge variant={inv.status === "paid" ? "secondary" : "destructive"}>{inv.status}</Badge>
                      </TableCell>
                      <TableCell className="pr-6 text-right">
                        {inv.hosted_url ? (
                          <a href={inv.hosted_url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">
                            View
                          </a>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function PlanGrid({
  plans,
  currency,
  currentCode,
  action,
}: {
  plans: Plan[];
  currency: "INR" | "USD";
  currentCode: string | null;
  action: (plan: Plan) => React.ReactNode;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {plans.map((p) => (
        <Card key={p.code} className={cn("flex flex-col p-5", p.code === "growth" && "border-primary shadow-md")}>
          <p className="flex items-center justify-between font-semibold">
            {p.name}
            {p.code === "growth" ? <Badge>Most popular</Badge> : null}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>
          <p className="mt-4 text-3xl font-semibold tabular-nums">
            {formatMoney(p.prices[currency], currency)}
            <span className="text-sm font-normal text-muted-foreground"> / month</span>
          </p>
          <ul className="mt-4 grid flex-1 gap-2 text-sm">
            {p.features.map((f) => (
              <li key={f} className="flex gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-primary" /> {f}
              </li>
            ))}
          </ul>
          <div className="mt-5">{currentCode === p.code ? <Button className="w-full" variant="outline" disabled>Current plan</Button> : action(p)}</div>
        </Card>
      ))}
    </div>
  );
}
