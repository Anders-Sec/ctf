import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  KIND_LABEL,
  getPuzzle,
  playMove,
  savePuzzle,
  type PuzzleMove,
  type PuzzleState,
} from "../../api/puzzles";
import ErrorMessage from "../ErrorMessage";
import Spinner from "../Spinner";
import ConnectionsBoard from "./ConnectionsBoard";
import CrosswordBoard from "./CrosswordBoard";
import WordleBoard from "./WordleBoard";

/**
 * A daily puzzle, where a challenge's description normally goes (spec 044 §1).
 *
 * This component owns the round trip and the shared furniture — the banner, the
 * refused-move message, invalidating everything a solve moves — and each game
 * owns only its own board.
 */
export default function PuzzlePanel({ challengeId }: { challengeId: string }) {
  const queryClient = useQueryClient();
  const [refusal, setRefusal] = useState<string | null>(null);

  const puzzle = useQuery({
    queryKey: ["puzzle", challengeId],
    queryFn: () => getPuzzle(challengeId),
  });

  const play = useMutation({
    mutationFn: (move: PuzzleMove) => playMove(challengeId, move),
    onSuccess: async (result) => {
      setRefusal(null);
      queryClient.setQueryData(["puzzle", challengeId], result);
      if (result.solved) {
        // A solve moves the board, this challenge, the score — and, through
        // decay, everyone else's standing too.
        await queryClient.invalidateQueries({ queryKey: ["challenges"] });
        await queryClient.invalidateQueries({ queryKey: ["challenge", challengeId] });
        await queryClient.invalidateQueries({ queryKey: ["my-score"] });
      } else if (result.status === "failed") {
        // The board marks a failed daily, so it has to hear about it too.
        await queryClient.invalidateQueries({ queryKey: ["challenges"] });
      }
    },
    onError: (error) => {
      // A refused move — an unknown word, a repeated guess — is ordinary play,
      // not a failure. It costs nothing and belongs next to the board rather
      // than in a red error box.
      if (error instanceof ApiError && error.status === 422) setRefusal(error.message);
      else setRefusal(null);
    },
  });

  // Fire-and-forget: a flush that fails is retried by the next one, and the
  // player must never be interrupted mid-word to be told about it.
  const save = useMutation({
    mutationFn: (grid: string[][]) => savePuzzle(challengeId, grid),
    onError: () => {},
  });

  if (puzzle.isPending) return <Spinner label="Setting out the tiles…" />;
  if (puzzle.isError) return <ErrorMessage error={puzzle.error} />;

  const state = puzzle.data;

  return (
    <section
      className="mt-6 rounded-lg border border-border bg-surface-raised p-5"
      aria-label={`${KIND_LABEL[state.kind]} puzzle`}
    >
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          {KIND_LABEL[state.kind]}
        </h2>
        {state.status && <Banner state={state} />}
      </header>

      {state.kind === "wordle" && (
        <WordleBoard
          state={state}
          onPlay={(guess) => play.mutate({ guess })}
          pending={play.isPending}
          error={refusal}
        />
      )}
      {state.kind === "connections" && (
        <ConnectionsBoard
          state={state}
          onPlay={(members) => play.mutate({ members })}
          pending={play.isPending}
        />
      )}
      {state.kind === "crossword" && (
        <CrosswordBoard
          challengeId={challengeId}
          state={state}
          onPlay={(grid) => play.mutate({ grid })}
          onSave={(grid) => save.mutate(grid)}
          pending={play.isPending}
        />
      )}

      {refusal && (
        <p
          role="status"
          className="mt-3 rounded border border-accent/40 bg-accent/10 px-3 py-2 text-sm"
        >
          {refusal}
        </p>
      )}
      {play.isError && !refusal && <ErrorMessage error={play.error} />}

      {state.kind === "connections" && state.feedback?.result === "one_away" && (
        <p role="status" className="mt-3 text-center text-sm font-medium">
          One away…
        </p>
      )}
    </section>
  );
}

function Banner({ state }: { state: PuzzleState }) {
  if (state.status === "solved") {
    return (
      <p className="rounded border border-success/40 bg-success/15 px-2 py-0.5 text-sm font-medium text-success">
        Solved{state.xp_awarded ? ` · ${state.xp_awarded} XP` : ""}
      </p>
    );
  }
  if (state.status === "failed") {
    return (
      <p className="rounded border border-border bg-surface-sunken px-2 py-0.5 text-sm font-medium text-content-muted">
        Out of luck today
      </p>
    );
  }
  return null;
}
