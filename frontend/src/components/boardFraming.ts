/**
 * Top ten, then a break, then you (spec 059 §4).
 *
 * The same framing on both boards, written once because the awkward cases are
 * identical and all of them are easy to get subtly wrong:
 *
 * - Already in the top ten? No break and no repeated row — a duplicate row for
 *   somebody at rank 4 would read as two entries.
 * - Not on the board at all (signed out, or unranked)? The top ten and nothing
 *   else, rather than an empty space where your row would be.
 * - Searching? The framing steps aside entirely and matches show their real
 *   ranks, because "rank 34 of 47" is the useful answer to a search and "no
 *   results in the top ten" is not.
 */

export const TOP_N = 10;

export interface Framed<T> {
  /** The rows to render, in order. */
  rows: T[];
  /** True when a visual break belongs immediately before the last row. */
  breakBeforeLast: boolean;
}

export function frameBoard<T>(
  all: T[],
  {
    isMine,
    showAll,
    searching,
  }: { isMine: (row: T) => boolean; showAll: boolean; searching: boolean },
): Framed<T> {
  if (searching || showAll) {
    // Real ranks, whole list. The rank is already on each row, so nothing has
    // to be recomputed for this view.
    return { rows: all, breakBeforeLast: false };
  }

  const top = all.slice(0, TOP_N);
  const mineIndex = all.findIndex(isMine);

  if (mineIndex === -1 || mineIndex < TOP_N) {
    return { rows: top, breakBeforeLast: false };
  }

  const mine = all[mineIndex];
  // `mine` cannot be undefined here — mineIndex came from findIndex — but the
  // compiler does not know that under noUncheckedIndexedAccess.
  return { rows: mine ? [...top, mine] : top, breakBeforeLast: Boolean(mine) };
}
