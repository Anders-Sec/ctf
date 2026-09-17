import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  LOOT_RARITY_BORDER,
  LOOT_RARITY_CLASS,
  boxLabel,
  equipTitle,
  getBoxes,
  getTitles,
  openBox,
  type HeldTitle,
  type LootBox,
  type Opened,
} from "../api/loot";
import ErrorMessage from "./ErrorMessage";

/**
 * Loot: the boxes waiting, and the titles already out of them (spec 038).
 *
 * Boxes are opened by hand rather than resolving on award, because the opening
 * is the only ceremony loot has. Phase 3 owns what that looks like; this is the
 * plain version.
 *
 * One title is worn at a time and shows beside the player's name on the
 * scoreboard, which is the whole reason a cosmetic title is worth anything.
 */
export default function LootSection() {
  const queryClient = useQueryClient();
  const [reveal, setReveal] = useState<Opened | null>(null);

  const boxes = useQuery({ queryKey: ["loot-boxes"], queryFn: getBoxes });
  const titles = useQuery({ queryKey: ["loot-titles"], queryFn: getTitles });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["loot-boxes"] });
    queryClient.invalidateQueries({ queryKey: ["loot-titles"] });
    queryClient.invalidateQueries({ queryKey: ["scoreboard"] });
  };

  const open = useMutation({
    mutationFn: (id: string) => openBox(id),
    onSuccess: (opened) => {
      setReveal(opened);
      refresh();
    },
  });
  const equip = useMutation({
    mutationFn: (itemId: string | null) => equipTitle(itemId),
    onSuccess: refresh,
  });

  // Defensive, like the other sheet sections: a partial response must not take
  // the whole page down with it.
  const waiting: LootBox[] = Array.isArray(boxes.data) ? boxes.data : [];
  const held: HeldTitle[] = Array.isArray(titles.data) ? titles.data : [];

  if (boxes.isPending && titles.isPending) return null;
  if (waiting.length === 0 && held.length === 0) return null;

  return (
    <section className="mt-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Loot</h2>
        <span className="text-sm text-content-muted tabular-nums">
          {held.length} {held.length === 1 ? "title" : "titles"}
          {waiting.length > 0 && ` · ${waiting.length} unopened`}
        </span>
      </div>

      <ErrorMessage error={open.error ?? equip.error} />

      {reveal && (
        <div
          role="status"
          className={`mt-3 rounded border-2 bg-surface-raised px-4 py-3 ${LOOT_RARITY_BORDER[reveal.rarity]}`}
        >
          <p className="text-xs uppercase tracking-wide text-content-muted">
            {reveal.rarity} {boxLabel(reveal.box_type)} Box
          </p>
          <p className={`mt-1 text-xl font-semibold ${LOOT_RARITY_CLASS[reveal.rarity]}`}>
            {reveal.title}
          </p>
          {reveal.generated && (
            // Worth marking: this one was written for them, not picked off a list.
            <p className="mt-1 text-xs text-content-muted">Written for you, just now.</p>
          )}
          <button
            onClick={() => setReveal(null)}
            className="mt-2 text-xs underline text-content-muted hover:text-content"
          >
            Dismiss
          </button>
        </div>
      )}

      {waiting.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-semibold uppercase tracking-wide text-content-muted">
            Unopened
          </h3>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {waiting.map((box) => (
              <li
                key={box.id}
                className={`flex items-center justify-between gap-3 rounded border px-3 py-2 ${LOOT_RARITY_BORDER[box.rarity]}`}
              >
                <span className="min-w-0">
                  <p
                    className={`text-sm font-semibold capitalize ${LOOT_RARITY_CLASS[box.rarity]}`}
                  >
                    {box.rarity} {boxLabel(box.box_type)} Box
                  </p>
                  <p className="truncate text-xs text-content-muted">
                    {box.achievement_name}
                  </p>
                </span>
                <button
                  onClick={() => open.mutate(box.id)}
                  disabled={open.isPending}
                  className="shrink-0 rounded bg-content px-3 py-1.5 text-sm text-surface disabled:opacity-50"
                >
                  {open.isPending ? "Opening…" : "Open"}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {held.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-semibold uppercase tracking-wide text-content-muted">
            Titles
          </h3>
          <ul className="mt-2 space-y-1">
            {held.map((title) => (
              <li
                key={title.item_id}
                className="flex items-center justify-between gap-3 rounded border border-border bg-surface-raised px-3 py-2"
              >
                <span className="min-w-0">
                  <p className={`text-sm font-semibold ${LOOT_RARITY_CLASS[title.rarity]}`}>
                    {title.title}
                  </p>
                  <p className="text-xs text-content-muted">
                    <span className="capitalize">{title.rarity}</span> ·{" "}
                    {boxLabel(title.box_type)}
                    {title.generated && " · one of a kind"}
                  </p>
                </span>
                <button
                  onClick={() =>
                    equip.mutate(title.equipped ? null : title.item_id)
                  }
                  disabled={equip.isPending}
                  className="shrink-0 text-sm hover:underline disabled:opacity-50"
                >
                  {title.equipped ? "Take off" : "Wear"}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-content-muted">
            The title you wear shows beside your name on the scoreboard.
          </p>
        </>
      )}
    </section>
  );
}
