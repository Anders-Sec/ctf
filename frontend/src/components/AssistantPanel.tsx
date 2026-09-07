import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useMatch } from "react-router-dom";

import { clearConversation, getConversation, sendMessage } from "../api/assistant";
import { ApiError } from "../api/client";
import { useSession } from "../auth/session";

/**
 * The dungeon master chat, reachable from any screen.
 *
 * Staff-only for now: spec 010 ships the mediator service, and spec 011 adds
 * the guardrails before players get it. The server enforces that — this only
 * decides whether to draw the button.
 *
 * There is no streaming. The model answers in about a second, measured, so a
 * typing indicator is honest and far less machinery than server-sent events.
 */
export default function AssistantPanel() {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  // What they are looking at, so they need not restate it. `useMatch` rather
  // than `useParams` because this panel lives in the layout, outside the route.
  const onChallenge = useMatch("/challenges/:challengeId");
  const challengeId = onChallenge?.params.challengeId ?? null;

  const conversation = useQuery({
    queryKey: ["assistant", "conversation"],
    queryFn: getConversation,
    enabled: open,
  });

  const send = useMutation({
    mutationFn: (content: string) => sendMessage(content, challengeId),
    onSuccess: async () => {
      setDraft("");
      await queryClient.invalidateQueries({ queryKey: ["assistant", "conversation"] });
    },
  });

  const reset = useMutation({
    mutationFn: clearConversation,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["assistant", "conversation"] });
    },
  });

  const messages = conversation.data?.messages ?? [];

  useEffect(() => {
    // Follow the conversation down as it grows, the way a chat should.
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length, send.isPending]);

  if (!me?.assistant_available) return null;

  const rateLimited = send.error instanceof ApiError && send.error.status === 429;
  const unavailable =
    conversation.data?.available === false ||
    (send.error instanceof ApiError && send.error.code === "assistant_unavailable");

  return (
    <div className="fixed bottom-4 right-4 z-40 flex flex-col items-end">
      {open && (
        <section
          aria-label="Dungeon master"
          className="mb-2 flex h-[28rem] w-[22rem] flex-col rounded-lg border border-stone bg-parchment shadow-lg"
        >
          <header className="flex items-center gap-2 border-b border-stone px-3 py-2">
            <h2 className="text-sm font-semibold">Dungeon Master</h2>
            <span className="text-xs text-muted">
              {challengeId ? "reading this encounter" : "at the table"}
            </span>
            <button
              onClick={() => reset.mutate()}
              className="ml-auto text-xs text-muted hover:underline"
            >
              New conversation
            </button>
          </header>

          <div ref={transcriptRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {conversation.isPending && <p className="text-sm text-muted">Gathering the scrolls…</p>}
            {!conversation.isPending && messages.length === 0 && (
              <p className="text-sm text-muted">
                Ask for a nudge. The dungeon master will not hand you treasure, but they know the
                terrain.
              </p>
            )}
            {messages.map((message) => (
              <p
                key={message.id}
                className={
                  message.role === "user"
                    ? "ml-6 rounded bg-stone/40 px-3 py-2 text-sm"
                    : message.error
                      ? "mr-6 rounded border border-torch/40 bg-torch/10 px-3 py-2 text-sm"
                      : "mr-6 rounded bg-white/60 px-3 py-2 text-sm"
                }
              >
                {message.content}
              </p>
            ))}
            {send.isPending && (
              <p className="mr-6 px-3 text-sm text-muted" role="status">
                The dungeon master considers…
              </p>
            )}
            {rateLimited && (
              <p role="alert" className="text-sm text-muted">
                Give them a moment to think.
              </p>
            )}
            {unavailable && (
              <p role="alert" className="text-sm text-muted">
                The dungeon master is not holding court right now.
              </p>
            )}
          </div>

          <form
            className="flex gap-2 border-t border-stone p-2"
            onSubmit={(event) => {
              event.preventDefault();
              const content = draft.trim();
              if (content) send.mutate(content);
            }}
          >
            <label htmlFor="dm-message" className="sr-only">
              Message the dungeon master
            </label>
            <input
              id="dm-message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={2000}
              placeholder="Ask for a nudge…"
              className="flex-1 rounded border border-stone bg-white/60 px-2 py-1 text-sm"
            />
            <button
              type="submit"
              disabled={send.isPending || draft.trim().length === 0}
              className="rounded bg-torch px-3 py-1 text-sm text-parchment disabled:opacity-50"
            >
              Ask
            </button>
          </form>
        </section>
      )}

      <button
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="rounded-full border border-stone bg-white/80 px-4 py-2 text-sm shadow"
      >
        {open ? "Close" : "Ask the Dungeon Master"}
      </button>
    </div>
  );
}
