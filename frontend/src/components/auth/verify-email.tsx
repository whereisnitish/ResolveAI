"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/queries";

export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const queryClient = useQueryClient();
  const started = useRef(false);
  const verify = useMutation({
    mutationFn: (t: string) => api.post("auth/verify-email", { token: t }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me }),
  });

  useEffect(() => {
    if (token && !started.current) {
      started.current = true;
      verify.mutate(token);
    }
  }, [token, verify]);

  if (!token || verify.isError) {
    const message =
      verify.error instanceof ApiError ? verify.error.message : "This verification link is invalid or incomplete.";
    return (
      <AuthCard title="We couldn't verify your email">
        <div className="grid gap-4">
          <p className="flex gap-2 text-sm text-muted-foreground">
            <XCircle className="size-5 shrink-0 text-destructive" />
            {message} Sign in and request a new link from your dashboard.
          </p>
          <Button render={<Link href="/app" />} className="h-9 w-full">
            Go to dashboard
          </Button>
        </div>
      </AuthCard>
    );
  }

  if (verify.isSuccess) {
    return (
      <AuthCard title="Email verified">
        <div className="grid gap-4">
          <p className="flex gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-5 shrink-0 text-emerald-600" />
            Thanks for confirming your email address.
          </p>
          <Button render={<Link href="/app" />} className="h-9 w-full">
            Continue to ResolveAI
          </Button>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Verifying your email…">
      <div className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
        <Loader2 className="size-4 animate-spin" /> One moment.
      </div>
    </AuthCard>
  );
}
