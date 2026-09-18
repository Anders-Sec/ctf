import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { DIFFICULTY_LABEL, artifactUrl, getChallenge, submitAnswer } from "../api/challenges";
import { ApiError } from "../api/client";
import ErrorMessage from "../components/ErrorMessage";
import HintList from "../components/HintList";
import InstancePanel from "../components/InstancePanel";
import PuzzlePanel from "../components/puzzle/PuzzlePanel";
import ReportChallenge from "../components/ReportChallenge";
import Spinner from "../components/Spinner";

/**
 * One challenge, as an overlay over the board (spec 062 §5).
 *
 * A child route rather than a page of its own, so the list behind it never
 * unmounts: scroll position survives by construction, a shared link still opens
 * the right challenge, and Back closes it — which is what Back means to somebody
 * looking at an overlay.
 */
export default function ChallengeDetailPage() {
  const { challengeId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");

  // Back rather than a push, so opening and closing ten challenges does not
  // leave ten entries to walk out through.
  const close = () => navigate("/challenges");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const challenge = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => getChallenge(challengeId),
  });

  const submit = useMutation({
    mutationFn: () => submitAnswer(challengeId, answer),
    onSuccess: async (result) => {
      if (result.correct) {
        setAnswer("");
        // The board, this challenge and the score all move on a solve — and so
        // does everyone else's, since the value decays.
        await queryClient.invalidateQueries({ queryKey: ["challenges"] });
        await queryClient.invalidateQueries({
          queryKey: ["challenge", challengeId],
        });
        await queryClient.invalidateQueries({ queryKey: ["my-score"] });
        // Solving a ladder rung changes which System AI the player faces, and
        // the server starts them a new session for it (spec 036). Without these
        // the panel keeps showing the old rung and the previous session's turns
        // until a page refresh — which reads as the chat being stuck.
        await queryClient.invalidateQueries({ queryKey: ["assistant", "conversation"] });
        await queryClient.invalidateQueries({ queryKey: ["me"] });
      }
    },
  });

  if (challenge.isPending) {
    return (
      <Overlay onClose={close} label="Challenge">
        <Spinner />
      </Overlay>
    );
  }

  if (challenge.isError) {
    const notFound = challenge.error instanceof ApiError && challenge.error.status === 404;
    return (
      <Overlay onClose={close} label="Challenge">
        <h1 className="text-2xl font-semibold">
          {notFound ? "No such challenge" : "Could not load that challenge"}
        </h1>
        <p className="mt-2 text-content-muted">
          {notFound && "It may not have been unsealed yet."}
        </p>
        <button type="button" onClick={close} className="mt-4 underline">
          Back to the board
        </button>
      </Overlay>
    );
  }

  const detail = challenge.data;
  const result = submit.data;
  const outOfAttempts = detail.attempts_remaining === 0 && !detail.solved;

  return (
    <Overlay onClose={close} label={detail.title ?? "Sealed challenge"}>
      <header>
        <p className="text-sm uppercase tracking-wide text-content-muted">
          {detail.category.name}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">
          {/* Null while sealed — the server sends no name for one (spec 062). */}
          {detail.title ?? "Sealed"}
        </h1>
        <p className="mt-2 text-content-muted">
          {detail.value} XP · {DIFFICULTY_LABEL[detail.difficulty]} · {detail.solve_count}{" "}
          {detail.solve_count === 1 ? "solve" : "solves"}
        </p>
      </header>

      {detail.solved && (
        <p className="mt-4 rounded border border-content/30 bg-content/5 px-3 py-2">
          You have already cleared this one.
        </p>
      )}

      {detail.locked && (
        <section className="mt-6 rounded-lg border border-accent/40 bg-accent/10 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
            Locked
          </h2>
          {detail.unlock_requirements.length > 0 ? (
            <>
              <p className="mt-1 text-sm">Opens when:</p>
              <ul className="mt-2 space-y-1 text-sm">
                {/* description is rendered server-side, so every gate type —
                    a solve, an XP total, a share of a zone — reads the same. */}
                {detail.unlock_requirements.map((req, index) => (
                  <li key={`${req.type}-${req.challenge_id ?? index}`}>
                    {req.met ? "✓" : "•"} {req.description}
                    {req.threshold !== null && req.progress !== null && (
                      <span className="ml-1 text-content-muted">
                        ({req.progress}/{req.threshold})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-1 text-sm text-content-muted">
              This challenge is not open yet.
            </p>
          )}
        </section>
      )}

      {detail.body !== null && detail.body !== "" && (
        <section className="mt-6 whitespace-pre-wrap rounded-lg border border-border bg-surface-raised p-5">
          {detail.body}
        </section>
      )}

      {detail.artifacts.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
            Files
          </h2>
          <ul className="mt-2 flex flex-col gap-2">
            {detail.artifacts.map((artifact) => (
              <li key={artifact.id}>
                <a
                  href={artifactUrl(detail.id, artifact.id)}
                  className="underline"
                  download={artifact.filename}
                >
                  {artifact.filename}
                </a>
                <span className="ml-2 text-sm text-content-muted">
                  {(artifact.size_bytes / 1024).toFixed(1)} KB
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The game goes where the description would be (spec 044 §1). The body
          above stays as its framing when there is one. */}
      {!detail.locked && detail.puzzle_kind !== null && (
        <PuzzlePanel challengeId={detail.id} />
      )}

      {!detail.locked && detail.has_container && (
        <InstancePanel challengeId={detail.id} />
      )}

      {!detail.locked && (
        <HintList challengeId={detail.id} hints={detail.hints} />
      )}

      {!detail.locked && detail.puzzle_kind === null && (
        <section className="mt-6">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              submit.mutate();
            }}
          >
            <label htmlFor="answer" className="block text-sm font-medium">
              Your answer
            </label>
            <div className="mt-1 flex gap-2">
              <input
                id="answer"
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                disabled={outOfAttempts}
                className="flex-1 rounded border border-border px-3 py-2 font-mono"
                placeholder="flag{…}"
                autoComplete="off"
              />
              <button
                type="submit"
                disabled={
                  submit.isPending || answer.trim() === "" || outOfAttempts
                }
                className="rounded bg-content px-4 py-2 font-medium text-surface disabled:opacity-50"
              >
                {submit.isPending ? "Checking…" : "Submit"}
              </button>
            </div>

            {detail.max_attempts !== null && (
              <p className="mt-2 text-sm text-content-muted">
                {outOfAttempts
                  ? "No attempts left on this challenge."
                  : `${result?.attempts_remaining ?? detail.attempts_remaining} of ${detail.max_attempts} attempts remaining.`}
              </p>
            )}
          </form>

          {result && (
            <p
              role="status"
              className={`mt-3 rounded px-3 py-2 ${
                result.correct
                  ? "border border-content/30 bg-content/5"
                  : "border border-accent/40 bg-accent/10"
              }`}
            >
              {result.message}
            </p>
          )}
          <ErrorMessage error={submit.error} />
        </section>
      )}

      <ReportChallenge challengeId={detail.id} />
    </Overlay>
  );
}

/**
 * The sheet itself.
 *
 * Full-screen below `sm` with an explicit close, because at phone width an
 * overlay covering the list is indistinguishable from a page and Back should not
 * be the only way out. A considered mobile pass across every page is queued
 * separately; this is a reasonable default, not that pass.
 */
function Overlay({
  onClose,
  label,
  children,
}: {
  onClose: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <div className="fixed inset-0 z-30 bg-content/40" onClick={onClose} aria-hidden />
      <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto sm:p-6">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={label}
          className="min-h-full w-full max-w-2xl border-border-strong bg-surface p-5 shadow-xl sm:min-h-0 sm:rounded-lg sm:border"
        >
          <button
            type="button"
            onClick={onClose}
            className="mb-3 text-sm underline"
          >
            ← Back to the board
          </button>
          {children}
        </div>
      </div>
    </>
  );
}
