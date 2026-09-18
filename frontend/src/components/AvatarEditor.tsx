import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  getMyAvatar,
  listAccessories,
  resetMyAvatar,
  saveMyAvatar,
  unlockReason,
  type Accessory,
  type AccessorySlot,
  type AvatarLayer,
  type AvatarSource,
} from "../api/avatar";
import { avatarUrl } from "../api/auth";
import { useSession } from "../auth/session";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";
import { RARITY_TEXT } from "./classRarity";

/**
 * Putting a hat on straight (spec 073 §5).
 *
 * Accessories carry authored anchors that are right for most people, so this is
 * **correction, not composition**: pick a thing, then nudge it. Drag to move,
 * two sliders for size and angle, and that is the whole editor.
 *
 * It saves the *transform*, never a flattened image. That matters more than it
 * sounds: unlocking a new hat next Tuesday must not lose the fit of the
 * glasses, and the same recipe has to render at 40px in a roster and at 512px
 * here.
 *
 * The preview is drawn here rather than fetched, because dragging against an
 * HTTP round-trip is not dragging. The server's render is the authoritative
 * one — this only has to be close enough to aim with.
 */
const SLOTS: { slot: AccessorySlot; label: string }[] = [
  { slot: "head", label: "Head" },
  { slot: "eyes", label: "Eyes" },
  { slot: "shoulders", label: "Shoulders" },
  { slot: "frame", label: "Frame" },
];

const PREVIEW = 280;

