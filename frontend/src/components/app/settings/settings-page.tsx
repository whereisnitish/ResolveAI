"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { PageHeader } from "@/components/app/page-header";
import { InboxSettingsPanel } from "@/components/app/settings/inbox-settings";
import { WidgetSettingsPanel } from "@/components/app/settings/widget-settings";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { queryKeys, useOrganization, useWorkspaceDetail } from "@/lib/queries";
import type { Organization, Workspace } from "@/lib/types";
import {
  changePasswordSchema,
  nameSchema,
  PASSWORD_MIN_LENGTH,
  profileSchema,
  type ChangePasswordValues,
  type NameValues,
  type ProfileValues,
} from "@/lib/validation";

const TABS = ["profile", "security", "organization", "workspace", "inbox", "widget"] as const;
type Tab = (typeof TABS)[number];

const TIMEZONES: string[] =
  typeof Intl.supportedValuesOf === "function" ? ["UTC", ...Intl.supportedValuesOf("timeZone")] : ["UTC"];

export function SettingsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = searchParams.get("tab");
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : "profile";

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" description="Manage your account, organization and workspace." />
      <Tabs value={tab} onValueChange={(value) => router.replace(`${pathname}?tab=${value}`, { scroll: false })}>
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="organization">Organization</TabsTrigger>
          <TabsTrigger value="workspace">Workspace</TabsTrigger>
          <TabsTrigger value="inbox">Inbox</TabsTrigger>
          <TabsTrigger value="widget">Widget</TabsTrigger>
        </TabsList>
        <TabsContent value="profile" className="mt-4">
          <ProfileSettings />
        </TabsContent>
        <TabsContent value="security" className="mt-4">
          <PasswordSettings />
        </TabsContent>
        <TabsContent value="organization" className="mt-4">
          <OrganizationSettings />
        </TabsContent>
        <TabsContent value="workspace" className="mt-4 grid gap-6">
          <WorkspaceSettings />
          <CreateWorkspace />
        </TabsContent>
        <TabsContent value="inbox" className="mt-4">
          <InboxSettingsPanel />
        </TabsContent>
        <TabsContent value="widget" className="mt-4">
          <WidgetSettingsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SettingsCard({
  title,
  description,
  children,
  footer,
  onSubmit,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  onSubmit?: (e: React.FormEvent) => void;
}) {
  return (
    <Card>
      <form onSubmit={onSubmit} noValidate>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent className="grid gap-4 pt-4">{children}</CardContent>
        {footer ? <CardFooter className="mt-4 justify-end border-t pt-4">{footer}</CardFooter> : null}
      </form>
    </Card>
  );
}

function SaveButton({ pending, disabled, label = "Save changes" }: { pending: boolean; disabled?: boolean; label?: string }) {
  return (
    <Button type="submit" disabled={pending || disabled}>
      {pending ? <Loader2 className="animate-spin" /> : null}
      {label}
    </Button>
  );
}

function ProfileSettings() {
  const { me } = useApp();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<ProfileValues>({ resolver: zodResolver(profileSchema), values: { full_name: me.user.full_name } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.patch("auth/me", values);
      await queryClient.invalidateQueries({ queryKey: queryKeys.me });
      toast.success("Profile updated");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["full_name"]));
    }
  });

  return (
    <SettingsCard
      title="Profile"
      description="How you appear to teammates and customers."
      onSubmit={onSubmit}
      footer={<SaveButton pending={isSubmitting} disabled={!isDirty} />}
    >
      <FormError message={formError} />
      <FormField id="full_name" label="Full name" error={errors.full_name?.message} {...register("full_name")} />
      <FormField id="email" label="Email" value={me.user.email} readOnly disabled hint="Contact support to change your email." />
    </SettingsCard>
  );
}

function PasswordSettings() {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: "", new_password: "", confirm_password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("auth/password/change", {
        current_password: values.current_password,
        new_password: values.new_password,
      });
      reset();
      toast.success("Password updated. Other sessions have been signed out.");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["current_password", "new_password"]));
    }
  });

  return (
    <SettingsCard
      title="Password"
      description="Changing your password signs you out everywhere else."
      onSubmit={onSubmit}
      footer={<SaveButton pending={isSubmitting} label="Update password" />}
    >
      <FormError message={formError} />
      <FormField
        id="current_password"
        label="Current password"
        type="password"
        autoComplete="current-password"
        error={errors.current_password?.message}
        {...register("current_password")}
      />
      <FormField
        id="new_password"
        label="New password"
        type="password"
        autoComplete="new-password"
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
    </SettingsCard>
  );
}

