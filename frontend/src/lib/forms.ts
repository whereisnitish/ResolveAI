import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "@/lib/api";

/**
 * Map a backend ApiError onto react-hook-form fields. Returns a message for
 * a form-level banner when the error isn't attributable to a known field.
 */
export function applyApiErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  knownFields: readonly Path<T>[],
): string | null {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  const fieldErrors = error.fieldErrors;
  let unmatched: string | null = null;
  for (const [field, message] of Object.entries(fieldErrors)) {
    if ((knownFields as readonly string[]).includes(field)) {
      setError(field as Path<T>, { type: "server", message });
    } else {
      unmatched ??= message;
    }
  }
  if (Object.keys(fieldErrors).length === 0) return error.message;
  return unmatched;
}
