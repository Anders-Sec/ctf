import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import StatusPage from "./StatusPage";

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function mockFetch(handler: (path: string) => { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const { status, body } = handler(String(input));
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", "X-Request-ID": "test-request" },
      });
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StatusPage", () => {
  it("renders version data fetched from the API", async () => {
    mockFetch((path) =>
      path.endsWith("/version")
        ? { status: 200, body: { version: "1.2.3", environment: "local" } }
        : { status: 200, body: { status: "ok", postgres: "ok", redis: "ok" } },
    );

    renderWithQueryClient(<StatusPage />);

    expect(await screen.findByTestId("version")).toHaveTextContent("1.2.3");
    expect(screen.getByTestId("environment")).toHaveTextContent("local");
  });

  it("shows each dependency's readiness separately", async () => {
    mockFetch((path) =>
      path.endsWith("/version")
        ? { status: 200, body: { version: "dev", environment: "local" } }
        : { status: 503, body: { status: "degraded", postgres: "ok", redis: "error" } },
    );

    renderWithQueryClient(<StatusPage />);

    // 503 is an error response, so the section reports the failure rather than
    // silently rendering a half-filled table.
    expect(await screen.findByTestId("error")).toBeInTheDocument();
  });

  it("reports the API error code rather than its prose message", async () => {
    mockFetch(() => ({
      status: 500,
      body: { error: { code: "internal_error", message: "Something went wrong." } },
    }));

    renderWithQueryClient(<StatusPage />);

    const errors = await screen.findAllByTestId("error");
    expect(errors[0]).toHaveTextContent("internal_error");
    expect(errors[0]).not.toHaveTextContent("Something went wrong.");
  });
});
