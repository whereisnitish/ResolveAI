import { z } from "zod";

// Client-side checks are for fast feedback only; the backend re-validates
// everything (including Django's common-password and similarity checks).
export const PASSWORD_MIN_LENGTH = 10;

const email = z.string().trim().min(1, "Email is required").email("Enter a valid email address");
const password = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `Use at least ${PASSWORD_MIN_LENGTH} characters`)
  .max(128, "Use at most 128 characters")
  .refine((value) => !/^\d+$/.test(value), "Password can't be entirely numeric");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Password is required"),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const signupSchema = z.object({
  full_name: z.string().trim().min(1, "Your name is required").max(150),
  email,
  password,
  organization_name: z.string().trim().min(1, "Company name is required").max(120),
});
export type SignupValues = z.infer<typeof signupSchema>;

export const inviteSignupSchema = signupSchema.omit({ organization_name: true });
export type InviteSignupValues = z.infer<typeof inviteSignupSchema>;

export const forgotPasswordSchema = z.object({ email });
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>;

export const resetPasswordSchema = z
  .object({ new_password: password, confirm_password: z.string() })
  .refine((v) => v.new_password === v.confirm_password, {
    message: "Passwords don't match",
    path: ["confirm_password"],
  });
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: password,
    confirm_password: z.string(),
  })
  .refine((v) => v.new_password === v.confirm_password, {
    message: "Passwords don't match",
    path: ["confirm_password"],
  });
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>;

export const profileSchema = z.object({ full_name: z.string().trim().min(1, "Name is required").max(150) });
export type ProfileValues = z.infer<typeof profileSchema>;

export const nameSchema = z.object({ name: z.string().trim().min(1, "Name is required").max(120) });
export type NameValues = z.infer<typeof nameSchema>;

export const inviteSchema = z.object({
  email,
  role: z.enum(["owner", "admin", "member", "billing_admin"]),
  workspace_role: z.enum(["", "admin", "supervisor", "agent", "viewer"]),
});
export type InviteValues = z.infer<typeof inviteSchema>;

/** Only allow same-site relative redirects (prevents open-redirects via ?next=). */
export function safeNextPath(next: string | null | undefined, fallback = "/app"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}
