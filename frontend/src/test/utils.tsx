import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { FALLBACK_THEME } from "../theme/themes";
import { SessionProvider } from "../auth/session";
import type { Capabilities, Me } from "../api/auth";

export function renderApp(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <SessionProvider>{ui}</SessionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    manage_party: true,
    play: true,
    view_scoreboard: true,
    view_admin: false,
    administer: false,
    blocked_reason: null,
    ...overrides,
  };
}

export function me(overrides: Partial<Me> = {}): Me {
  return {
    user: {
      id: "11111111-1111-1111-1111-111111111111",
      email: "player@example.com",
      display_name: "Grix",
      source: "guest",
      role: "player",
      status: "active",
      has_avatar: false,
      created_at: "2026-09-01T00:00:00Z",
    },
    team: null,
    theme: FALLBACK_THEME,
    theme_source: "event",
    high_contrast: false,
    base_theme: FALLBACK_THEME,
    capabilities: capabilities(),
    event: {
      name: "Autumn Crawl",
      starts_at: "2026-09-01T09:00:00Z",
      ends_at: "2026-09-03T17:00:00Z",
      registration_open: true,
      server_time: "2026-09-02T12:00:00Z",
    },
    assistant_available: false,
    // Accepted by default: that is the state for all but a player's first
    // visit, and the terms gate has its own tests (spec 035).
    assistant_terms_accepted: true,
    ...overrides,
  };
}

type Handler = (path: string, init?: RequestInit) => { status: number; body: unknown };

/** Installs a fetch stub and returns the mock so calls can be asserted on. */
export function stubFetch(handler: Handler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const { status, body } = handler(String(input), init);
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", "X-Request-ID": "test-req" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
