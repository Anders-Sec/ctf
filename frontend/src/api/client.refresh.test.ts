import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "ctf_csrf=; Max-Age=0; path=/";
});

describe("session refresh interceptor", () => {
  it("rotates once and replays the original request on a 401", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        calls.push(path);
        if (path.endsWith("/auth/refresh")) {
          return new Response(JSON.stringify({ message: "ok" }), { status: 200 });
        }
        // Unauthorised first, fine after the refresh.
        const isFirstAttempt = calls.filter((c) => c.endsWith("/teams")).length === 1;
        return new Response(JSON.stringify(isFirstAttempt ? {} : [{ id: "t1" }]), {
          status: isFirstAttempt ? 401 : 200,
        });
      }),
    );

    const result = await api.get<unknown[]>("/teams");

    expect(calls).toEqual(["/api/teams", "/api/auth/refresh", "/api/teams"]);
    expect(result).toEqual([{ id: "t1" }]);
  });

  it("gives up rather than looping when the refresh itself fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: { code: "session_expired", message: "gone" } }),
            { status: 401 },
          ),
      ),
    );

    const error = (await api.get("/teams").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    // Original request, refresh attempt, and nothing more.
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("deduplicates concurrent refreshes", async () => {
    // Rotation invalidates the previous refresh token, so a second concurrent
    // rotation would look like token reuse and revoke the whole session.
    let refreshes = 0;
    const seen = new Set<string>();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.endsWith("/auth/refresh")) {
          refreshes += 1;
          return new Response(JSON.stringify({ message: "ok" }), { status: 200 });
        }
        if (!seen.has(path)) {
          seen.add(path);
          return new Response("{}", { status: 401 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    await Promise.all([api.get("/a"), api.get("/b"), api.get("/c")]);

    expect(refreshes).toBe(1);
  });

  it("attaches the CSRF header to state-changing requests", async () => {
    document.cookie = "ctf_csrf=token-abc; path=/";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })),
    );

    await api.post("/teams", { name: "Mimics" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/teams",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "token-abc" }),
      }),
    );
  });

  it("does not attach it to reads", async () => {
    document.cookie = "ctf_csrf=token-abc; path=/";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })),
    );

    await api.get("/teams");

    const firstCall = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(firstCall).toBeDefined();
    expect((firstCall![1] as RequestInit).headers).not.toHaveProperty("X-CSRF-Token");
  });
});
