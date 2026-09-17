import { useCallback, useState } from "react";

/**
 * The selection behind `ContentBulkBar` (spec 058 §2).
 *
 * Shared rather than written three times because the awkward part is the same
 * everywhere: a filter that hides a selected row must not quietly widen what a
 * bulk action does. `visible` is intersected on read, so "delete 4 selected"
 * deletes the four you can see.
 */
export function useSelection() {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = useCallback((id: string, on: boolean) => {
    setSelected((was) => {
      const next = new Set(was);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  const visible = useCallback(
    (ids: string[]) => ids.filter((id) => selected.has(id)),
    [selected],
  );

  return { selected, toggle, clear, visible };
}
