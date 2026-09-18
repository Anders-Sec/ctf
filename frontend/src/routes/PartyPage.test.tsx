import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartyPage from "./PartyPage";
import type { Me } from "../api/auth";
import { me, renderApp, stubFetch } from "../test/utils";

/**
 * The party page's first tests (spec 072).
 *
 * 577 lines across eight components, every one of them a write, and most of
 * those writes hard to take back mid-event: remove a member, hand over
 * leadership, leave. Spec 067 added the standing panel here and claimed "every
 * existing party test passes untouched", which was true only because there
 * were none.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const SELF = "11111111-1111-1111-1111-111111111111";
const OTHER = "22222222-2222-2222-2222-222222222222";

function team(overrides: Record<string, unknown> = {}) {
  return {
    id: "t1",
    name: "The Grey Company",
    visibility: "public",
    member_count: 2,
    max_members: 8,
    has_space: true,
    requires_password: false,
    ...overrides,
  };
}

function member(overrides: Record<string, unknown> = {}) {
  return {
    user_id: OTHER,
    display_name: "Bex",
    is_leader: false,
    has_avatar: false,
    joined_at: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    ...team(),
    leader_user_id: SELF,
    created_at: "2026-09-01T09:00:00Z",
    members: [
      member({ user_id: SELF, display_name: "Grix", is_leader: true }),
      member(),
    ],
    ...overrides,
  };
}

const PANEL = {
  id: "t1",
  name: "The Grey Company",
  rank: 3,
  level: 4,
  stars: [],
  solve_count: 12,
  achievement_count: 5,
  founded_at: "2026-09-01T09:00:00Z",
  members: [],
};

const PROGRESS = { zones: [], solved_by: {} };

/**
 * `me` drives which half of the page renders, so every test says which player
 * it is: nobody, a member, or the leader.
 */
function as(kind: "none" | "member" | "leader"): Partial<Me> {
  if (kind === "none") return { team: null };
  return {
    team: { id: "t1", name: "The Grey Company", is_leader: kind === "leader" },
  } as Partial<Me>;
}

function render({
  who = "none",
  teams = [team()],
  party = detail(),
  requests = [] as unknown[],
  panel = PANEL as unknown,
  panelFails = false,
  post = { message: "ok" } as unknown,
}: Record<string, unknown> = {}) {
  const mock = stubFetch((path, init) => {
    if (path.includes("/auth/me")) {
      return { status: 200, body: me(as(who as "none") as Partial<Me>) };
    }
    if (init?.method && init.method !== "GET") return { status: 200, body: post };
    if (path.includes("/join-requests")) return { status: 200, body: requests };
    if (path.includes("/progress")) return { status: 200, body: PROGRESS };
    if (path.includes("/scoreboard/teams/")) {
      return panelFails
        ? { status: 503, body: { error: { code: "unavailable", message: "no" } } }
        : { status: 200, body: panel };
    }
    if (/\/teams\/[^/]+$/.test(path)) return { status: 200, body: party };
    if (path.endsWith("/teams")) return { status: 200, body: teams };
    return { status: 200, body: {} };
  });
  renderApp(<PartyPage />, { route: "/party" });
  return mock;
}

