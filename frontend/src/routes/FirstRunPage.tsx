import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { updateDisplayName } from "../api/auth";
import { useSession } from "../auth/session";
import ErrorMessage from "../components/ErrorMessage";

/**
 * Asked of brand-new guests before anything else. Available while still
 * pending approval — the account exists, it just cannot play yet.
 */
export default function FirstRunPage() {
  const { me, refresh } = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState(me?.user.display_name ?? "");

  const save = useMutation({
    mutationFn: () => updateDisplayName(name.trim()),
    onSuccess: async () => {
      await refresh();
      navigate("/party", { replace: true });
    },
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">What shall we call you?</h1>
        <p className="mt-2 text-muted">
          This is the name other adventurers will see on the scoreboard.
        </p>
      </header>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label htmlFor="display-name" className="block text-sm">
          Display name
        </label>
        <input
          id="display-name"
          required
          minLength={2}
          maxLength={64}
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="mt-1 w-full rounded border border-stone px-3 py-2"
        />
        <button
          type="submit"
          disabled={save.isPending || name.trim().length < 2}
          className="mt-4 w-full rounded bg-ink px-4 py-2 font-medium text-parchment disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Continue"}
        </button>
        <ErrorMessage error={save.error} />
      </form>
    </main>
  );
}
