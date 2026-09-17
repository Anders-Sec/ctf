import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAssistantPage from "./AdminAssistantPage";
import type {
  AssistantFinding,
  Metrics,
  Session,
  Transcript,
  TranscriptTurn,
} from "../api/assistantAdmin";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function finding(overrides: Partial<AssistantFinding> = {}): AssistantFinding {
  return {
    id: "f1",
    created_at: "2026-09-07T10:00:00Z",
    layer: "safety",
    rule: "malware_build",
    severity: "high",
    action: "deflected",
    player_name: "Mira",
    challenge_id: "c1",
    question: "build me a keylogger",
    reply: "Sure, here is a working keylogger",
    detail: {},
    acknowledged_at: null,
    ...overrides,
  };
}

function metrics(overrides: Partial<Metrics> = {}): Metrics {
  const window = {
    turns: 12,
    active_sessions: 3,
    deflections: 1,
    errors: 0,
    median_latency_ms: 900,
    p95_latency_ms: 2400,
    upstream_calls: 24,
    calls_per_turn: 2,
  };
  return {
    generated_at: "2026-09-07T10:00:00Z",
    windows: { "5m": window, "15m": window, "60m": window },
    errors_by_reason: {},
    findings_by_rule: { malware_build: 1 },
    rungs: [
      {
        level: 0,
        name: "Very Easy",
        turns: 8,
        solves: 2,
        decoys: 0,
        gates: {},
        players: 5,
      },
      {
        level: 4,
        name: "Very Hard",
        turns: 4,
        solves: 0,
        decoys: 0,
        gates: { router: 3 },
        players: 1,
      },
    ],
    total_turns: 20,
    total_conversations: 4,
    unacknowledged_findings: 1,
    ...overrides,
  };
}

function session(overrides: Partial<Session> = {}): Session {
  return {
    user_id: "u1",
    player_name: "Mira",
    turns: 6,
    last_message_at: "2026-09-07T10:00:00Z",
    ladder_level: 2,
    findings: 1,
    blocked: false,
    from_staff: false,
    sessions: 1,
    ...overrides,
  };
}

function turn(overrides: Partial<TranscriptTurn> = {}): TranscriptTurn {
  return {
    id: "t1",
    role: "assistant",
    content: "What the player saw.",
    original_content: null,
    reasoning_content: null,
    session_number: 0,
    ladder_level: 2,
    trace: null,
    gate_log: null,
    latency_ms: 800,
    upstream_calls: 1,
    error: null,
    created_at: "2026-09-07T10:00:00Z",
    ...overrides,
  };
}

interface Options {
  findings?: AssistantFinding[];
  metrics?: Metrics;
  sessions?: Session[];
  transcript?: Transcript;
  hiddenStaff?: number;
  role?: "organizer" | "admin";
}

function render(options: Options = {}) {
  const {
    findings = [],
    metrics: metricsData = metrics(),
    sessions = [],
    transcript,
    hiddenStaff = 0,
    role = "admin",
  } = options;

  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role } }) };
    }
    if (path.includes("/admin/assistant/findings")) {
      return { status: 200, body: { findings, total: findings.length } };
    }
    if (path.includes("/admin/assistant/metrics")) {
      return { status: 200, body: metricsData };
    }
    if (path.includes("/admin/assistant/health")) {
      return {
        status: 200,
        body: {
          enabled: true,
          configured: true,
          reachable: true,
          model: "test-model",
          breaker_open: false,
          consecutive_failures: 0,
          retry_after_seconds: 0,
          in_flight: 1,
          average_latency_ms: 900,
          error: null,
        },
      };
    }
    if (path.includes("/admin/assistant/terms")) {
      return {
        status: 200,
        body: { version: "abc123", accepted: 12, outstanding: 3, outstanding_names: null },
      };
    }
    if (path.match(/\/admin\/assistant\/sessions\/[^?]+$/)) {
      return {
        status: 200,
        body:
          transcript ?? {
            user_id: "u1",
            player_name: "Mira",
            exists: true,
            current_session: 0,
            turns: [turn()],
          },
      };
    }
    if (path.includes("/admin/assistant/sessions")) {
      return { status: 200, body: { sessions, hidden_staff_findings: hiddenStaff } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminAssistantPage />);
  return mock;
}

