import { useRef, useState } from "react";

import { useDialogFocus } from "../../hooks/useDialogFocus";

/**
 * The shape every Content page shares (spec 058 §2).
 *
 * Modelled on the Challenges page, which got this treatment at 242 rows in spec
 * 041: a New button at the top, search and filters beside it, a grouped
 * collapsible list, and a drawer over the right-hand side.
 *
 * **Challenges keeps its own table**, which is a deviation from §2 — recorded in
 * §10, along with why.
 */

export interface FilterSpec {
  id: string;
  label: string;
  options: { value: string; label: string }[];
}

/** A clickable count — spec 041's problem filters, made visible (§6). */
export interface ProblemCount {
  id: string;
  label: string;
  count: number;
}

export function ContentPage({
  title,
  description,
  newLabel,
  onNew,
  canWrite,
  readOnlyNote,
  children,
  drawer,
  bulkBar,
  filterBar,
}: {
  title: string;
  description: React.ReactNode;
  newLabel: string;
  onNew: () => void;
  canWrite: boolean;
  readOnlyNote: string;
  children: React.ReactNode;
  drawer?: React.ReactNode;
  bulkBar?: React.ReactNode;
  filterBar: React.ReactNode;
}) {
  return (
    <main className="p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-content-muted">{description}</p>
        </div>
        {canWrite && (
          <button
            type="button"
            onClick={onNew}
            className="shrink-0 rounded bg-accent-strong px-3 py-1.5 text-sm font-medium text-accent-content"
          >
            + {newLabel}
          </button>
        )}
      </header>

      {!canWrite && (
        <p className="mt-4 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
          {readOnlyNote}
        </p>
      )}

      {filterBar}
      {bulkBar}
      {children}
      {drawer}
    </main>
  );
}

