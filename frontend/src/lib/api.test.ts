import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("normalizes paths to Django's trailing-slash URLs and drops empty query params", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await api.get("workspaces", { organization: "abc", search: "" });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/workspaces/?organization=abc", expect.any(Object));
  });

  it("sends the CSRF cookie value on unsafe requests", async () => {
    document.cookie = "resolveai_csrftoken=tok123; path=/";
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    await api.post("auth/login", { email: "a@b.co" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-CSRFToken"]).toBe("tok123");
    expect(init.credentials).toBe("same-origin");
  });

  it("fetches a CSRF token first when the cookie is missing", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "fresh" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await api.post("auth/logout");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/csrf/");
    expect(fetchMock.mock.calls[1][1].headers["X-CSRFToken"]).toBe("fresh");
  });

  it("does not send a CSRF header on GET", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    await api.get("auth/me");
    expect(fetchMock.mock.calls[0][1].headers["X-CSRFToken"]).toBeUndefined();
  });

  it("parses the backend error envelope into ApiError with field errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, {
        error: {
          code: "validation_error",
          message: "Invalid input.",
          details: { email: ["Enter a valid email address."] },
          request_id: "req-1",
        },
      }),
    );
    const error = await api.get("auth/me").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(400);
    expect(apiError.code).toBe("validation_error");
    expect(apiError.requestId).toBe("req-1");
    expect(apiError.fieldErrors).toEqual({ email: "Enter a valid email address." });
  });

  it("reports network failures as ApiError(network_error)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = (await api.get("auth/me").catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("network_error");
    expect(error.status).toBe(0);
  });
});