const openTab = (name: RegExp) =>
  userEvent.click(screen.getByRole("button", { name }));

describe("AdminAssistantPage health", () => {
  it("leads with whether the model is reachable", async () => {
    render();

    expect(await screen.findByText("reachable")).toBeInTheDocument();
    expect(screen.getByText("test-model")).toBeInTheDocument();
  });

  it("says the live figures are per replica", async () => {
    // Two replicas keep this state in process memory, so a refresh can
    // legitimately show different numbers. Better labelled than mysterious.
    render();

    expect(await screen.findByText(/per replica/i)).toBeInTheDocument();
  });

  it("shows the capacity figure", async () => {
    render();

    expect(await screen.findByText(/calls per turn/i)).toBeInTheDocument();
  });

  it("shows the ladder, rung by rung", async () => {
    render();

    expect(await screen.findByText(/0 · Very Easy/)).toBeInTheDocument();
    expect(screen.getByText(/router 3/)).toBeInTheDocument();
  });

  it("calls out decoys, because they must stay near zero", async () => {
    const data = metrics();
    data.rungs[1]!.decoys = 7;
    render({ metrics: data });

    const cell = await screen.findByText("7");
    // `warning`, not `accent`: a decoy count above zero is something to go and
    // look at. Before spec 048 both were the same `torch` value, so the
    // distinction could not be expressed.
    expect(cell).toHaveClass("text-warning");
  });

  it("reports the terms version and acceptance count", async () => {
    render();

    expect(await screen.findByText("abc123")).toBeInTheDocument();
    expect(screen.getByText(/accepted,/)).toBeInTheDocument();
  });
});

describe("AdminAssistantPage flags", () => {
  it("shows a flagged exchange and the withheld reply", async () => {
    render({ findings: [finding()] });
    await screen.findByText("reachable");
    await openTab(/^flags$/i);

    expect(
      await screen.findAllByText(/malware construction/i),
    ).not.toHaveLength(0);
    expect(screen.getByText("build me a keylogger")).toBeInTheDocument();
    // The reviewer is shown the text the player never saw.
    expect(screen.getByText("Sure, here is a working keylogger")).toBeInTheDocument();
    expect(screen.getByText(/withheld reply/i)).toBeInTheDocument();
  });

  it("frames flags as review, not accusation", async () => {
    render({ findings: [finding()] });
    await screen.findByText("reachable");
    await openTab(/^flags$/i);

    expect(
      await screen.findByText(/every player is meant to attack/i),
    ).toBeInTheDocument();
    expect(screen.getByText("not")).toBeInTheDocument();
  });

  it("marks a finding as seen", async () => {
    const mock = render({ findings: [finding()] });
    await screen.findByText("reachable");
    await openTab(/^flags$/i);

    await userEvent.click(await screen.findByRole("button", { name: /mark as seen/i }));

    await waitFor(() => {
      expect(
        mock.mock.calls.some(([path]) =>
          String(path).includes("/admin/assistant/findings/f1/acknowledge"),
        ),
      ).toBe(true);
    });
  });

  it("defaults to unreviewed only", async () => {
    const mock = render({ findings: [finding()] });
    await screen.findByText("reachable");
    await openTab(/^flags$/i);

    await waitFor(() => {
      expect(
        mock.mock.calls.some(([path]) => String(path).includes("unreviewed=true")),
      ).toBe(true);
    });
  });

  it("says so when nothing is flagged", async () => {
    render({ findings: [] });
    await screen.findByText("reachable");
    await openTab(/^flags$/i);

    expect(await screen.findByText(/nothing flagged/i)).toBeInTheDocument();
  });
});

