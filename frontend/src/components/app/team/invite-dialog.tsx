"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { useApp } from "@/components/app/app-context";
import { FormError, FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { applyApiErrors } from "@/lib/forms";
import { queryKeys } from "@/lib/queries";
import { ORG_ROLE_LABELS, WORKSPACE_ROLE_LABELS, type OrganizationRole } from "@/lib/types";
import { inviteSchema, type InviteValues } from "@/lib/validation";

/** Mirrors backend ASSIGNABLE_ORG_ROLES (the backend remains the authority). */
export function assignableOrgRoles(actorRole: OrganizationRole | undefined): OrganizationRole[] {
  if (actorRole === "owner") return ["owner", "admin", "member", "billing_admin"];
  if (actorRole === "admin") return ["admin", "member", "billing_admin"];
  return [];
}

const NO_WORKSPACE_ACCESS = "";

export function InviteDialog() {
  const { organization, workspace } = useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const roles = assignableOrgRoles(organization?.role);

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "member", workspace_role: "agent" },
  });

  const onSubmit = handleSubmit(async (values) => {
    if (!organization) return;
    setFormError(null);
    try {
      await api.post(`organizations/${organization.id}/invitations`, {
        email: values.email,
        role: values.role,
        ...(values.workspace_role && workspace
          ? { workspace: workspace.id, workspace_role: values.workspace_role }
          : {}),
      });
      toast.success(`Invitation sent to ${values.email}`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.orgInvitations(organization.id) });
      reset();
      setOpen(false);
    } catch (error) {
      setFormError(applyApiErrors(error, setError, ["email", "role", "workspace_role"]));
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setFormError(null);
      }}
    >
      <DialogTrigger render={<Button />}>
        <UserPlus /> Invite teammate
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite a teammate</DialogTitle>
          <DialogDescription>They&apos;ll get an email with a link that expires in 7 days.</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4" noValidate id="invite-form">
          <FormError message={formError} />
          <FormField
            id="invite-email"
            label="Email address"
            type="email"
            autoComplete="off"
            error={errors.email?.message}
            {...register("email")}
          />
          <div className="grid gap-1.5">
            <Label>Organization role</Label>
            <Controller
              control={control}
              name="role"
              render={({ field }) => (
                <Select
                  items={Object.fromEntries(roles.map((r) => [r, ORG_ROLE_LABELS[r]]))}
                  value={field.value}
                  onValueChange={(value) => value && field.onChange(value)}
                >
                  <SelectTrigger className="h-9 w-full" aria-label="Organization role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((role) => (
                      <SelectItem key={role} value={role}>
                        {ORG_ROLE_LABELS[role]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <p className="text-xs text-muted-foreground">Owners and Admins can access every workspace.</p>
          </div>
          {workspace ? (
            <div className="grid gap-1.5">
              <Label>Access to {workspace.name}</Label>
              <Controller
                control={control}
                name="workspace_role"
                render={({ field }) => (
                  <Select
                    items={{ [NO_WORKSPACE_ACCESS]: "No direct access", ...WORKSPACE_ROLE_LABELS }}
                    value={field.value}
                    onValueChange={(value) => field.onChange(value ?? NO_WORKSPACE_ACCESS)}
                  >
                    <SelectTrigger className="h-9 w-full" aria-label="Workspace role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_WORKSPACE_ACCESS}>No direct access</SelectItem>
                      {Object.entries(WORKSPACE_ROLE_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          ) : null}
        </form>
        <DialogFooter>
          <Button type="submit" form="invite-form" disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="animate-spin" /> : null}
            Send invitation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
