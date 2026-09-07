import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AssistantPanel from "./AssistantPanel";
import type { AssistantMessage } from "../api/assistant";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

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
}

function render(options: Options = {}) {
  const {
    available = true,
    assistantAvailable = true,
    messages = [],
    sendStatus = 200,
    sendBody = { message: message() },
    route = "/",
  } = options;

  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ assistant_available: assistantAvailable }) };
    }
    if (path.endsWith("/assistant/messages")) {
      return { status: sendStatus, body: sendBody };
    }
    if (path.endsWith("/assistant/conversation")) {
      if (init?.method === "DELETE") return { status: 204, body: undefined };
      return { status: 200, body: { available, messages } };
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