export default function AvatarEditor() {
  const { me, refresh } = useSession();
  const queryClient = useQueryClient();

  const mine = useQuery({ queryKey: ["avatar", "me"], queryFn: getMyAvatar });
  const catalogue = useQuery({ queryKey: ["avatar", "accessories"], queryFn: listAccessories });

  const [layers, setLayers] = useState<AvatarLayer[] | null>(null);
  const [source, setSource] = useState<AvatarSource>("sigil");
  const [selected, setSelected] = useState<string | null>(null);
  // Bumped on save: every <img> in the app points at the same avatar URL,
  // and nothing else would tell them the bytes behind it changed.
  const [cacheBust, setCacheBust] = useState(() => Date.now());

  // Seeded once from the server, then owned here until saved — otherwise a
  // background refetch would yank a half-finished adjustment away.
  useEffect(() => {
    if (mine.data && layers === null) {
      setLayers(mine.data.layers);
      setSource(mine.data.source);
      setSelected(mine.data.layers[0]?.accessory ?? null);
    }
  }, [mine.data, layers]);

  const afterSave = async () => {
    await refresh();
    await queryClient.invalidateQueries({ queryKey: ["avatar"] });
    setCacheBust(Date.now());
  };

  const save = useMutation({
    mutationFn: () => saveMyAvatar({ source, layers: layers ?? [] }),
    onSuccess: async (updated) => {
      setLayers(updated.layers);
      setSource(updated.source);
      await afterSave();
    },
  });

  const reset = useMutation({
    mutationFn: resetMyAvatar,
    onSuccess: async (updated) => {
      setLayers(updated.layers);
      setSource(updated.source);
      setSelected(null);
      await afterSave();
    },
  });


  if (mine.isPending || catalogue.isPending || layers === null || !me) {
    return <Spinner label="Fetching your likeness…" />;
  }
  if (mine.isError) return <ErrorMessage error={mine.error} />;

  const accessories = catalogue.data ?? [];
  const bySlug = new Map(accessories.map((item) => [item.slug, item]));
  const active = selected ? layers.find((layer) => layer.accessory === selected) : undefined;
  const activeAccessory = selected ? bySlug.get(selected) : undefined;

  const equip = (accessory: Accessory) => {
    setLayers((current) => {
      const rest = (current ?? []).filter(
        (layer) => bySlug.get(layer.accessory)?.slot !== accessory.slot,
      );
      return [
        ...rest,
        {
          accessory: accessory.slug,
          x: accessory.anchor_x,
          y: accessory.anchor_y,
          scale: accessory.anchor_scale,
          rotation: accessory.anchor_rotation,
        },
      ];
    });
    setSelected(accessory.slug);
  };

  const unequip = (slug: string) => {
    setLayers((current) => (current ?? []).filter((layer) => layer.accessory !== slug));
    if (selected === slug) setSelected(null);
  };

  const adjust = (patch: Partial<AvatarLayer>) => {
    if (!selected) return;
    setLayers((current) =>
      (current ?? []).map((layer) =>
        layer.accessory === selected ? { ...layer, ...patch } : layer,
      ),
    );
  };

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <section className="lg:w-[300px]">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Preview
        </h3>
        <Preview
          userId={me.user.id}
          cacheBust={cacheBust}
          layers={layers}
          bySlug={bySlug}
          selected={selected}
          onMove={(x, y) => adjust({ x, y })}
        />

        {mine.data && (
          <p className="mt-2 text-xs text-content-muted">{mine.data.description}</p>
        )}

        {mine.data?.has_photo && (
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={source === "entra"}
              onChange={(event) => setSource(event.target.checked ? "entra" : "sigil")}
            />
            Use my work photo instead of the crest
          </label>
        )}

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="rounded bg-content px-4 py-2 text-sm text-surface disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="rounded border border-border px-4 py-2 text-sm disabled:opacity-50"
          >
            Start over
          </button>
        </div>
        <ErrorMessage error={save.error ?? reset.error} />
      </section>

      <section className="min-w-0 flex-1">
        {active && activeAccessory ? (
          <Adjusters layer={active} name={activeAccessory.name} onChange={adjust} />
        ) : (
          <p className="rounded border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
            Pick something below, then drag it on the preview to place it.
          </p>
        )}

        <div className="mt-4 flex flex-col gap-4">
          {SLOTS.map(({ slot, label }) => {
            const inSlot = accessories.filter((item) => item.slot === slot);
            if (inSlot.length === 0) return null;
            const worn = layers.find((layer) => bySlug.get(layer.accessory)?.slot === slot);

            return (
              <div key={slot}>
                <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
                  {label}
                </h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {worn && (
                    <li>
                      <button
                        type="button"
                        onClick={() => unequip(worn.accessory)}
                        className="rounded border border-border px-3 py-1.5 text-sm hover:border-accent"
                      >
                        Take off
                      </button>
                    </li>
                  )}
                  {inSlot.map((item) => (
                    <li key={item.slug}>
                      <button
                        type="button"
                        disabled={!item.unlocked}
                        onClick={() => equip(item)}
                        aria-pressed={worn?.accessory === item.slug}
                        title={item.unlocked ? (item.description ?? item.name) : unlockReason(item)}
                        className={`rounded border px-3 py-1.5 text-sm ${
                          worn?.accessory === item.slug
                            ? "border-accent bg-accent/10"
                            : "border-border hover:border-border-strong"
                        } disabled:cursor-not-allowed disabled:opacity-40`}
                      >
                        <span className={RARITY_TEXT[item.rarity] ?? ""}>{item.name}</span>
                        {/* Locked ones are shown rather than hidden: seeing the
                            hat you have not earned is the motivation. The
                            *reason* is said in words, never by colour alone. */}
                        {!item.unlocked && (
                          <span className="ml-2 text-xs text-content-muted">
                            {unlockReason(item)}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function Preview({
  userId,
  cacheBust,
  layers,
  bySlug,
  selected,
  onMove,
}: {
  userId: string;
  cacheBust: number;
  layers: AvatarLayer[];
  bySlug: Map<string, Accessory>;
  selected: string | null;
  onMove: (x: number, y: number) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) return;
    const move = (event: PointerEvent) => {
      const box = frame.current?.getBoundingClientRect();
      if (!box) return;
      onMove(
        Math.min(1.2, Math.max(-0.2, (event.clientX - box.left) / box.width)),
        Math.min(1.2, Math.max(-0.2, (event.clientY - box.top) / box.height)),
      );
    };
    const stop = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
  }, [dragging, onMove]);

  return (
    <div
      ref={frame}
      className="relative mt-2 overflow-hidden rounded-lg border border-border-strong bg-surface-sunken"
      style={{ width: PREVIEW, height: PREVIEW, maxWidth: "100%" }}
    >
      {/* The composite as the server last rendered it. Accessory art is drawn
          over the top so a drag is instant; on save the two agree again. */}
      <img
        src={`${avatarUrl(userId)}?v=${cacheBust}`}
        alt=""
        className="absolute inset-0 h-full w-full object-cover"
      />
      {layers.map((layer) => {
        const accessory = bySlug.get(layer.accessory);
        if (!accessory) return null;
        const isSelected = layer.accessory === selected;
        return (
          <div
            key={layer.accessory}
            onPointerDown={() => isSelected && setDragging(true)}
            className={`absolute grid place-items-center rounded text-center text-xs ${
              isSelected
                ? "cursor-move border-2 border-dashed border-accent bg-accent/20"
                : "border border-border/60 bg-surface/40"
            }`}
            style={{
              left: `${layer.x * 100}%`,
              top: `${layer.y * 100}%`,
              width: PREVIEW * 0.5 * layer.scale,
              height: PREVIEW * 0.5 * layer.scale,
              transform: `translate(-50%, -50%) rotate(${layer.rotation}deg)`,
            }}
          >
            {/* A placeholder box rather than the art: the PNGs live in object
                storage and are not reachable from here. It shows *where* the
                thing will sit, which is what the editor is for. */}
            {accessory.name}
          </div>
        );
      })}
    </div>
  );
}

function Adjusters({
  layer,
  name,
  onChange,
}: {
  layer: AvatarLayer;
  name: string;
  onChange: (patch: Partial<AvatarLayer>) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <p className="text-sm font-medium">{name}</p>
      <label className="mt-3 block text-sm">
        Size
        <input
          type="range"
          min={0.2}
          max={3}
          step={0.05}
          value={layer.scale}
          onChange={(event) => onChange({ scale: Number(event.target.value) })}
          className="mt-1 w-full"
        />
      </label>
      <label className="mt-2 block text-sm">
        Angle
        <input
          type="range"
          min={-180}
          max={180}
          step={1}
          value={layer.rotation}
          onChange={(event) => onChange({ rotation: Number(event.target.value) })}
          className="mt-1 w-full"
        />
      </label>
      <p className="mt-2 text-xs text-content-muted tabular-nums">
        {Math.round(layer.scale * 100)}% · {Math.round(layer.rotation)}°
      </p>
    </div>
  );
}
