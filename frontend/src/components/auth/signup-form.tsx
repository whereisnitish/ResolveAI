"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/auth/auth-card";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { queryKeys } from "@/lib/queries";
import type { Me } from "@/lib/types";
import { PASSWORD_MIN_LENGTH, signupSchema, type SignupValues } from "@/lib/validation";

export function SignupForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: { full_name: "", email: "", password: "", organization_name: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await api.post<Me>("auth/register", values);
      queryClient.setQueryData(queryKeys.me, me);
      router.replace("/app");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["full_name", "email", "password", "organization_name"]));
    }
  });

  return (
    <AuthCard
      title="Create your account"
      description="Start with a shared inbox for your team. No credit card required."
      footer={
        <span>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </span>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <FormField
          id="full_name"
          label="Your name"
          autoComplete="name"
          autoFocus
          error={errors.full_name?.message}
          {...register("full_name")}
        />
        <FormField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <FormField
          id="organization_name"
          label="Company name"
          autoComplete="organization"
          error={errors.organization_name?.message}
          {...register("organization_name")}
        />
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          error={errors.password?.message}
          {...register("password")}
        />
        <Button type="submit" size="lg" className="mt-1 h-9 w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}
