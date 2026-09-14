import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AssistantPanel from "./AssistantPanel";
import type { AssistantMessage } from "../api/assistant";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const TERMS_TEXT = ["# Terms", "", "This conversation is **not private**."].join("\n");

function message(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "Look to the packet comments.",
    challenge_id: null,
    created_at: "2026-09-02T12:00:00Z",
    error: null,
    ...overrides,
  };
}

interface Options {
  available?: boolean;
  assistantAvailable?: boolean;
  messages?: AssistantMessage[];
  sendStatus?: number;
  sendBody?: unknown;
  route?: string;
  termsAccepted?: boolean;
  termsStatus?: number;
  ladderLevel?: number;
  maxLadderLevel?: number;
}

function render(options: Options = {}) {
  const {
    available = true,
    assistantAvailable = true,
    messages = [],
    sendStatus = 200,
    sendBody = { message: message() },
    route = "/",
    termsAccepted = true,
    termsStatus = 200,
    ladderLevel = 0,
    maxLadderLevel = 0,
  } = options;

  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({
          assistant_available: assistantAvailable,
          assistant_terms_accepted: termsAccepted,
        }),
      };
    }
    if (path.endsWith("/assistant/terms/accept")) {
      return {
        status: termsStatus,
        body:
          termsStatus === 200
            ? { text: TERMS_TEXT, version: "v1", accepted: true }
            : { error: { code: "assistant_terms_stale", message: "Updated." } },
      };
    }
    if (path.endsWith("/assistant/terms")) {
      return {
        status: 200,
        body: { text: TERMS_TEXT, version: "v1", accepted: termsAccepted },
      };
    }
    if (path.endsWith("/assistant/messages")) {
      return { status: sendStatus, body: sendBody };
    }
    if (path.endsWith("/assistant/ladder-level")) {
      return {
        status: 200,
        body: {
          ladder_level: 0,
          max_ladder_level: maxLadderLevel,
          conversation_cleared: true,
        },
      };
    }
    if (path.endsWith("/assistant/conversation")) {
      if (init?.method === "DELETE") return { status: 204, body: undefined };
      return {
        status: 200,
        body: {
          available,
          messages,
          ladder_level: ladderLevel,
          max_ladder_level: maxLadderLevel,
        },
      };
    }
    return { status: 200, body: {} };
  });

  renderApp(<AssistantPanel />, { route });
  return mock;
}

async function open() {
  await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));
}