function OrganizationSettings() {
  const { organization, canOrg } = useApp();
  const org = useOrganization(organization?.id);
  if (org.isPending) return <Skeleton className="h-56 w-full rounded-xl" />;
  if (org.isError) return <p className="text-sm text-destructive">{org.error.message}</p>;
  return <OrganizationForm org={org.data} editable={canOrg("org.update")} />;
}

function OrganizationForm({ org, editable }: { org: Organization; editable: boolean }) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const [country, setCountry] = useState(org.country);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<NameValues>({ resolver: zodResolver(nameSchema), values: { name: org.name } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.patch(`organizations/${org.id}`, { name: values.name, country });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.organization(org.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.me }),
      ]);
      toast.success("Organization updated");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["name"]));
    }
  });

  return (
    <SettingsCard
      title="Organization"
      description={editable ? "Billing and ownership boundary for your workspaces." : "Only owners and admins can edit these settings."}
      onSubmit={onSubmit}
      footer={editable ? <SaveButton pending={isSubmitting} disabled={!isDirty && country === org.country} /> : null}
    >
      <FormError message={formError} />
      <FormField id="org-name" label="Name" disabled={!editable} error={errors.name?.message} {...register("name")} />
      <FormField
        id="org-country"
        label="Country (ISO code)"
        maxLength={2}
        placeholder="e.g. IN, US"
        disabled={!editable}
        value={country}
        onChange={(e) => setCountry(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))}
        hint="Used for tax and payment-provider selection."
      />
      <FormField id="org-slug" label="Slug" value={org.slug} readOnly disabled />
    </SettingsCard>
  );
}

function WorkspaceSettings() {
  const { workspace, canWorkspace } = useApp();
  const detail = useWorkspaceDetail(workspace?.id);
  if (detail.isPending) return <Skeleton className="h-56 w-full rounded-xl" />;
  if (detail.isError) return <p className="text-sm text-destructive">{detail.error.message}</p>;
  return <WorkspaceForm ws={detail.data} editable={canWorkspace("workspace.update")} />;
}

function WorkspaceForm({ ws, editable }: { ws: Workspace; editable: boolean }) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const [timezone, setTimezone] = useState(ws.timezone);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<NameValues>({ resolver: zodResolver(nameSchema), values: { name: ws.name } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.patch(`workspaces/${ws.id}`, { name: values.name, timezone });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.workspace(ws.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.me }),
      ]);
      toast.success("Workspace updated");
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["name"]));
    }
  });

  return (
    <SettingsCard
      title="Workspace"
      description={editable ? "Settings for the current workspace." : "Only workspace admins can edit these settings."}
      onSubmit={onSubmit}
      footer={editable ? <SaveButton pending={isSubmitting} disabled={!isDirty && timezone === ws.timezone} /> : null}
    >
      <FormError message={formError} />
      <FormField id="ws-name" label="Name" disabled={!editable} error={errors.name?.message} {...register("name")} />
      <div className="grid gap-1.5">
        <Label htmlFor="ws-timezone">Timezone</Label>
        <select
          id="ws-timezone"
          className="h-9 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
          value={timezone}
          disabled={!editable}
          onChange={(e) => setTimezone(e.target.value)}
        >
          {(TIMEZONES.includes(ws.timezone) ? TIMEZONES : [ws.timezone, ...TIMEZONES]).map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">Used for business hours and reporting.</p>
      </div>
      <FormField id="ws-public-id" label="Widget workspace ID" value={ws.public_id} readOnly className="font-mono" />
    </SettingsCard>
  );
}

function CreateWorkspace() {
  const { organization, canOrg, setWorkspaceId } = useApp();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<NameValues>({ resolver: zodResolver(nameSchema), defaultValues: { name: "" } });

  if (!organization || !canOrg("org.workspaces.create")) return null;

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const ws = await api.post<Workspace>(`organizations/${organization.id}/workspaces`, {
        name: values.name,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.me });
      setWorkspaceId(ws.id);
      reset();
      toast.success(`Workspace “${ws.name}” created`);
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["name"]));
    }
  });

  return (
    <SettingsCard
      title="New workspace"
      description={`Create a separate, isolated support environment in ${organization.name} — e.g. per brand or region.`}
      onSubmit={onSubmit}
      footer={<SaveButton pending={isSubmitting} label="Create workspace" />}
    >
      <FormError message={formError} />
      <FormField id="new-ws-name" label="Workspace name" placeholder="e.g. EU Support" error={errors.name?.message} {...register("name")} />
    </SettingsCard>
  );
}