/** Search plus the `<select>` filters a page declares, plus its problem counts. */
export function ContentFilterBar({
  searchLabel,
  search,
  onSearchChange,
  filters,
  values,
  onFilterChange,
  problems,
  activeProblem,
  onProblemChange,
  shown,
  total,
}: {
  searchLabel: string;
  search: string;
  onSearchChange: (value: string) => void;
  filters: FilterSpec[];
  values: Record<string, string>;
  onFilterChange: (id: string, value: string) => void;
  problems?: ProblemCount[];
  activeProblem?: string;
  onProblemChange?: (id: string) => void;
  shown: number;
  total: number;
}) {
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block text-content-muted">Search</span>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            aria-label={searchLabel}
            className="w-full rounded border border-border-strong bg-surface-raised px-2 py-1.5"
          />
        </label>

        {filters.map((filter) => (
          <label key={filter.id} className="text-sm">
            <span className="mb-1 block text-content-muted">{filter.label}</span>
            <select
              value={values[filter.id] ?? ""}
              onChange={(event) => onFilterChange(filter.id, event.target.value)}
              aria-label={filter.label}
              className="rounded border border-border-strong bg-surface-raised px-2 py-1.5"
            >
              <option value="">Any</option>
              {filter.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="text-content-muted tabular-nums">
          {shown === total ? `${total} shown` : `${shown} of ${total} shown`}
        </span>
        {/* Visible rather than folded into a dropdown: the working list for an
            afternoon is "what is still wrong", and it should not need finding. */}
        {problems
          ?.filter((problem) => problem.count > 0)
          .map((problem) => (
            <button
              key={problem.id}
              type="button"
              aria-pressed={activeProblem === problem.id}
              onClick={() => onProblemChange?.(activeProblem === problem.id ? "" : problem.id)}
              className={`rounded px-1.5 py-0.5 tabular-nums underline ${
                activeProblem === problem.id
                  ? "bg-warning/20 font-medium text-warning"
                  : "text-content-muted"
              }`}
            >
              {problem.count} {problem.label}
            </button>
          ))}
      </p>
    </div>
  );
}

export interface ContentGroup {
  id: string;
  heading: string;
  /** What is inside, so a shut group still says what it holds (§6). */
  summary: string;
  /** A Tailwind text-colour class for the group's flag. Decoration only. */
  accent?: string;
  rows: React.ReactNode;
  count: number;
}

/**
 * Collapsible groups, with the open set remembered per admin.
 *
 * This is what makes 242 rows and 110 rows use the same page: at any moment you
 * are looking at one zone or one rarity, not at everything.
 */
export function ContentGroupList({
  groups,
  storageKey,
  empty,
}: {
  groups: ContentGroup[];
  storageKey: string;
  empty: string;
}) {
  const [closed, setClosed] = useState<Set<string>>(() => readClosed(storageKey));

  const toggle = (id: string) => {
    setClosed((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      writeClosed(storageKey, next);
      return next;
    });
  };

  const populated = groups.filter((group) => group.count > 0);
  if (populated.length === 0) {
    return <p className="mt-6 text-sm text-content-muted">{empty}</p>;
  }

  return (
    <div className="mt-4">
      {populated.map((group) => {
        const open = !closed.has(group.id);
        return (
          <section key={group.id} className="mb-3">
            {/* Sticky, so the zone or rarity you are inside stays named (§6). */}
            <h2 className="sticky top-0 z-10 bg-surface">
              <button
                type="button"
                onClick={() => toggle(group.id)}
                aria-expanded={open}
                className="flex w-full items-baseline gap-2 border-b border-border-strong px-1 py-1.5 text-left"
              >
                <span aria-hidden className="w-3 shrink-0 text-content-muted">
                  {open ? "▾" : "▸"}
                </span>
                <span className={`font-semibold ${group.accent ?? ""}`}>{group.heading}</span>
                <span className="text-xs font-normal text-content-muted">{group.summary}</span>
              </button>
            </h2>
            {open && group.rows}
          </section>
        );
      })}
    </div>
  );
}

/** Per-admin convenience, so a wrapped read or write cannot break the page. */
function readClosed(storageKey: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(`${storageKey}.closed`);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeClosed(storageKey: string, closed: Set<string>): void {
  try {
    window.localStorage.setItem(`${storageKey}.closed`, JSON.stringify([...closed]));
  } catch {
    // A collapse we cannot remember still collapses.
  }
}

/**
 * The editor, over the right-hand side.
 *
 * A drawer rather than an inline expander for spec 041's reason: the list does
 * not move, so working through it does not mean re-finding your place after
 * every edit — and it is what makes a selection column usable at all.
 */
export function ContentDrawer({
  title,
  subtitle,
  dirty,
  onClose,
  onDelete,
  deleteTitle,
  deleteDisabled,
  children,
  footer,
}: {
  title: string;
  subtitle?: React.ReactNode;
  dirty: boolean;
  onClose: () => void;
  onDelete?: () => void;
  deleteTitle?: string;
  deleteDisabled?: boolean;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const [confirming, setConfirming] = useState(false);
  const close = () => {
    // Losing an edit silently is worse than one extra click.
    if (dirty) {
      setConfirming(true);
      return;
    }
    onClose();
  };

  // `close` checks `dirty`, which changes as the admin types. The hook holds
  // the callback in a ref and calls the current one, so this keeps the property
  // the old hand-rolled version needed a missing dependency array to get: the
  // handler never discards an edit because it closed over a stale `dirty`.
  const panel = useRef<HTMLElement>(null);
  useDialogFocus(panel, { onClose: close });

  return (
    <>
      <div
        className="fixed inset-0 z-30 bg-content/20"
        onClick={close}
        aria-hidden
      />
      <aside
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${title}`}
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col overflow-y-auto border-l border-border-strong bg-surface-overlay shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-content-muted">{subtitle}</p>}
          </div>
          <span className="flex shrink-0 items-center gap-3 text-sm">
            {dirty && <span className="text-xs text-warning">unsaved</span>}
            {/* Delete in the header, not behind a scroll — spec 041 found the
                distance was the problem, not a missing second confirmation. */}
            {onDelete && (
              <button
                type="button"
                onClick={onDelete}
                disabled={deleteDisabled}
                title={deleteTitle}
                className="text-danger underline disabled:no-underline disabled:opacity-40"
              >
                Delete
              </button>
            )}
            <button
              type="button"
              onClick={close}
              aria-label="Close editor"
              className="text-xl leading-none"
            >
              ×
            </button>
          </span>
        </div>

        {confirming && (
          <p className="flex flex-wrap items-center gap-3 border-b border-warning bg-warning/10 px-5 py-2 text-sm">
            Close without saving?
            <button type="button" onClick={onClose} className="underline">
              Discard
            </button>
            <button type="button" onClick={() => setConfirming(false)} className="underline">
              Keep editing
            </button>
          </p>
        )}

        <div className="flex flex-1 flex-col gap-4 px-5 py-4">{children}</div>
        <div className="sticky bottom-0 border-t border-border bg-surface-overlay px-5 py-3">
          {footer}
        </div>
      </aside>
    </>
  );
}

/** Appears only with a selection. The operations are declared per page. */
export function ContentBulkBar({
  count,
  children,
  onClear,
  result,
}: {
  count: number;
  children: React.ReactNode;
  onClear: () => void;
  /** Per-item outcome of the last operation (§4). */
  result?: { changed: number; refused: Record<string, string> } | undefined;
}) {
  if (count === 0 && !result) return null;

  return (
    <div className="mt-4">
      {count > 0 && (
        <div
          role="group"
          aria-label="Bulk actions"
          className="flex flex-wrap items-center gap-3 rounded border border-accent-strong bg-accent/10 px-3 py-2 text-sm"
        >
          <span className="font-medium tabular-nums">{count} selected</span>
          {children}
          <button type="button" onClick={onClear} className="ml-auto text-content-muted underline">
            Clear
          </button>
        </div>
      )}
      {result && (
        // A bulk that skipped rows has to say which and why, or it reads as a
        // success that quietly did less than asked.
        <p
          role="status"
          className="mt-2 rounded border border-border bg-surface-raised px-3 py-2 text-sm"
        >
          {result.changed} changed
          {Object.keys(result.refused).length > 0 && (
            <>
              , {Object.keys(result.refused).length} refused:{" "}
              <span className="text-warning">
                {[...new Set(Object.values(result.refused))].join("; ")}
              </span>
            </>
          )}
        </p>
      )}
    </div>
  );
}

/** A labelled field, so every drawer lays out the same way. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-content-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-content-faint">{hint}</span>}
    </label>
  );
}

/** A checkbox in the selection column, labelled for a screen reader. */
export function SelectBox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <input
      type="checkbox"
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
      aria-label={`Select ${label}`}
      className="h-3.5 w-3.5 align-middle"
    />
  );
}

export const inputClass =
  "w-full rounded border border-border-strong bg-surface-raised px-2 py-1.5";

/** A row's warning pip: always text, never colour alone (§6). */
export function RowFlag({ tone, children }: { tone: "warning" | "muted"; children: string }) {
  return (
    <span
      className={`rounded-full border px-1.5 py-0.5 text-[11px] leading-none ${
        tone === "warning" ? "border-warning text-warning" : "border-border text-content-muted"
      }`}
    >
      {children}
    </span>
  );
}
