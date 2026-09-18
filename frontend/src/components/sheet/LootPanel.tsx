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
  type LootRarity,
  type Opened,
} from "../../api/loot";
import ErrorMessage from "../ErrorMessage";
import { FilteredList, SheetPanel } from "./SheetPanel";

/**
 * Loot: the boxes waiting, and the titles already out of them (specs 038, 060).
 *
 * Boxes are opened by hand rather than resolving on award, because the opening
 * is the only ceremony loot has. The shelf is a **fixed-height horizontal
 * scroll** — an item shop you walk along — so opening one does not resize the
 * panel and the page does not move under the player mid-ceremony. With nothing
 * on it, it says so at exactly the same height.
 *
 * One title is worn at a time, and it shows beside the player's name on the
 * scoreboard and at the top of this sheet, which is the whole reason a cosmetic
 * title is worth anything.
 */

/** Best first. Ascending in the model, so this is reversed for display. */
const RARITY_ORDER: LootRarity[] = [
  "celestial",
  "legendary",
  "platinum",
  "gold",
  "silver",
  "bronze",
];

const rarityRank = (rarity: LootRarity) => RARITY_ORDER.indexOf(rarity);

export default function LootPanel() {
  const queryClient = useQueryClient();
  const [reveal, setReveal] = useState<Opened | null>(null);

  const boxes = useQuery({ queryKey: ["loot-boxes"], queryFn: getBoxes });
  const titles = useQuery({ queryKey: ["loot-titles"], queryFn: getTitles });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["loot-boxes"] });
    queryClient.invalidateQueries({ queryKey: ["loot-titles"] });
    queryClient.invalidateQueries({ queryKey: ["scoreboard"] });
    // The worn title is on the sheet's identity block now (spec 060 §6).
    queryClient.invalidateQueries({ queryKey: ["character", "me"] });
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

  // Defensive: a partial response must not take the whole sheet down with it.
  const waiting: LootBox[] = (Array.isArray(boxes.data) ? boxes.data : [])
    .slice()
    .sort((a, b) => rarityRank(a.rarity) - rarityRank(b.rarity));
  const held: HeldTitle[] = Array.isArray(titles.data) ? titles.data : [];

  return (
    <SheetPanel
      title="Loot"
      summary={
        waiting.length > 0
          ? `${waiting.length} to open`
          : `${held.length} ${held.length === 1 ? "title" : "titles"}`
      }
      className="h-[19rem]"
    >
      <ErrorMessage error={open.error ?? equip.error} />

      {/* The shelf. Fixed height whether it holds none or twelve. */}
      <div
        role="group"
        aria-label="Unopened loot boxes"
        className="mb-2 flex h-20 shrink-0 gap-2 overflow-x-auto rounded border border-border bg-surface p-1.5"
      >
        {waiting.length === 0 ? (
          <p className="m-auto text-xs text-content-muted">
            Nothing to open. Boxes arrive with achievements.
          </p>
        ) : (
          waiting.map((box) => (
            <button
              key={box.id}
              type="button"
              onClick={() => open.mutate(box.id)}
              disabled={open.isPending}
              title={box.achievement_name}
              className={`flex w-28 shrink-0 flex-col justify-center rounded border-2 px-2 py-1 text-left disabled:opacity-50 ${LOOT_RARITY_BORDER[box.rarity]}`}
            >
              <span
                className={`text-[10px] uppercase tracking-wide ${LOOT_RARITY_CLASS[box.rarity]}`}
              >
                {box.rarity}
              </span>
              <span className="truncate text-xs font-semibold">{boxLabel(box.box_type)}</span>
              <span className="text-[10px] text-content-muted">
                {open.isPending ? "Opening…" : "Open"}
              </span>
            </button>
          ))
        )}
      </div>

      {reveal && (
        <div
          role="status"
          className={`mb-2 shrink-0 rounded border-2 bg-surface px-3 py-1.5 ${LOOT_RARITY_BORDER[reveal.rarity]}`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <p className={`truncate text-sm font-semibold ${LOOT_RARITY_CLASS[reveal.rarity]}`}>
              {reveal.title}
            </p>
            <button
              type="button"
              onClick={() => setReveal(null)}
              className="shrink-0 text-xs text-content-muted underline"
            >
              Dismiss
            </button>
          </div>
          <p className="text-[11px] text-content-muted">
            {reveal.rarity} {boxLabel(reveal.box_type)} Box
            {/* Worth marking: this one was written for them, not picked off a list. */}
            {reveal.generated && " · written for you, just now"}
          </p>
        </div>
      )}

      <FilteredList
        items={held}
        listLabel="Titles"
        searchLabel="Search titles"
        filters={[
          {
            id: "rarity",
            label: "Any rarity",
            options: RARITY_ORDER.map((rarity) => ({ value: rarity, label: rarity })),
          },
        ]}
        match={(title, { term, values }) => {
          if (values.rarity && title.rarity !== values.rarity) return false;
          if (term) return title.title.toLowerCase().includes(term);
          return true;
        }}
        rowKey={(title) => title.item_id}
        empty="No titles yet. Open a box to find one."
        renderRow={(title) => (
          <div className="flex items-center justify-between gap-2 px-1 py-1.5 text-sm">
            <span className="min-w-0 truncate">
              <span className={`font-medium ${LOOT_RARITY_CLASS[title.rarity]}`}>
                {title.title}
              </span>
              {title.generated && (
                <span className="ml-1 text-[10px] text-content-faint">one of a kind</span>
              )}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {title.equipped && (
                <span className="text-[10px] uppercase tracking-wide text-accent-strong">
                  worn
                </span>
              )}
              <button
                type="button"
                onClick={() => equip.mutate(title.equipped ? null : title.item_id)}
                disabled={equip.isPending}
                className="text-xs underline disabled:opacity-50"
              >
                {title.equipped ? "Take off" : "Wear"}
              </button>
            </span>
          </div>
        )}
      />
    </SheetPanel>
  );
}
