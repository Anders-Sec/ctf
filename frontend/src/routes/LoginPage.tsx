import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import { requestMagicLink, startEntraLogin } from "../api/auth";
import ErrorMessage from "../components/ErrorMessage";
import { useSession } from "../auth/session";
import Spinner from "../components/Spinner";

export default function LoginPage() {
  const { me, isLoading } = useSession();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  const send = useMutation({
    mutationFn: () => requestMagicLink(email),
    onSuccess: () => setSent(true),
  });

  if (isLoading) return <Spinner />;
  if (me) return <Navigate to="/" replace />;

  const providerError = params.get("error");

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-8 p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Enter the dungeon</h1>
        <p className="mt-2 text-content-muted">Sign in to join the crawl.</p>
      </header>

      {providerError && (
        <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm">
          That sign-in did not complete. Please try again.
        </p>
      )}

      <section className="rounded-lg border border-border bg-surface-raised p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">Employees</h2>
        <button
          type="button"
          onClick={startEntraLogin}
          className="mt-3 w-full rounded bg-content px-4 py-2 font-medium text-surface hover:opacity-90"
        >
          Sign in with your work account
        </button>
        <p className="mt-2 text-xs text-content-muted">
          No password needed — you will be sent to your organisation's sign-in page.
        </p>
      </section>

      <section className="rounded-lg border border-border bg-surface-raised p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-muted">Guests</h2>

        {sent ? (
          // Deliberately says nothing about whether the address is known: the
          // API answers identically either way, and so does this screen.
          <div className="mt-3">
            <p>If that address can sign in, a link is on its way.</p>
            <p className="mt-2 text-sm text-content-muted">
              The link works once and expires in 15 minutes.
            </p>
            <button
              type="button"
              onClick={() => {
                setSent(false);
                send.reset();
              }}
              className="mt-4 text-sm underline"
            >
              Use a different address
            </button>
          </div>
        ) : (
          <form
            className="mt-3"
            onSubmit={(event) => {
              event.preventDefault();
              send.mutate();
            }}
          >
            <label htmlFor="email" className="block text-sm">
              Email address
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 w-full rounded border border-border px-3 py-2"
              placeholder="you@example.com"
            />
            <button
              type="submit"
              disabled={send.isPending}
              className="mt-3 w-full rounded border border-content px-4 py-2 font-medium hover:bg-content hover:text-surface disabled:opacity-50"
            >
              {send.isPending ? "Sending…" : "Email me a sign-in link"}
            </button>
            <ErrorMessage error={send.error} />
          </form>
        )}
      </section>
    </main>
  );
}
