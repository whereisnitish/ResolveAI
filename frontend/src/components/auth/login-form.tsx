"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/auth/auth-card";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { queryKeys } from "@/lib/queries";
import type { Me } from "@/lib/types";
import { loginSchema, safeNextPath, type LoginValues } from "@/lib/validation";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const next = safeNextPath(searchParams.get("next"));

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await api.post<Me>("auth/login", values);
      queryClient.setQueryData(queryKeys.me, me);
      router.replace(next);
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["email", "password"]));
    }
  });

  return (
    <AuthCard
      title="Welcome back"
      description="Sign in to your ResolveAI workspace."
      footer={
        <span>
          New to ResolveAI?{" "}
          <Link href="/signup" className="font-medium text-primary hover:underline">
            Create an account
          </Link>
        </span>
      }
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
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          labelAction={
            <Link href="/forgot-password" className="text-xs text-muted-foreground hover:text-foreground">
              Forgot password?
            </Link>
          }
          {...register("password")}
        />
        <Button type="submit" size="lg" className="mt-1 h-9 w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          Sign in
        </Button>
      </form>
    </AuthCard>
  );
}
