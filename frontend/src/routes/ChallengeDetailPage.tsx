import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { artifactUrl, getChallenge, submitAnswer } from "../api/challenges";
import { ApiError } from "../api/client";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

export default function ChallengeDetailPage() {
  const { challengeId = "" } = useParams();
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");

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
        await queryClient.invalidateQueries({ queryKey: ["challenge", challengeId] });
        await queryClient.invalidateQueries({ queryKey: ["my-score"] });
      }
    },
  });

  if (challenge.isPending) return <Spinner />;
  if (challenge.isError) {
    const notFound = challenge.error instanceof ApiError && challenge.error.status === 404;
    return (
      <main className="mx-auto max-w-2xl p-6">
        <h1 className="text-2xl font-semibold">
          {notFound ? "No such challenge" : "Could not load that challenge"}
        </h1>
        <p className="mt-2 text-muted">
          {notFound && "It may not have been unsealed yet."}
        </p>
        <Link to="/challenges" className="mt-4 inline-block underline">
          Back to the board
        </Link>
      </main>
    );
  }

  const detail = challenge.data;
  const result = submit.data;
  const outOfAttempts = detail.attempts_remaining === 0 && !detail.solved;

  return (
    <main className="mx-auto max-w-2xl p-6">
      <Link to="/challenges" className="text-sm underline">
        ← Back to the board
      </Link>

      <header className="mt-4">
        <p className="text-sm uppercase tracking-wide text-muted">{detail.category.name}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">{detail.title}</h1>
        <p className="mt-2 text-muted">
          {detail.value} points · {detail.difficulty} · {detail.solve_count}{" "}
          {detail.solve_count === 1 ? "solve" : "solves"}
        </p>
      </header>

      {detail.solved && (
        <p className="mt-4 rounded border border-ink/30 bg-ink/5 px-3 py-2">
          You have already cleared this one.
        </p>
      )}

      {detail.body !== null && (
        <section className="mt-6 whitespace-pre-wrap rounded-lg border border-stone bg-white/60 p-5">
          {detail.body}
        </section>
      )}

      {detail.artifacts.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Files</h2>
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
                <span className="ml-2 text-sm text-muted">
                  {(artifact.size_bytes / 1024).toFixed(1)} KB
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

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
              className="flex-1 rounded border border-stone px-3 py-2 font-mono"
              placeholder="flag{…}"
              autoComplete="off"
            />
            <button
              type="submit"
              disabled={submit.isPending || answer.trim() === "" || outOfAttempts}
              className="rounded bg-ink px-4 py-2 font-medium text-parchment disabled:opacity-50"
            >
              {submit.isPending ? "Checking…" : "Submit"}
            </button>
          </div>

          {detail.max_attempts !== null && (
            <p className="mt-2 text-sm text-muted">
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
                ? "border border-ink/30 bg-ink/5"
                : "border border-torch/40 bg-torch/10"
            }`}
          >
            {result.message}
          </p>
        )}
        <ErrorMessage error={submit.error} />
      </section>
    </main>
  );
}
