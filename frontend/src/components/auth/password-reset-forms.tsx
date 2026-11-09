"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/auth/auth-card";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import {
  forgotPasswordSchema,
  PASSWORD_MIN_LENGTH,
  resetPasswordSchema,
  type ForgotPasswordValues,
  type ResetPasswordValues,
} from "@/lib/validation";

const backToLogin = (
  <Link href="/login" className="font-medium text-primary hover:underline">
    Back to sign in
  </Link>
);

export function ForgotPasswordForm() {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordValues>({ resolver: zodResolver(forgotPasswordSchema), defaultValues: { email: "" } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("auth/password-reset", values);
      setSentTo(values.email);
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["email"]));
    }
  });

  if (sentTo) {
    return (
      <AuthCard title="Check your email" footer={backToLogin}>
        <div className="flex gap-3 text-sm text-muted-foreground">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-primary" />
          <p>
            If an account exists for <span className="font-medium text-foreground">{sentTo}</span>, we&apos;ve sent a
            link to reset your password. The link expires in 1 hour.
          </p>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      description="Enter your email and we'll send you a reset link."
      footer={backToLogin}
    >
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <FormField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          autoFocus
          error={errors.email?.message}
          {...register("email")}
        />
        <Button type="submit" size="lg" className="h-9 w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          Send reset link
        </Button>
      </form>
    </AuthCard>
  );
}

export function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const uid = searchParams.get("uid") ?? "";
  const token = searchParams.get("token") ?? "";
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: "", confirm_password: "" },
  });

  if (!uid || !token) {
    return (
      <AuthCard
        title="Invalid reset link"
        description="This link is incomplete. Request a new password reset email."
        footer={backToLogin}
      >
        <Button render={<Link href="/forgot-password" />} className="h-9 w-full">
          Request a new link
        </Button>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard title="Password updated">
        <div className="grid gap-4">
          <p className="flex gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-5 shrink-0 text-emerald-600" />
            Your password has been reset. Other sessions have been signed out.
          </p>
          <Button render={<Link href="/login" />} className="h-9 w-full">
            Sign in
          </Button>
        </div>
      </AuthCard>
    );
  }

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("auth/password-reset/confirm", { uid, token, new_password: values.new_password });
      setDone(true);
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["new_password"]));
    }
  });

  return (
    <AuthCard title="Choose a new password" footer={backToLogin}>
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <FormField
          id="new_password"
          label="New password"
          type="password"
          autoComplete="new-password"
          autoFocus
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          error={errors.new_password?.message}
          {...register("new_password")}
        />
        <FormField
          id="confirm_password"
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          error={errors.confirm_password?.message}
          {...register("confirm_password")}
        />
        <Button type="submit" size="lg" className="h-9 w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          Update password
        </Button>
      </form>
    </AuthCard>
  );
}