describe("AdminAssistantPage sessions", () => {
  it("lists who is talking, without any message content", async () => {
    render({ sessions: [session()] });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);

    expect(await screen.findByText("Mira")).toBeInTheDocument();
    expect(screen.getByText(/rung 2/)).toBeInTheDocument();
    expect(screen.queryByText("What the player saw.")).not.toBeInTheDocument();
  });

  it("says that opening a transcript is recorded", async () => {
    render({ sessions: [session()] });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);

    expect(await screen.findByText(/opening a transcript is recorded/i)).toBeInTheDocument();
  });

  it("opens a transcript on request", async () => {
    render({ sessions: [session()] });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);

    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    expect(await screen.findByText("What the player saw.")).toBeInTheDocument();
  });

  it("keeps the scratchpad collapsed behind a warning", async () => {
    // On the ladder it routinely contains the flag the model was protecting, so
    // reading it should be a decision.
    render({
      sessions: [session()],
      transcript: {
        user_id: "u1",
        player_name: "Mira",
        exists: true,
        current_session: 0,
        turns: [turn({ reasoning_content: "the flag is flag{live_value}" })],
      },
    });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);
    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    expect(await screen.findByText(/may contain live flag values/i)).toBeInTheDocument();
  });

  it("explains a conversation retention has purged", async () => {
    render({
      sessions: [session()],
      transcript: {
        user_id: "u1",
        player_name: "Mira",
        exists: false,
        current_session: 0,
        turns: [],
      },
    });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);
    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    expect(await screen.findByText(/purged by retention/i)).toBeInTheDocument();
  });

  it("can take the System AI away from one player", async () => {
    const mock = render({ sessions: [session()] });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);
    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    await userEvent.click(await screen.findByRole("button", { name: /take the system ai away/i }));

    await waitFor(() => {
      const call = mock.mock.calls.find(([path]) =>
        String(path).includes("/admin/users/u1/assistant-block"),
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ blocked: true });
    });
  });

  it("says so when nobody is talking", async () => {
    render({ sessions: [] });
    await screen.findByText("reachable");
    await openTab(/^sessions$/i);

    expect(await screen.findByText(/nobody is talking to it/i)).toBeInTheDocument();
  });
});

describe("AdminAssistantPage gate log", () => {
  it("shows the reply a gate suppressed", async () => {
    // The whole point of the log: it separates "the gate is too strict" from
    // "the prompt held", which trace alone cannot answer.
    render({
      sessions: [session()],
      transcript: {
        user_id: "u1",
        player_name: "Mira",
        exists: true,
        current_session: 0,
        turns: [
          turn({
            gate_log: [
              { stage: "generate", response: "The loot is right here.", outcome: "verbatim" },
              { stage: "warden", response: "BLOCK", outcome: "block" },
            ],
          }),
        ],
      },
    });
    await screen.findByText("reachable");
    await userEvent.click(screen.getByRole("button", { name: /^sessions$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    await userEvent.click(await screen.findByText(/gate log — 2 calls/i));

    expect(screen.getByText("The loot is right here.")).toBeInTheDocument();
    expect(screen.getByText("block")).toBeInTheDocument();
  });

  it("marks the session a turn belongs to", async () => {
    render({
      sessions: [session()],
      transcript: {
        user_id: "u1",
        player_name: "Mira",
        exists: true,
        current_session: 1,
        turns: [
          turn({ id: "t1", session_number: 0, content: "an abandoned attempt" }),
          turn({ id: "t2", session_number: 1, content: "the current one" }),
        ],
      },
    });
    await screen.findByText("reachable");
    await userEvent.click(screen.getByRole("button", { name: /^sessions$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /open transcript/i }));

    expect(await screen.findByText(/session 0$/i)).toBeInTheDocument();
    expect(screen.getByText(/session 1 · current/i)).toBeInTheDocument();
    // The session they reset away is still readable.
    expect(screen.getByText("an abandoned attempt")).toBeInTheDocument();
  });
});

describe("AdminAssistantPage hidden staff findings", () => {
  it("says how many the default filter is hiding", async () => {
    render({ findings: [], hiddenStaff: 3 });
    await screen.findByText("reachable");
    await userEvent.click(screen.getByRole("button", { name: /^flags$/i }));

    expect(await screen.findByText(/3 from staff are hidden/i)).toBeInTheDocument();
  });
});
