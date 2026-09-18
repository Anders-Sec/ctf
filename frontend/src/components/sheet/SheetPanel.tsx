import { useMemo, useState } from "react";

/**
 * The blocks a character sheet is made of (spec 060 §5).
 *
 * The single idea behind all of this is **fixed height**. A printed 5e sheet has
 * the same boxes in the same places whoever is holding it, and that is what makes
 * it readable at a glance; a page whose blocks grow as you collect things is a
 * feed. So every panel declares its height, every list scrolls inside one, and
 * nothing on the page moves when a box is opened or a skill is discovered.
 *
 * It also means the empty state is load-bearing rather than apologetic. On day
 * one a player has no loot, no achievements and no skills — and four full-height
 * panels showing them everything there is to unlock is the point (§9.2).
 */

export function SheetPanel({
  title,
  summary,
  className = "",
  children,
}: {
  title: string;
  /** Right-aligned in the header: `12 of 45 discovered`, `2 to open`. */
  summary?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`flex flex-col overflow-hidden rounded-lg border border-border-strong bg-surface-raised ${className}`}
    >
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-border px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide">{title}</h2>
        {summary && <span className="text-xs text-content-muted tabular-nums">{summary}</span>}
      </div>
      <div className="flex min-h-0 flex-1 flex-col p-3">{children}</div>
    </section>
  );
}

export interface ListFilter {
  id: string;
  label: string;
  options: { value: string; label: string }[];
}

/**
 * Search, filters, and a scroll region that does not change size.
 *
 * Three panels want exactly this chrome, so it is written once — the lesson from
 * spec 058, where four near-identical admin pages meant four places to fix a
 * scroll bug. Deliberately *not* `ContentPage`: that one is an admin CRUD shell
 * with a selection column and bulk actions, none of which belongs on a player's
 * own sheet.
 *
 * The caller supplies the predicate, because what "matches" means differs every
 * time — a skill matches on a name it may not have yet, an achievement only if
 * it has been earned.
 */
export function FilteredList<T>({
  items,
  listLabel,
  searchLabel,
  searchHint,
  filters = [],
  match,
  rowKey,
  renderRow,
  empty,
  noMatches = "Nothing matches that.",
}: {
  items: T[];
  /** Names the scroll region. A sheet has four of these; without names a
   *  screen reader meets four anonymous lists. */
  listLabel: string;
  searchLabel: string;
  /** Shown under the search box — e.g. why an unearned row cannot be found. */
  searchHint?: string;
  filters?: ListFilter[];
  match: (item: T, state: { term: string; values: Record<string, string> }) => boolean;
  rowKey: (item: T) => string;
  renderRow: (item: T) => React.ReactNode;
  /** When the player has none of these at all — a day-one state, not an error. */
  empty: React.ReactNode;
  noMatches?: string;
}) {
  const [term, setTerm] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});

  const shown = useMemo(
    () => items.filter((item) => match(item, { term: term.trim().toLowerCase(), values })),
    // `match` is redefined on every render by every caller, so depending on it
    // would defeat the memo entirely. The inputs that actually change the result
    // are the three below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, term, values],
  );

  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Search"
          aria-label={searchLabel}
          className="min-w-24 flex-1 rounded border border-border-strong bg-surface px-2 py-1 text-sm"
        />
        {filters.map((filter) => (
          <select
            key={filter.id}
            value={values[filter.id] ?? ""}
            onChange={(event) =>
              setValues((was) => ({ ...was, [filter.id]: event.target.value }))
            }
            aria-label={filter.label}
            className="rounded border border-border-strong bg-surface px-2 py-1 text-sm"
          >
            <option value="">{filter.label}</option>
            {filter.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ))}
      </div>
      {searchHint && <p className="mt-1 shrink-0 text-xs text-content-faint">{searchHint}</p>}

      {/* The one element that scrolls. Its parent is `min-h-0 flex-1`, which is
          what lets it take the leftover height instead of growing the panel. */}
      <ul
        aria-label={listLabel}
        className="mt-2 min-h-0 flex-1 divide-y divide-border overflow-y-auto"
      >
        {items.length === 0 ? (
          <li className="px-1 py-3 text-sm text-content-muted">{empty}</li>
        ) : shown.length === 0 ? (
          <li className="px-1 py-3 text-sm text-content-muted">{noMatches}</li>
        ) : (
          shown.map((item) => <li key={rowKey(item)}>{renderRow(item)}</li>)
        )}
      </ul>
    </>
  );
}