describe("AssistantPanel", () => {
  it("is not offered to anyone the server has not cleared", async () => {
    render({ assistantAvailable: false });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /system ai/i })).not.toBeInTheDocument();
    });
  });

  it("stays shut until it is asked for", async () => {
    render();
    await screen.findByRole("button", { name: /ask the system ai/i });

    expect(screen.queryByRole("region", { name: /system ai/i })).not.toBeInTheDocument();
  });

  it("shows the conversation so far", async () => {
    render({
      messages: [
        message({ id: "m1", role: "user", content: "where do I start?" }),
        message({ id: "m2", content: "Read the packet comments." }),
      ],
    });
    await open();

    expect(await screen.findByText("where do I start?")).toBeInTheDocument();
    expect(screen.getByText("Read the packet comments.")).toBeInTheDocument();
  });

  it("sends what the player typed and shows the reply", async () => {
    const fetchMock = render({ sendBody: { message: message({ content: "Try the metadata." }) } });
    await open();

    await userEvent.type(await screen.findByLabelText(/message the system ai/i), "any ideas?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const call = fetchMock.mock.calls.find(([path]) =>
      String(path).endsWith("/assistant/messages"),
    );
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      content: "any ideas?",
      challenge_id: null,
    });
  });

  it("tells the server which encounter is on screen", async () => {
    const fetchMock = render({ route: "/challenges/c-42" });
    await open();

    await userEvent.type(await screen.findByLabelText(/message the system ai/i), "stuck");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/assistant/messages"),
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ challenge_id: "c-42" });
    });
  });

  it("will not send an empty message", async () => {
    render();
    await open();
    await screen.findByLabelText(/message the system ai/i);

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("marks a reply the model could not give", async () => {
    render({
      messages: [
        message({
          content: "The System AI is offline right now.",
          error: "unreachable",
        }),
      ],
    });
    await open();

    expect(await screen.findByText(/offline right now/i)).toBeInTheDocument();
  });

  it("says so when the assistant is switched off", async () => {
    render({ available: false });
    await open();

    expect(await screen.findByRole("alert")).toHaveTextContent(/offline right now/i);
  });

  it("explains a rate limit rather than showing a raw error", async () => {
    render({
      sendStatus: 429,
      sendBody: { error: { code: "rate_limited", message: "Too many." } },
    });
    await open();

    await userEvent.type(await screen.findByLabelText(/message the system ai/i), "again");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/slow down/i);
  });

  it("can start the conversation again", async () => {
    const fetchMock = render({ messages: [message({ content: "an old answer" })] });
    await open();
    await screen.findByText("an old answer");

    await userEvent.click(screen.getByRole("button", { name: /new conversation/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            String(path).endsWith("/assistant/conversation") && init?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });
});

describe("AssistantPanel markdown", () => {
  it("renders the notification block rather than showing raw asterisks", async () => {
    render({
      messages: [
        message({
          content: [
            "> **[ SYSTEM NOTIFICATION ]**",
            "> *Achievement Unlocked: Reads The Room*",
            "",
            "Carry on.",
          ].join("\n"),
        }),
      ],
    });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    expect(await screen.findByText(/SYSTEM NOTIFICATION/)).toBeInTheDocument();
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  });

  it("never renders HTML from a reply", async () => {
    // Model output steered by whatever the player typed. A prompt-injection
    // ladder is exactly where someone will try this.
    render({ messages: [message({ content: "<img src=x onerror=alert(1)>" })] });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    const panel = await screen.findByRole("region", { name: /system ai/i });
    expect(panel.querySelector("img")).toBeNull();
    expect(panel.textContent).toContain("<img");
  });

  it("shows the player's own message verbatim", async () => {
    render({ messages: [message({ role: "user", content: "what about **this**?" })] });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    expect(await screen.findByText("what about **this**?")).toBeInTheDocument();
  });
});

describe("AssistantPanel ladder selector", () => {
  it("is hidden for a player who has not earned a rung", async () => {
    render({ maxLadderLevel: 0 });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    expect(screen.queryByLabelText(/protection level/i)).not.toBeInTheDocument();
  });

  it("offers every rung up to the one they have earned", async () => {
    render({ ladderLevel: 3, maxLadderLevel: 3 });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    const select = (await screen.findByLabelText(/protection level/i)) as HTMLSelectElement;
    expect(select.value).toBe("3");
    expect(select.querySelectorAll("option")).toHaveLength(4);
  });

  it("sends the chosen rung to the server", async () => {
    const mock = render({ ladderLevel: 2, maxLadderLevel: 2 });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));
    await userEvent.selectOptions(await screen.findByLabelText(/protection level/i), "0");

    await waitFor(() => {
      const call = mock.mock.calls.find(([path]) =>
        String(path).endsWith("/assistant/ladder-level"),
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ level: 0 });
    });
  });
});

describe("AssistantPanel terms gate", () => {
  it("shows the terms instead of the chat until they are accepted", async () => {
    render({ termsAccepted: false });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    expect(await screen.findByText(/not private/i)).toBeInTheDocument();
    // No way to type until they have accepted.
    expect(screen.queryByLabelText(/message the system ai/i)).not.toBeInTheDocument();
  });

  it("accepts the version it was shown", async () => {
    const mock = render({ termsAccepted: false });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));
    await userEvent.click(await screen.findByRole("button", { name: /accept these terms/i }));

    await waitFor(() => {
      const call = mock.mock.calls.find(([path]) =>
        String(path).endsWith("/assistant/terms/accept"),
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ version: "v1" });
    });
  });

  it("explains a version that changed while they were reading", async () => {
    render({ termsAccepted: false, termsStatus: 409 });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));
    await userEvent.click(await screen.findByRole("button", { name: /accept these terms/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/updated while you were reading/i);
  });

  it("does not fetch the conversation while the gate is shut", async () => {
    const mock = render({ termsAccepted: false });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));
    await screen.findByText(/not private/i);

    expect(
      mock.mock.calls.filter(([path]) => String(path).endsWith("/assistant/conversation")),
    ).toHaveLength(0);
  });

  it("keeps a standing reminder once accepted", async () => {
    // The acceptance is a moment; this is what someone sees on day three.
    render({ termsAccepted: true });

    await userEvent.click(await screen.findByRole("button", { name: /ask the system ai/i }));

    expect(await screen.findByText(/visible to event staff/i)).toBeInTheDocument();
  });
});
