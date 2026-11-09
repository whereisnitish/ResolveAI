import Link from "next/link";

import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2.4}>
        <path d="M5 12.5c0-4 3-7 7-7s7 3 7 7c0 3.6-2.6 6.4-6 6.9L9 21v-2.4c-2.4-1-4-3.4-4-6.1Z" />
        <path d="m9.5 12.5 1.8 1.8 3.4-3.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function Logo({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <LogoMark />
      <span>ResolveAI</span>
    </Link>
  );
}
