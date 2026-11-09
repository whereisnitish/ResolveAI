"use client";

import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";

type ErrorStateProps = {
  title: string;
  description: string;
  digest?: string;
  onRetry?: () => void;
  homeHref?: string;
};

/** Full-area error / not-found message. Never renders raw error text (it may leak internals). */
export function ErrorState({ title, description, digest, onRetry, homeHref = "/" }: ErrorStateProps) {
  return (
    <div role="alert" className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="max-w-md text-sm text-muted-foreground">{description}</p>
        {digest ? <p className="text-xs text-muted-foreground">Reference: {digest}</p> : null}
      </div>
      <div className="flex gap-2">
        {onRetry ? <Button onClick={onRetry}>Try again</Button> : null}
        <Link href={homeHref} className={buttonVariants({ variant: onRetry ? "outline" : "default" })}>
          Go home
        </Link>
      </div>
    </div>
  );
}
