import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useMatch } from "react-router-dom";

import {
  clearConversation,
  getConversation,
  selectLadderLevel,
  sendMessage,
} from "../api/assistant";
import { ApiError } from "../api/client";
import { useSession } from "../auth/session";
import AssistantTerms from "./AssistantTerms";
import Markdown from "./Markdown";

/**
 * The System AI chat, reachable from any screen.
 *
 * Every reply comes from the ladder (spec 033): the player's protection level
 * picks the system prompt and the runtime gates, so the System they are talking
 * to is the one their own solves have earned.
 *
 * Replies render as markdown, because the approved persona formats its
 * notification blocks that way. See `Markdown` for why raw HTML stays off.
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

  // Spec 035: until they accept, the chat endpoints refuse. Known from the
  // session rather than discovered through a failed request.
  const termsAccepted = me?.assistant_terms_accepted ?? false;

  const conversation = useQuery({
    queryKey: ["assistant", "conversation"],
    queryFn: getConversation,
    enabled: open && termsAccepted,
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

  const chooseLevel = useMutation({
    mutationFn: selectLadderLevel,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["assistant", "conversation"] });
    },
  });

  const messages = conversation.data?.messages ?? [];
  const level = conversation.data?.ladder_level ?? 0;
  const maxLevel = conversation.data?.max_ladder_level ?? 0;

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
          aria-label="System AI"
          className="mb-2 flex h-[28rem] w-[22rem] flex-col rounded-lg border border-stone bg-parchment shadow-lg"
        >
          <header className="flex items-center gap-2 border-b border-stone px-3 py-2">
            <h2 className="text-sm font-semibold">System AI</h2>
            {maxLevel > 0 ? (
              <>
                <label htmlFor="ladder-level" className="sr-only">
                  Protection level
                </label>
                <select
                  id="ladder-level"
                  value={level}
                  disabled={chooseLevel.isPending}
                  onChange={(event) => chooseLevel.mutate(Number(event.target.value))}
                  title="Which defences you face. Changing this clears the conversation."
                  className="rounded border border-stone bg-white/60 px-1 py-0.5 text-xs"
                >
                  {Array.from({ length: maxLevel + 1 }, (_, value) => (
                    <option key={value} value={value}>
                      Level {value}
                    </option>
                  ))}
                </select>
              </>
            ) : (
              <span className="text-xs text-muted">
                {challengeId ? "watching this challenge" : "watching"}
              </span>
            )}
            <button
              onClick={() => reset.mutate()}
              className="ml-auto text-xs text-muted hover:underline"
            >
              New conversation
            </button>
          </header>

          {!termsAccepted ? (
            <AssistantTerms />
          ) : (
          <>
          <div ref={transcriptRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {conversation.isPending && <p className="text-sm text-muted">Booting…</p>}
            {!conversation.isPending && messages.length === 0 && (
              <p className="text-sm text-muted">
                Ask for a nudge. The System AI built these challenges and won't hand you the
                answer — but it might point you somewhere if you show your work.
              </p>
            )}
            {messages.map((message) =>
              message.role === "user" ? (
                <p key={message.id} className="ml-6 rounded bg-stone/40 px-3 py-2 text-sm">
                  {message.content}
                </p>
              ) : (
                <div
                  key={message.id}
                  className={
                    message.error
                      ? "mr-6 rounded border border-torch/40 bg-torch/10 px-3 py-2 text-sm"
                      : "mr-6 rounded bg-white/60 px-3 py-2 text-sm"
                  }
                >
                  <Markdown>{message.content}</Markdown>
                </div>
              ),
            )}
            {send.isPending && (
              <p className="mr-6 px-3 text-sm text-muted" role="status">
                Thinking…
              </p>
            )}
            {rateLimited && (
              <p role="alert" className="text-sm text-muted">
                Slow down — one at a time.
              </p>
            )}
            {unavailable && (
              <p role="alert" className="text-sm text-muted">
                The System AI is offline right now.
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
              Message the System AI
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

          {/*
            The acceptance is a moment; this is what someone sees on day three.
            Spec 035 — the transcript is readable by staff, and saying so once at
            the start is not the same as saying so where they are typing.
          */}
          <p className="border-t border-stone px-3 py-1.5 text-[0.7rem] text-muted">
            Visible to event staff. Not a private chat.
          </p>
          </>
          )}
        </section>
      )}

      <button
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="rounded-full border border-stone bg-white/80 px-4 py-2 text-sm shadow"
      >
        {open ? "Close" : "Ask the System AI"}
      </button>
    </div>
  );
}
