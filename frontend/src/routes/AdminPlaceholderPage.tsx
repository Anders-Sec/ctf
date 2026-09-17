import { Link } from "react-router-dom";

/**
 * A page the admin navigation lists (spec 049) but whose spec has not been
 * built yet.
 *
 * Listing the whole information architecture up front is the point of 049 —
 * later specs land in a settled structure rather than renegotiating it one page
 * at a time. The cost is six sidebar entries that would otherwise navigate
 * nowhere, and a placeholder that says which spec owns the page is a better
 * answer to a click than a silent bounce to the dashboard.
 */
export default function AdminPlaceholderPage({
  title,
  spec,
  summary,
}: {
  title: string;
  /** e.g. "050 — Event Metrics". */
  spec: string;
  summary: string;
}) {
  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-content-muted">{summary}</p>

      <div className="mt-6 rounded border border-dashed border-border bg-surface-raised p-4 text-sm">
        <p>
          <strong>Not built yet.</strong> Specified in <code>specs/{spec}</code>, and listed here
          so the admin area&rsquo;s shape is settled before the pages arrive.
        </p>
        <p className="mt-2 text-content-muted">
          <Link to="/admin" className="text-accent-strong underline">
            Back to the dashboard
          </Link>
        </p>
      </div>
    </main>
  );
}
