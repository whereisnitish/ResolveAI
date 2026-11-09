import { ArrowRight, Bot, BookOpen, Globe2, Inbox, ShieldCheck, Workflow } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/brand";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: Inbox,
    title: "Shared inbox",
    body: "Every customer conversation in one place, with assignment, priorities, internal notes and real-time updates.",
  },
  {
    icon: Bot,
    title: "AI agents",
    body: "Deploy AI agents that answer with your own knowledge and hand off to humans the moment they're unsure.",
  },
  {
    icon: BookOpen,
    title: "Knowledge hub",
    body: "Train agents on PDFs, help-center articles, websites and FAQs. Keep answers grounded and up to date.",
  },
  {
    icon: Workflow,
    title: "Automation",
    body: "Route, tag and escalate conversations automatically with safe, structured workflows.",
  },
  {
    icon: ShieldCheck,
    title: "Built for trust",
    body: "Strict workspace isolation, role-based access and audit logs for every sensitive action.",
  },
  {
    icon: Globe2,
    title: "India & global",
    body: "Billing in INR via Razorpay or international currencies via Stripe — from day one.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav className="flex items-center gap-2">
            <Button variant="ghost" render={<Link href="/pricing" />}>
              Pricing
            </Button>
            <Button variant="ghost" render={<Link href="/login" />}>
              Sign in
            </Button>
            <Button render={<Link href="/signup" />}>Get started</Button>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[28rem] max-w-4xl rounded-full bg-primary/15 blur-3xl"
          />
          <div className="relative mx-auto max-w-4xl px-4 pt-20 pb-16 text-center sm:px-6 sm:pt-28">
            <p className="mx-auto mb-5 inline-flex items-center rounded-full border bg-background px-3 py-1 text-xs font-medium text-muted-foreground">
              Your AI workforce for customer support
            </p>
            <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-6xl">
              Resolve customer questions instantly — with AI and your team, together.
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-pretty text-muted-foreground">
              ResolveAI combines a modern shared inbox with AI agents trained on your knowledge, so customers get
              accurate answers in seconds and your team focuses on the conversations that need a human.
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button size="lg" className="h-11 px-5 text-base" render={<Link href="/signup" />}>
                Start free <ArrowRight />
              </Button>
              <Button size="lg" variant="outline" className="h-11 px-5 text-base" render={<Link href="/login" />}>
                Sign in
              </Button>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
          <div className="grid gap-px overflow-hidden rounded-2xl border bg-border sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="bg-card p-6">
                <div className="mb-4 inline-flex rounded-lg bg-primary/10 p-2 text-primary">
                  <Icon className="size-5" />
                </div>
                <h2 className="font-semibold">{title}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:px-6">
          <span>© 2026 ResolveAI</span>
          <span>Made for support teams in India and around the world.</span>
        </div>
      </footer>
    </div>
  );
}
