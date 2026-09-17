import { useSession } from "../auth/session";
import ResetPlayDataPanel from "../components/ResetPlayDataPanel";
import SampleDataPanel from "../components/SampleDataPanel";

/**
 * Data & Reset (spec 049 §3).
 *
 * Split out of the operations page, where the most destructive control in the
 * platform sat underneath the broken-challenge queue — somewhere you scroll
 * past while triaging. Setup tools belong with setup tools, and the reset
 * already carries its own confirmation, so this is separation rather than
 * added friction.
 */
export default function AdminDataPage() {
  const { me } = useSession();
  const canWrite = me?.capabilities.administer ?? false;

  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Data &amp; Reset</h1>
      <p className="mt-2 text-content-muted">
        Seeding a rehearsal and clearing what it produced. Used before the doors open, not
        during.
      </p>

      {!canWrite && (
        <p className="mt-4 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
          Read-only — only admins can seed or clear data.
        </p>
      )}

      <SampleDataPanel />
      <ResetPlayDataPanel canWrite={canWrite} />
    </main>
  );
}
