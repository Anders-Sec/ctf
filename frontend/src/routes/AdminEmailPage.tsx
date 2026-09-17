import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getMailStatus,
  listDeliveries,
  sendTestEmail,
  type DeliveryFilters,
  type EmailStatus,
} from "../api/adminEmail";
import { useSession } from "../auth/session";
import DeliveryTable from "../components/DeliveryTable";
import ErrorMessage from "../components/ErrorMessage";
import Spinner from "../components/Spinner";

/**
 * Email Delivery (spec 055 §4).
 *
 * Exists because `mail.py` has always promised that a failed send is "logged
 * with the request id so an admin can find it mid-event" — and the log went to
 * the pod's stdout, unreachable from here, recording the exception type but
 * never the recipient.
 */
export default function AdminEmailPage() {
  const { me } = useSession();
  const canSend = me?.capabilities.administer ?? false;
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<DeliveryFilters>({ limit: 200 });

  const status = useQuery({
    queryKey: ["admin", "email", "status"],
    queryFn: getMailStatus,
    refetchInterval: 30_000,
  });
  const deliveries = useQuery({
    queryKey: ["admin", "email", "deliveries", filters],
    queryFn: () => listDeliveries(filters),
  });

  const test = useMutation({
    mutationFn: sendTestEmail,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "email"] });
    },
  });

  return (
    <main className="p-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Email Delivery</h1>
        <p className="mt-2 text-sm text-content-muted">
          Every outbound message and what became of it. &ldquo;Accepted by relay&rdquo; is as much
          as SMTP will confirm — it is not proof of arrival.
        </p>
      </header>

      <ErrorMessage error={status.error ?? deliveries.error ?? test.error} />

      {status.data && (
        <section className="mt-6">
          {!status.data.configured && (
            <p className="rounded border border-warning bg-warning/10 px-3 py-2 text-sm">
              <strong>No SMTP configured.</strong> Guests cannot sign in at all until it is.
            </p>
          )}

          {status.data.degraded && (
            // The failure nobody notices until it has been true for an hour.
            <p
              role="alert"
              className="mt-2 rounded border border-danger bg-danger/10 px-3 py-2 text-sm"
            >
              <strong>Most recent sends are failing.</strong> Guest sign-in is probably broken
              right now.
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
            <Stat label={`Sent · last ${status.data.window_minutes}m`} value={status.data.sent} />
            <Stat label="Failed" value={status.data.failed} tone={status.data.failed > 0} />
            <Stat
              label="Failure rate"
              value={`${Math.round(status.data.failure_rate * 100)}%`}
              tone={status.data.degraded}
            />

            {canSend && (
              <button
                type="button"
                disabled={test.isPending || !status.data.configured}
                onClick={() => test.mutate()}
                className="ml-auto rounded border border-border px-3 py-1 hover:bg-surface-sunken disabled:opacity-40"
              >
                Send a test to myself
              </button>
            )}
          </div>

          {test.isSuccess && (
            <p className="mt-2 text-sm text-success">{test.data.message}</p>
          )}
        </section>
      )}

      <div className="mt-8 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-content-muted">Result</span>
          <select
            value={filters.status ?? ""}
            onChange={(event) =>
              setFilters((was) => ({
                ...was,
                status: (event.target.value || undefined) as EmailStatus | undefined,
              }))
            }
            className="rounded border border-border-strong bg-surface-raised px-2 py-1"
          >
            <option value="">Any</option>
            <option value="sent">Accepted</option>
            <option value="failed">Failed</option>
            <option value="not_configured">Not configured</option>
          </select>
        </label>

        <label className="flex-1 text-sm">
          <span className="mb-1 block text-content-muted">Recipient</span>
          <input
            value={filters.search ?? ""}
            onChange={(event) =>
              setFilters((was) => ({ ...was, search: event.target.value || undefined }))
            }
            placeholder="part of an address"
            className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1"
          />
        </label>
      </div>

      {!deliveries.data ? (
        <Spinner />
      ) : (
        <>
          <p className="mt-4 text-sm text-content-muted">
            {deliveries.data.total} {deliveries.data.total === 1 ? "message" : "messages"}
          </p>
          <DeliveryTable rows={deliveries.data.entries} />
        </>
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: boolean;
}) {
  return (
    <span>
      <span className="text-content-muted">{label} </span>
      <span className={`font-semibold tabular-nums ${tone ? "text-danger" : ""}`}>{value}</span>
    </span>
  );
}