/** The body of the first non-GET call whose payload mentions `marker`. */
function bodyOf(mock: ReturnType<typeof stubFetch>, marker: string) {
  const call = mock.mock.calls.find(([, init]) =>
    String((init as RequestInit)?.body ?? "").includes(marker),
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : null;
}

function urlsOf(mock: ReturnType<typeof stubFetch>, method: string) {
  return mock.mock.calls
    .filter(([, init]) => (init as RequestInit)?.method === method)
    .map(([path]) => String(path));
}

/* ------------------------------------------------------------------ */
/* Browsing                                                            */
/* ------------------------------------------------------------------ */

describe("PartyBrowser", () => {
  it("says so when there are no parties to join", async () => {
    render({ teams: [] });

    expect(await screen.findByText(/no open parties yet/i)).toBeInTheDocument();
  });

  it("joins an open party directly", async () => {
    const mock = render();

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    await waitFor(() => expect(urlsOf(mock, "POST").some((u) => u.endsWith("/t1/join"))).toBe(true));
  });

  it("says Full instead of offering to join a party with no space", async () => {
    render({ teams: [team({ has_space: false, member_count: 8 })] });

    expect(await screen.findByText("Full")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("asks for the password before joining a protected party", async () => {
    const mock = render({
      teams: [team({ visibility: "private", requires_password: true })],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Join with password" }),
    );
    await userEvent.type(screen.getByLabelText(/password for/i), "mellon123");
    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => expect(bodyOf(mock, "password")).toBeTruthy());
    expect(bodyOf(mock, "password").password).toBe("mellon123");
  });

  it("offers to ask when a private party has no password", async () => {
    render({ teams: [team({ visibility: "private", requires_password: false })] });

    expect(
      await screen.findByRole("button", { name: "Ask to join" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("sends a message with the request, and confirms it went", async () => {
    // Spec 072 §3.1: the leader's view has always rendered this message and
    // nothing ever sent one.
    const mock = render({
      teams: [team({ visibility: "private", requires_password: false })],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Ask to join" }));
    await userEvent.type(screen.getByLabelText(/say something/i), "Grix, from Ops.");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(bodyOf(mock, "Grix, from Ops.")).toBeTruthy());
    expect(bodyOf(mock, "Grix, from Ops.").message).toBe("Grix, from Ops.");
    expect(await screen.findByRole("button", { name: "Request sent" })).toBeDisabled();
  });

  it("lets the message be left empty", async () => {
    const mock = render({
      teams: [team({ visibility: "private", requires_password: false })],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Ask to join" }));
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() =>
      expect(urlsOf(mock, "POST").some((u) => u.includes("join-requests"))).toBe(true),
    );
    expect(bodyOf(mock, "message").message).toBeNull();
  });

  it("reports a refused join in our own words, not the server's", async () => {
    stubFetch((path, init) => {
      if (path.includes("/auth/me")) return { status: 200, body: me(as("none")) };
      if (init?.method === "POST") {
        return {
          status: 409,
          body: { error: { code: "team_full", message: "Team t1 is at capacity." } },
        };
      }
      return { status: 200, body: [team()] };
    });
    renderApp(<PartyPage />, { route: "/party" });

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // ErrorMessage keys on `code` on purpose, so wording stays in the frontend.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/eight adventurers is the limit/i);
    expect(alert).not.toHaveTextContent("at capacity");
  });
});

/* ------------------------------------------------------------------ */
/* Forming                                                             */
/* ------------------------------------------------------------------ */

describe("CreatePartyForm", () => {
  async function openCreate() {
    await userEvent.click(await screen.findByRole("tab", { name: "Start a party" }));
  }

  it("will not submit a name under three characters", async () => {
    render();
    await openCreate();

    await userEvent.type(screen.getByLabelText("Party name"), "ab");

    expect(screen.getByRole("button", { name: "Form the party" })).toBeDisabled();
  });

  it("creates a public party with no password", async () => {
    const mock = render();
    await openCreate();

    await userEvent.type(screen.getByLabelText("Party name"), "The Grey Company");
    await userEvent.click(screen.getByRole("button", { name: "Form the party" }));

    await waitFor(() => expect(bodyOf(mock, "The Grey Company")).toBeTruthy());
    const body = bodyOf(mock, "The Grey Company");
    expect(body.visibility).toBe("public");
    expect(body.join_password).toBeNull();
  });

  it("only offers a password once the party is private", async () => {
    render();
    await openCreate();

    expect(screen.queryByLabelText(/party password/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/only with a password/i));

    expect(screen.getByLabelText(/party password/i)).toBeInTheDocument();
  });

  it("does not send a password typed and then hidden again", async () => {
    // The field unmounts but its state does not, so a public party could
    // otherwise be created carrying a password nobody can see.
    const mock = render();
    await openCreate();

    await userEvent.type(screen.getByLabelText("Party name"), "The Grey Company");
    await userEvent.click(screen.getByLabelText(/only with a password/i));
    await userEvent.type(screen.getByLabelText(/party password/i), "mellon123");
    await userEvent.click(screen.getByLabelText(/anyone can join/i));
    await userEvent.click(screen.getByRole("button", { name: "Form the party" }));

    await waitFor(() => expect(bodyOf(mock, "The Grey Company")).toBeTruthy());
    expect(bodyOf(mock, "The Grey Company").join_password).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* Your own party                                                      */
/* ------------------------------------------------------------------ */

describe("MyParty", () => {
  it("shows the party and its roster", async () => {
    render({ who: "member" });

    expect(
      await screen.findByRole("heading", { name: "The Grey Company" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Bex")).toBeInTheDocument();
    expect(screen.getByText("you")).toBeInTheDocument();
  });

  it("shows the standing the page never used to", async () => {
    render({ who: "member" });

    // Spec 067: until then you could learn more about a stranger's party from
    // the scoreboard than about your own from here.
    expect(await screen.findByText("#3")).toBeInTheDocument();
    expect(screen.getByText(/12 solved/)).toBeInTheDocument();
  });

  it("stays usable when the standing has not arrived", async () => {
    // `panel.data &&` — a slow board must not take the roster down with it.
    // Passing `undefined` would hit the destructuring default and quietly give
    // the panel back, so this fails the request instead.
    render({ who: "member", panelFails: true });

    expect(await screen.findByText("Bex")).toBeInTheDocument();
    expect(screen.queryByText("#3")).not.toBeInTheDocument();
  });

  it("gives a plain member no roster controls", async () => {
    render({ who: "member" });
    await screen.findByText("Bex");

    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make leader" })).not.toBeInTheDocument();
  });

  it("gives the leader controls on others but not on themselves", async () => {
    render({ who: "leader" });
    await screen.findByText("Bex");

    // One other member, so exactly one of each — never on their own row.
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Make leader" })).toHaveLength(1);
  });

  it("removes a member by their id", async () => {
    const mock = render({ who: "leader" });
    await screen.findByText("Bex");

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(urlsOf(mock, "DELETE").some((u) => u.endsWith(`/t1/members/${OTHER}`))).toBe(
        true,
      ),
    );
  });

  it("hands leadership over by user id, not member index", async () => {
    const mock = render({ who: "leader" });
    await screen.findByText("Bex");

    await userEvent.click(screen.getByRole("button", { name: "Make leader" }));

    await waitFor(() => expect(bodyOf(mock, "user_id")).toBeTruthy());
    expect(bodyOf(mock, "user_id").user_id).toBe(OTHER);
  });

  it("leaves by deleting your own membership", async () => {
    const mock = render({ who: "member" });
    await screen.findByText("Bex");

    await userEvent.click(screen.getByRole("button", { name: "Leave party" }));

    await waitFor(() =>
      expect(urlsOf(mock, "DELETE").some((u) => u.endsWith(`/t1/members/${SELF}`))).toBe(
        true,
      ),
    );
  });

  it("says that XP leaves with you", async () => {
    render({ who: "member" });

    expect(await screen.findByText(/your xp goes with you/i)).toBeInTheDocument();
  });

  it("does not fetch join requests for a plain member", async () => {
    const mock = render({ who: "member" });
    await screen.findByText("Bex");

    // `enabled: isLeader` — a member asking would just 403.
    expect(mock.mock.calls.some(([p]) => String(p).includes("join-requests"))).toBe(false);
  });

  it("fetches them for the leader", async () => {
    const mock = render({ who: "leader" });
    await screen.findByText("Bex");

    await waitFor(() =>
      expect(mock.mock.calls.some(([p]) => String(p).includes("join-requests"))).toBe(true),
    );
  });
});

/* ------------------------------------------------------------------ */
/* The door                                                            */
/* ------------------------------------------------------------------ */

describe("JoinRequestsSection", () => {
  const request = {
    id: "r1",
    team_id: "t1",
    user_id: "33333333-3333-3333-3333-333333333333",
    display_name: "Sella",
    status: "pending",
    message: "Grix, from Ops.",
    created_at: "2026-09-02T10:00:00Z",
  };

  it("says nobody is waiting when nobody is", async () => {
    render({ who: "leader" });

    expect(await screen.findByText(/nobody is waiting/i)).toBeInTheDocument();
    expect(screen.getByText(/knocking at the door \(0\)/i)).toBeInTheDocument();
  });

  it("counts the people waiting and shows what they said", async () => {
    render({ who: "leader", requests: [request] });

    expect(await screen.findByText(/knocking at the door \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText("Sella")).toBeInTheDocument();
    // Dead until spec 072 fixed the sending end.
    expect(screen.getByText(/Grix, from Ops\./)).toBeInTheDocument();
  });

  it("accepts by request id, not by user id", async () => {
    const mock = render({ who: "leader", requests: [request] });
    await screen.findByText("Sella");

    await userEvent.click(screen.getByRole("button", { name: "Let them in" }));

    await waitFor(() =>
      expect(urlsOf(mock, "POST").some((u) => u.endsWith("/join-requests/r1/accept"))).toBe(
        true,
      ),
    );
  });

  it("declines by request id too", async () => {
    const mock = render({ who: "leader", requests: [request] });
    await screen.findByText("Sella");

    await userEvent.click(screen.getByRole("button", { name: "Decline" }));

    await waitFor(() =>
      expect(urlsOf(mock, "POST").some((u) => u.endsWith("/join-requests/r1/reject"))).toBe(
        true,
      ),
    );
  });
});

/* ------------------------------------------------------------------ */
/* Settings                                                            */
/* ------------------------------------------------------------------ */

describe("PartySettings", () => {
  it("is the leader's alone", async () => {
    render({ who: "member" });
    await screen.findByText("Bex");

    expect(screen.queryByText(/party settings/i)).not.toBeInTheDocument();
  });

  it("sends only what changed", async () => {
    const mock = render({ who: "leader" });
    await screen.findByText("Bex");

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(urlsOf(mock, "PATCH")).toHaveLength(1));
    const body = bodyOf(mock, "{");
    // Unchanged fields are absent, not echoed back: this endpoint patches.
    expect(body.name).toBeUndefined();
    expect(body.visibility).toBeUndefined();
    expect(body.join_password).toBeUndefined();
  });

  it("sends a renamed party", async () => {
    const mock = render({ who: "leader" });
    await screen.findByText("Bex");

    const field = screen.getByLabelText("Name");
    await userEvent.clear(field);
    await userEvent.type(field, "The Fellowship");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(bodyOf(mock, "The Fellowship")).toBeTruthy());
    expect(bodyOf(mock, "The Fellowship").name).toBe("The Fellowship");
  });

  it("offers to remove a password only when there is one", async () => {
    render({ who: "leader", party: detail({ visibility: "private" }) });
    await screen.findByText("Bex");

    expect(screen.queryByLabelText(/remove the password/i)).not.toBeInTheDocument();
  });

  it("clears the password with the flag the API has always accepted", async () => {
    // Spec 072 §3.2: implemented the whole way down and sent by nothing.
    const mock = render({
      who: "leader",
      party: detail({ visibility: "private", requires_password: true }),
    });
    await screen.findByText("Bex");

    await userEvent.click(screen.getByLabelText(/remove the password/i));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(bodyOf(mock, "clear_password")).toBeTruthy());
    expect(bodyOf(mock, "clear_password").clear_password).toBe(true);
  });
});
