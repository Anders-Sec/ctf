import { useQuery } from "@tanstack/react-query";

import { getReadiness, getVersion } from "../api/health";
import { ApiError } from "../api/client";

/**
 * The only page in spec 001: proof that the frontend, the API, Postgres and
 * Redis are all talking to each other. Specs 002+ replace it with the real
 * landing experience.
 */
export default function StatusPage() {
  const version = useQuery({ queryKey: ["version"], queryFn: getVersion });
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: getReadiness });

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-8 p-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">CTF Platform</h1>
        <p className="mt-2 text-muted">
          The dungeon is still being dug. This page exists to prove the walls stand up.
        </p>
      </header>

      <section
        aria-labelledby="build-heading"
        className="rounded-lg border border-stone bg-white/60 p-6"
      >
        <h2 id="build-heading" className="text-sm font-semibold uppercase tracking-wide text-muted">
          Build
        </h2>
        {version.isPending && <p className="mt-3">Loading…</p>}
        {version.isError && <ErrorLine error={version.error} />}
        {version.data && (
          <dl className="mt-3 grid grid-cols-2 gap-2">
            <dt className="text-muted">Version</dt>
            <dd data-testid="version">{version.data.version}</dd>
            <dt className="text-muted">Environment</dt>
            <dd data-testid="environment">{version.data.environment}</dd>
          </dl>
        )}
      </section>

      <section
        aria-labelledby="dependencies-heading"
        className="rounded-lg border border-stone bg-white/60 p-6"
      >
        <h2
          id="dependencies-heading"
          className="text-sm font-semibold uppercase tracking-wide text-muted"
        >
          Dependencies
        </h2>
        {readiness.isPending && <p className="mt-3">Loading…</p>}
        {readiness.isError && <ErrorLine error={readiness.error} />}
        {readiness.data && (
          <dl className="mt-3 grid grid-cols-2 gap-2">
            <dt className="text-muted">PostgreSQL</dt>
            <dd data-testid="postgres">{readiness.data.postgres}</dd>
            <dt className="text-muted">Redis</dt>
            <dd data-testid="redis">{readiness.data.redis}</dd>
          </dl>
        )}
      </section>
    </main>
  );
}

function ErrorLine({ error }: { error: unknown }) {
  // Branch on the stable code, never the prose message.
  const code = error instanceof ApiError ? error.code : "unreachable";
  return (
    <p className="mt-3 text-torch" role="alert" data-testid="error">
      Could not reach the API ({code}).
    </p>
  );
}
