"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Users, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard, AuthCardSkeleton } from "@/components/auth/auth-card";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { queryKeys, useMe } from "@/lib/queries";
import { ORG_ROLE_LABELS, type InvitationPreview, type Me } from "@/lib/types";
import { inviteSignupSchema, PASSWORD_MIN_LENGTH, type InviteSignupValues } from "@/lib/validation";

export function AcceptInvitation() {
  const token = useSearchParams().get("token") ?? "";
  const preview = useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: () => api.post<InvitationPreview>("invitations/preview", { token }),
    enabled: Boolean(token),
  });
  const me = useMe();

  if (!token || preview.isError) {
    return (
      <AuthCard title="Invitation unavailable">
        <p className="flex gap-2 text-sm text-muted-foreground">
          <XCircle className="size-5 shrink-0 text-destructive" />
          This invitation is invalid, has expired, or was revoked. Ask your team admin to send a new one.
        </p>
      </AuthCard>
    );
  }
  if (preview.isPending || me.isPending) return <AuthCardSkeleton />;

  const invitation = preview.data;
  const summary = (
    <div className="mb-5 flex gap-3 rounded-lg border bg-muted/50 p-3 text-sm">
      <Users className="mt-0.5 size-5 shrink-0 text-primary" />
      <p>
        {invitation.invited_by_name || "A teammate"} invited <strong>{invitation.email}</strong> to join{" "}
        <strong>{invitation.organization_name}</strong> as {ORG_ROLE_LABELS[invitation.role]}.
      </p>
    </div>
  );

  if (me.data) {
    if (me.data.user.email !== invitation.email) {
      return (
        <AuthCard title={`Join ${invitation.organization_name}`}>
          {summary}
          <p className="text-sm text-muted-foreground">
            You&apos;re signed in as <strong>{me.data.user.email}</strong>. Sign out and sign in as{" "}
            <strong>{invitation.email}</strong> to accept this invitation.
          </p>
        </AuthCard>
      );
    }
    return <AcceptAsCurrentUser token={token} summary={summary} orgName={invitation.organization_name} />;
  }

  const next = `/invite?token=${encodeURIComponent(token)}`;
  if (invitation.account_exists) {
    return (
      <AuthCard title={`Join ${invitation.organization_name}`}>
        {summary}
        <Button render={<Link href={`/login?next=${encodeURIComponent(next)}`} />} className="h-9 w-full">
          Sign in to accept
        </Button>
      </AuthCard>
    );
  }
  return <InviteSignup token={token} email={invitation.email} summary={summary} orgName={invitation.organization_name} />;
}

function AcceptAsCurrentUser({ token, summary, orgName }: { token: string; summary: React.ReactNode; orgName: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const accept = useMutation({
    mutationFn: () => api.post<Me>("invitations/accept", { token }),
    onSuccess: (me) => {
      queryClient.setQueryData(queryKeys.me, me);
      router.replace("/app");
    },
  });
  return (
    <AuthCard title={`Join ${orgName}`}>
      {summary}
      <FormError message={accept.error instanceof ApiError ? accept.error.message : null} />
      <Button className="mt-3 h-9 w-full" onClick={() => accept.mutate()} disabled={accept.isPending}>
        {accept.isPending ? <Loader2 className="animate-spin" /> : null}
        Accept invitation
      </Button>
    </AuthCard>
  );
}

function InviteSignup({
  token,
  email,
  summary,
  orgName,
}: {
  token: string;
  email: string;
  summary: React.ReactNode;
  orgName: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<InviteSignupValues>({
    resolver: zodResolver(inviteSignupSchema),
    defaultValues: { full_name: "", email, password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await api.post<Me>("auth/register", { ...values, invitation_token: token });
      queryClient.setQueryData(queryKeys.me, me);
      router.replace("/app");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["full_name", "password"]));
    }
  });

  return (
    <AuthCard title={`Join ${orgName}`} description="Create your account to accept the invitation.">
      {summary}
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <FormField id="email" label="Work email" type="email" readOnly {...register("email")} />
        <FormField
          id="full_name"
          label="Your name"
          autoComplete="name"
          autoFocus
          error={errors.full_name?.message}
          {...register("full_name")}
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
        <Button type="submit" size="lg" className="h-9 w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          Create account &amp; join
        </Button>
      </form>
    </AuthCard>
  );
}
