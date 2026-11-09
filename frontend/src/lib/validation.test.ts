import { describe, expect, it } from "vitest";

import { changePasswordSchema, loginSchema, safeNextPath, signupSchema } from "@/lib/validation";

describe("safeNextPath (open-redirect protection)", () => {
  it.each([
    ["/app/team", "/app/team"],
    ["/app?tab=x", "/app?tab=x"],
  ])("allows same-site path %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([null, undefined, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"])(
    "rejects %s",
    (input) => {
      expect(safeNextPath(input)).toBe("/app");
    },
  );
});

describe("signupSchema", () => {
  const valid = {
    full_name: "Asha",
    email: "asha@example.com",
    password: "a-strong-passphrase",
    organization_name: "Acme",
  };

  it("accepts valid input", () => {
    expect(signupSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects short and all-numeric passwords", () => {
    expect(signupSchema.safeParse({ ...valid, password: "short" }).success).toBe(false);
    expect(signupSchema.safeParse({ ...valid, password: "12345678901234" }).success).toBe(false);
  });

  it("requires a company name and a valid email", () => {
    expect(signupSchema.safeParse({ ...valid, organization_name: "  " }).success).toBe(false);
    expect(signupSchema.safeParse({ ...valid, email: "not-an-email" }).success).toBe(false);
  });
});

describe("loginSchema", () => {
  it("requires both fields", () => {
    const result = loginSchema.safeParse({ email: "", password: "" });
    expect(result.success).toBe(false);
  });
});

describe("changePasswordSchema", () => {
  it("requires matching confirmation", () => {
    const result = changePasswordSchema.safeParse({
      current_password: "old",
      new_password: "a-strong-passphrase",
      confirm_password: "different-passphrase",
    });
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.issues[0].path).toEqual(["confirm_password"]);
  });
});
