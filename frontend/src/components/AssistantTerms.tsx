import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { acceptTerms, getTerms } from "../api/assistant";
import { ApiError } from "../api/client";
import ErrorMessage from "./ErrorMessage";
import Markdown from "./Markdown";
import Spinner from "./Spinner";

/**
 * The terms of use a player accepts before the System AI will talk to them
 * (spec 035).
 *
 * This is what makes the admin transcript view in spec 034 sound: conversations
 * are readable by event staff, and players are told so here rather than in a
 * briefing everyone half-hears.
 *
 * Shown in place of the transcript rather than as a modal over the app — the
 * chat is optional, and a player who does not want it should be able to close
 * the panel and carry on with the event.
 */
export default function AssistantTerms() {
  const queryClient = useQueryClient();

  const terms = useQuery({ queryKey: ["assistant", "terms"], queryFn: getTerms });

  const accept = useMutation({
    mutationFn: (version: string) => acceptTerms(version),
    onSuccess: async () => {
      // Both: the session query carries the flag the panel switches on, and the
      // conversation query was refused while the gate was shut.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["me"] }),
        queryClient.invalidateQueries({ queryKey: ["assistant", "conversation"] }),
      ]);
    },
    onError: async (error) => {
      // 409 means the wording changed between load and click. Re-fetch so they
      // accept what they can actually see.
      if (error instanceof ApiError && error.code === "assistant_terms_stale") {
        await queryClient.invalidateQueries({ queryKey: ["assistant", "terms"] });
      }
    },
  });

  if (terms.isPending) return <Spinner label="Fetching the paperwork…" />;
  if (terms.isError) return <ErrorMessage error={terms.error} />;

  const stale =
    accept.error instanceof ApiError && accept.error.code === "assistant_terms_stale";

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-3 py-3 text-sm">
        <Markdown>{terms.data.text}</Markdown>
      </div>

      <div className="border-t border-stone p-3">
        {stale && (
          <p role="alert" className="mb-2 text-xs text-torch">
            These terms were updated while you were reading. Please look again.
          </p>
        )}
        {accept.isError && !stale && <ErrorMessage error={accept.error} />}
        <button
          onClick={() => accept.mutate(terms.data.version)}
          disabled={accept.isPending}
          className="w-full rounded bg-torch px-3 py-2 text-sm text-parchment disabled:opacity-50"
        >
          {accept.isPending ? "Filing…" : "I have read and accept these terms"}
        </button>
      </div>
    </div>
  );
}
