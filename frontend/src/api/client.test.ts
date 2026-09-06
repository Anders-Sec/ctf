import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

function mockResponse(status: number, body: unknown, requestId = "req-1") {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(body === undefined ? null : JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json", "X-Request-ID": requestId },
        }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("prefixes paths with /api", async () => {
    mockResponse(200, { ok: true });

    await api.get("/version");

    expect(fetch).toHaveBeenCalledWith("/api/version", expect.anything());
  });

  it("sends cookies so httpOnly sessions work", async () => {
    mockResponse(200, { ok: true });

    await api.get("/version");

    expect(fetch).toHaveBeenCalledWith(
      "/api/version",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("unwraps the error envelope into a coded ApiError", async () => {
    mockResponse(409, {
      error: { code: "team_full", message: "That party is full.", details: { max: 8 } },
    });

    const error = await api.post("/teams/abc/join").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe("team_full");
    expect(apiError.status).toBe(409);
    expect(apiError.details).toEqual({ max: 8 });
    // The request id makes a player's report traceable in the backend logs.
    expect(apiError.requestId).toBe("req-1");
  });

  it("falls back to a coded error when the body is not the envelope", async () => {
    // An ingress or proxy failure will not be JSON from our app.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>502 Bad Gateway</html>", { status: 502 })),
    );

    const error = (await api.get("/version").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("unexpected_response");
  });

  it("serialises request bodies as JSON", async () => {
    mockResponse(200, { ok: true });

    await api.post("/teams", { name: "Mimics" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/teams",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Mimics" }),
      }),
    );
  });
});
