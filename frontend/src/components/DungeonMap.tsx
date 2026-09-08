import { useEffect, useMemo, useRef, useState } from "react";

import type { DungeonMap as MapData, Zone } from "../api/dungeon";
import { useMapViewport } from "./useMapViewport";
import ZonePanel from "./ZonePanel";

/**
 * The dungeon map (specs 017, 019, 020) — 22 zones, not 231 challenges.
 *
 * Three layers, and keeping them apart is the whole idea: painted tiles that
 * know nothing about game state, an SVG layer over them carrying everything
 * stateful, and budgeted ambience. A zone with no tile yet draws as a procedural
 * stone chamber, so the map works with a partial art set and improves one file
 * at a time.
 *
 * **Corridors are drawn underneath the tiles.** A tile cannot know how many
 * connections its zone has — Intro has six, a leaf has one — so painted doors
 * could never line up. Running the corridor under the art means it emerges from
 * beneath the chamber, which reads correctly for any number of them.
 */
/* Proportions matter more than they look: the first pass had gaps wider than the
   tiles, so the map read as mostly empty floor with small pictures on it. The
   tiles are now the content and the gaps are just enough to run a corridor. */
const LAYOUT = {
  tile: 260,
  columnGap: 44,
  rowGap: 72,
  margin: 40,
  labelHeight: 34,
  gridSize: 32,
};

const PALETTE = {
  void: "#0a0f17",
  gridLine: "#4a7fa8",
  stoneDark: "#241f1b",
  stoneMid: "#584a3d",
  stoneLit: "#9c7d59",
  wall: "#15110e",
  torch: "#ff9d3d",
  // Corridors are cut rock, not paved road: they sit a shade above the base
  // plate and let the tiles be the bright things on the map.
  corridorCut: "#0d0b09",
  corridorFloor: "#241d17",
  corridorFloorDim: "#171412",
  water: "#3fd6d0",
  ink: "#f0e2c8",
  inkDim: "#9b8f7d",
};

const tileUrl = (slug: string) => `/map/zones/${slug}.png`;

/** Zone coordinates are the tile's top-left corner, in map pixels — authored by
 *  an admin (spec 021) or derived by the server, and the client cannot tell. */
function centre(zone: Zone) {
  return { cx: zone.x + LAYOUT.tile / 2, cy: zone.y + LAYOUT.tile / 2 };
}

/**
 * An organic corridor between two zones.
 *
 * A quadratic curve whose control point is the midpoint pushed perpendicular to
 * the line. The push is derived from the two zone ids, so every corridor gets
 * its own consistent bend with no authoring at all — and it is identical for
 * every player and across reloads, which a random one would not be.
 */
function hashOf(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return hash;
}

/** The hash as 0..1 — for anything that wants a stable per-thing variation. */
function hashUnit(seed: string): number {
  return (Math.abs(hashOf(seed)) % 1000) / 1000;
}

/**
 * Soft darkening pools, placed from the map's own dimensions.
 *
 * Their whole job is to be on a different rhythm from the plate's tiling grid,
 * so the eye stops finding the repeat (spec 023).
 */
function darkPools(width: number, height: number) {
  const pools = [];
  for (let i = 0; i < 7; i += 1) {
    const seed = hashUnit(`pool-${i}-${width}x${height}`);
    const other = hashUnit(`pool-alt-${i}`);
    pools.push({
      cx: width * ((seed * 1.2 + i * 0.19) % 1),
      cy: height * ((other * 1.3 + i * 0.31) % 1),
      rx: width * (0.18 + other * 0.22),
      ry: height * (0.08 + seed * 0.12),
    });
  }
  return pools;
}

function corridorPath(
  from: { cx: number; cy: number },
  to: { cx: number; cy: number },
  seed: string,
): string {
  const hash = hashOf(seed);
  const dx = to.cx - from.cx;
  const dy = to.cy - from.cy;
  const length = Math.hypot(dx, dy) || 1;
  // Bend proportional to length, so short hops stay nearly straight and long
  // runs sweep — and never so far that the corridor loses its own endpoints.
  const amount = (((hash % 100) / 100) * 0.16 + 0.06) * length;
  const sign = hash % 2 === 0 ? 1 : -1;
  const mx = (from.cx + to.cx) / 2 + (-dy / length) * amount * sign;
  const my = (from.cy + to.cy) / 2 + (dx / length) * amount * sign;
  return `M ${from.cx} ${from.cy} Q ${mx} ${my} ${to.cx} ${to.cy}`;
}

/** Optional scatter art over the base plate. Each is placed once rather than
 *  tiled, so any number of them breaks the grid further — and the map is
 *  correct with none of them present (spec 023). */
const OVERLAYS = ["rubble", "cracks", "scorch", "water"];

const overlayUrl = (name: string) => `/map/overlays/${name}.png`;

function Overlays({ width, height }: { width: number; height: number }) {
  const available = useAvailableImages(OVERLAYS, overlayUrl);
  return (
    <g pointerEvents="none">
      {OVERLAYS.filter((name) => available.has(name)).map((name, index) => {
        const seed = hashUnit(`overlay-${name}`);
        const size = Math.max(width, height) * (0.55 + seed * 0.35);
        return (
          <image
            key={name}
            href={overlayUrl(name)}
            x={width * ((seed * 1.4 + index * 0.23) % 1) - size / 2}
            y={height * ((hashUnit(`overlay-y-${name}`) * 1.2 + index * 0.29) % 1) - size / 2}
            width={size}
            height={size}
            opacity={0.5}
            preserveAspectRatio="xMidYMid meet"
          />
        );
      })}
    </g>
  );
}

/**
 * Which zones have artwork. Probed once rather than handled per-element, so a
 * zone renders its fallback immediately instead of flashing a broken image.
 */
function useAvailableImages(
  names: string[],
  toUrl: (name: string) => string,
): Set<string> {
  const key = names.join(",");
  const [available, setAvailable] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    for (const name of key ? key.split(",") : []) {
      const probe = new Image();
      probe.onload = () => {
        if (!cancelled) setAvailable((have) => new Set(have).add(name));
      };
      probe.src = toUrl(name);
    }
    return () => {
      cancelled = true;
    };
  }, [key, toUrl]);

  return available;
}

/** Free placement, snapped just enough that saved values stay tidy and two
 *  zones nudged to "the same" spot actually match (spec 021). */
const SNAP = 8;

/** Below this, a press in edit mode is a click on the zone rather than a move. */
const EDIT_CLICK_SLOP = 4;

export default function DungeonMap({
  data,
  editable = false,
  onMove,
  onEditGates,
  unreachable,
  fullBleed = false,
}: {
  data: MapData;
  /** Admin edit mode: drag zones to move them, click to edit their gates. */
  editable?: boolean;
  onMove?: (zoneId: string, x: number, y: number) => void;
  onEditGates?: (zoneId: string) => void;
  /** Break out of the page column. The challenges page wants the room; the
   *  admin page keeps its column, where the controls read better. */
  fullBleed?: boolean;
  /** Zones no player can reach — flagged in edit mode only (spec 022). */
  unreachable?: Set<string>;
}) {
  const [openZone, setOpenZone] = useState<Zone | null>(null);
  const [dragging, setDragging] = useState<{ id: string; x: number; y: number } | null>(
    null,
  );
  const zones = data.zones ?? [];
  const slugs = useMemo(() => zones.map((z) => z.slug), [zones]);
  const tiles = useAvailableImages(slugs, tileUrl);

  const content = useMemo(
    () => ({
      width:
        Math.max(LAYOUT.tile, ...zones.map((z) => z.x + LAYOUT.tile)) + LAYOUT.margin,
      height:
        Math.max(LAYOUT.tile, ...zones.map((z) => z.y + LAYOUT.tile + LAYOUT.labelHeight)) +
        LAYOUT.margin,
    }),
    [zones],
  );
  const { width, height } = content;
  const view = useMapViewport(content);

  // While a zone is being dragged, draw it (and its corridors) at the pointer
  // rather than where the server last saw it.
  const placed = useMemo(
    () =>
      zones.map((z) =>
        dragging && dragging.id === z.id ? { ...z, x: dragging.x, y: dragging.y } : z,
      ),
    [zones, dragging],
  );
  const points = useMemo(() => new Map(placed.map((z) => [z.id, centre(z)])), [placed]);

  if (zones.length === 0) {
    return <p className="mt-8 text-muted">The dungeon is empty for now.</p>;
  }

  return (
    <>
      <figure
        ref={view.container}
        className={
          view.fullscreen
            ? "dungeon fixed inset-0 z-30 overflow-hidden"
            : `dungeon dungeon-feathered relative mt-4 h-[80vh] min-h-[520px] overflow-hidden ${
                fullBleed ? "dungeon-bleed" : "rounded-lg"
              }`
        }
        aria-label="Dungeon map"
        style={{
          background: PALETTE.void,
          cursor: view.panning ? "grabbing" : "grab",
          touchAction: "none",
        }}
        {...view.handlers}
      >
        <MapControls view={view} />
        <svg
          role="group"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="max-w-none origin-top-left select-none"
          style={{
            transform: `translate(${view.viewport.x}px, ${view.viewport.y}px) scale(${view.viewport.scale})`,
          }}
        >
          <Defs />

          <rect width={width} height={height} fill={PALETTE.void} />
          <rect width={width} height={height} fill="url(#dungeon-base)" opacity={0.9} />

          {/* Everything from here to the corridors exists to stop the plate
              reading as a tiled grid. None of it repeats (spec 023). */}
          <rect
            width={width}
            height={height}
            filter="url(#dungeon-mottle)"
            opacity={0.55}
          />
          {darkPools(width, height).map((pool, index) => (
            <ellipse
              key={`pool-${index}`}
              cx={pool.cx}
              cy={pool.cy}
              rx={pool.rx}
              ry={pool.ry}
              fill="url(#dungeon-pool)"
            />
          ))}
          <Overlays width={width} height={height} />
          <rect width={width} height={height} fill="url(#dungeon-grain)" opacity={0.16} />

          <rect width={width} height={height} fill="url(#dungeon-grid)" />

          {/* Torchlight pools under the zones you can enter. */}
          <g filter="url(#dungeon-bloom)" opacity={0.75} className="dungeon-torch">
            {placed
              .filter((z) => !z.locked)
              .map((z) => {
                const point = points.get(z.id);
                if (!point) return null;
                const cleared = z.total > 0 && z.cleared === z.total;
                return (
                  <ellipse
                    key={`light-${z.id}`}
                    cx={point.cx}
                    cy={point.cy}
                    rx={cleared ? 160 : 128}
                    ry={cleared ? 130 : 104}
                    fill={cleared ? "url(#dungeon-torch)" : "url(#dungeon-coldlight)"}
                  />
                );
              })}
          </g>

          {/* Corridors, under the tiles so their ends are hidden by the art. */}
          <g>
            {(data.edges ?? []).map((edge) => {
              const from = points.get(edge.from_zone_id);
              const to = points.get(edge.to_zone_id);
              if (!from || !to) return null;
              const target = placed.find((z) => z.id === edge.to_zone_id);
              const dark = data.fog_of_war && target?.locked;
              const seed = `${edge.from_zone_id}${edge.to_zone_id}`;
              const path = corridorPath(from, to, seed);
              const wobble = hashUnit(seed);
              return (
                <g
                  key={`${edge.from_zone_id}-${edge.to_zone_id}`}
                  filter="url(#dungeon-corridor-rough)"
                >
                  {/* The cut through the rock. Width varies per corridor from
                      the same hash that bends it, so no two are identical. */}
                  <path
                    d={path}
                    fill="none"
                    stroke={PALETTE.corridorCut}
                    strokeWidth={26 + wobble * 8}
                    strokeLinecap="round"
                  />
                  <path
                    d={path}
                    fill="none"
                    stroke={dark ? PALETTE.corridorFloorDim : PALETTE.corridorFloor}
                    strokeWidth={14 + wobble * 6}
                    strokeLinecap="round"
                    opacity={dark ? 0.6 : 0.95}
                  />
                  {/* A thread of torchlight down an open passage — the only
                      thing tying it to the lit zones, and faint enough that the
                      corridor still reads as unlit rock. */}
                  {!dark && (
                    <path
                      d={path}
                      fill="none"
                      stroke={PALETTE.torch}
                      strokeWidth={5}
                      strokeLinecap="round"
                      opacity={0.1}
                    />
                  )}
                </g>
              );
            })}
          </g>

          {placed.map((zone) => (
            <ZoneNode
              key={zone.id}
              zone={zone}
              hasTile={tiles.has(zone.slug)}
              unlit={data.fog_of_war && zone.locked}
              fogged={data.fog_of_war && zone.locked}
              editable={editable}
              stranded={editable && (unreachable?.has(zone.id) ?? false)}
              // A drag that happens to start on a zone is a pan, not a click.
              onOpen={() => {
                if (view.wasPan()) return;
                if (editable) onEditGates?.(zone.id);
                else setOpenZone(zone);
              }}
              // Deltas are measured from where the drag began, so they are
              // applied to that same starting position — never to the in-flight
              // one, which would compound every move event.
              onDragMove={(startX, startY, dx, dy) =>
                setDragging({
                  id: zone.id,
                  x: Math.round((startX + dx / view.viewport.scale) / SNAP) * SNAP,
                  y: Math.round((startY + dy / view.viewport.scale) / SNAP) * SNAP,
                })
              }
              onDragEnd={() => {
                if (dragging && dragging.id === zone.id) {
                  onMove?.(zone.id, dragging.x, dragging.y);
                }
                setDragging(null);
              }}
            />
          ))}

          <Motes zones={placed.filter((z) => !(data.fog_of_war && z.locked))} />

          <rect
            width={width}
            height={height}
            fill="url(#dungeon-vignette)"
            pointerEvents="none"
          />
        </svg>
      </figure>

      {openZone && <ZonePanel zone={openZone} onClose={() => setOpenZone(null)} />}
    </>
  );
}

/** Dust drifting in the lit parts of the dungeon, so open ground feels
 *  occupied rather than merely painted (spec 023). */
function Motes({ zones }: { zones: Zone[] }) {
  return (
    <g pointerEvents="none">
      {zones.flatMap((zone) =>
        [0, 1, 2].map((index) => {
          const seed = hashUnit(`mote-${zone.id}-${index}`);
          const other = hashUnit(`mote-alt-${zone.id}-${index}`);
          return (
            <circle
              key={`mote-${zone.id}-${index}`}
              cx={zone.x + LAYOUT.tile * (0.15 + seed * 0.7)}
              cy={zone.y + LAYOUT.tile * (0.2 + other * 0.6)}
              r={1 + seed * 1.6}
              fill={PALETTE.torch}
              className="dungeon-mote"
              style={{ animationDelay: `${(seed * 14).toFixed(1)}s` }}
            />
          );
        }),
      )}
    </g>
  );
}

function Defs() {
  return (
    <defs>
      {/* Drawn at 2x so the plate repeats half as often before the
          non-repeating layers above it hide what is left (spec 023). */}
      <pattern id="dungeon-base" width={3072} height={2048} patternUnits="userSpaceOnUse">
        <image href="/map/base.png" width={3072} height={2048} preserveAspectRatio="none" />
      </pattern>

      {/* One noise cell spans the whole map, so there is no second copy of it
          to notice — which is what kills the sense of a repeating grid. */}
      <filter
        id="dungeon-mottle"
        filterUnits="objectBoundingBox"
        x="0"
        y="0"
        width="1"
        height="1"
      >
        <feTurbulence type="fractalNoise" baseFrequency="0.0016" numOctaves={2} seed={7} />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0.04
                  0 0 0 0 0.05
                  0 0 0 0 0.07
                  0 0 0 0.7 0"
        />
      </filter>

      {/* Fine grain, which is what actually hides the plate's seam line.
          Tiled small rather than applied as one map-sized filter: a filter that
          big gets seamed by the browser's own internal tiling, and those seams
          showed as streaks across the map. A repeat at this scale is invisible
          in a way a repeating photographic plate never is. */}
      <filter id="dungeon-grain-tile" x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves={1} seed={23} />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0.5
                  0 0 0 0 0.47
                  0 0 0 0 0.42
                  0 0 0 0.35 0"
        />
      </filter>
      <pattern id="dungeon-grain" width={256} height={256} patternUnits="userSpaceOnUse">
        <rect width={256} height={256} filter="url(#dungeon-grain-tile)" />
      </pattern>

      {/* Corridors: the same hewn treatment the procedural chambers get, at a
          lower scale so a passage stays readable as a passage. */}
      <filter id="dungeon-corridor-rough" x="-15%" y="-15%" width="130%" height="130%">
        <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves={3} seed={31} />
        <feDisplacementMap
          in="SourceGraphic"
          scale={7}
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>

      {/* Fog over the unexplored map. Two offset fields drifting in different
          directions, so they never line up into a visible cycle. */}
      <filter id="dungeon-fog-a" x="-25%" y="-25%" width="150%" height="150%">
        <feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves={3} seed={3} />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0.62
                  0 0 0 0 0.66
                  0 0 0 0 0.72
                  0 0 0 0.9 0"
        />
      </filter>
      <filter id="dungeon-fog-b" x="-25%" y="-25%" width="150%" height="150%">
        <feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves={2} seed={17} />
        <feColorMatrix
          type="matrix"
          values="0 0 0 0 0.55
                  0 0 0 0 0.58
                  0 0 0 0 0.66
                  0 0 0 0.8 0"
        />
      </filter>

      {/* Fog has to fall off at its own edges. A filter fills its region as a
          rectangle, so without this mask the tile's bounding box *is* the
          visible shape — grey boxes instead of cloud. */}
      <radialGradient id="dungeon-fog-fade">
        <stop offset="0%" stopColor="#fff" stopOpacity={1} />
        <stop offset="55%" stopColor="#fff" stopOpacity={0.75} />
        <stop offset="100%" stopColor="#fff" stopOpacity={0} />
      </radialGradient>
      <mask id="dungeon-fog-mask" maskUnits="userSpaceOnUse">
        <rect
          x={-40}
          y={-40}
          width={LAYOUT.tile + 80}
          height={LAYOUT.tile + 80}
          fill="url(#dungeon-fog-fade)"
        />
      </mask>

      <radialGradient id="dungeon-pool">
        <stop offset="0%" stopColor="#000" stopOpacity={0.55} />
        <stop offset="100%" stopColor="#000" stopOpacity={0} />
      </radialGradient>

      <pattern
        id="dungeon-grid"
        width={LAYOUT.gridSize}
        height={LAYOUT.gridSize}
        patternUnits="userSpaceOnUse"
      >
        <path
          d={`M ${LAYOUT.gridSize} 0 L 0 0 0 ${LAYOUT.gridSize}`}
          fill="none"
          stroke={PALETTE.gridLine}
          strokeWidth={1}
          opacity={0.14}
        />
      </pattern>

      <filter id="dungeon-rough" x="-12%" y="-12%" width="124%" height="124%">
        <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves={3} seed={11} />
        <feDisplacementMap
          in="SourceGraphic"
          scale={12}
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>

      <filter id="dungeon-bloom" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation={28} />
      </filter>

      {/* Follows the tile's real alpha silhouette, so it is correct for any
          shape — which a shadow baked into the art could never be. */}
      <filter id="dungeon-tile-shadow" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="6" stdDeviation="10" floodColor="#000" floodOpacity="0.65" />
      </filter>

      <radialGradient id="dungeon-torch">
        <stop offset="0%" stopColor="#ffca7a" stopOpacity={0.9} />
        <stop offset="35%" stopColor={PALETTE.torch} stopOpacity={0.5} />
        <stop offset="100%" stopColor={PALETTE.torch} stopOpacity={0} />
      </radialGradient>

      <radialGradient id="dungeon-coldlight">
        <stop offset="0%" stopColor={PALETTE.water} stopOpacity={0.45} />
        <stop offset="100%" stopColor={PALETTE.water} stopOpacity={0} />
      </radialGradient>

      <linearGradient id="dungeon-floor-lit" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={PALETTE.stoneMid} />
        <stop offset="100%" stopColor={PALETTE.stoneDark} />
      </linearGradient>

      <linearGradient id="dungeon-floor-dark" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={PALETTE.stoneDark} />
        <stop offset="100%" stopColor="#171310" />
      </linearGradient>

      <pattern id="dungeon-flagstone" width={22} height={22} patternUnits="userSpaceOnUse">
        <path
          d="M 22 0 L 0 0 0 22"
          fill="none"
          stroke={PALETTE.wall}
          strokeWidth={1}
          opacity={0.4}
        />
      </pattern>

      <radialGradient id="dungeon-vignette" cx="50%" cy="50%" r="78%">
        <stop offset="55%" stopColor="#000" stopOpacity={0} />
        <stop offset="100%" stopColor="#000" stopOpacity={0.7} />
      </radialGradient>
    </defs>
  );
}

function ZoneNode({
  zone,
  hasTile,
  unlit,
  fogged,
  editable,
  stranded,
  onOpen,
  onDragMove,
  onDragEnd,
}: {
  zone: Zone;
  hasTile: boolean;
  unlit: boolean;
  /** Sealed, with fog of war on. The same signal as `unlit`, named for what it
   *  draws rather than what it dims. */
  fogged: boolean;
  editable: boolean;
  stranded: boolean;
  onOpen: () => void;
  onDragMove: (startX: number, startY: number, dx: number, dy: number) => void;
  onDragEnd: () => void;
}) {
  //: Where the pointer went down, and where the zone sat at that moment.
  const origin = useRef<{
    x: number;
    y: number;
    zx: number;
    zy: number;
    moved: number;
  } | null>(null);
  const condition = zone.unlock_requirements.map((r) => r.description).join(", ");

  // Spelled out rather than left to the lighting, so the state survives
  // greyscale and reaches a screen reader.
  const label = zone.locked
    ? `${zone.name} — sealed${condition ? `, needs ${condition}` : ""}`
    : `${zone.name} — open, ${zone.cleared} of ${zone.total} cleared`;

  return (
    <g
      transform={`translate(${zone.x}, ${zone.y})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      className={`dungeon-zone ${editable ? "cursor-move" : "cursor-pointer"}`}
      onClick={editable ? undefined : onOpen}
      data-stranded={stranded || undefined}
      data-locked={zone.locked || undefined}
      onKeyDown={(event) => {
        if (!editable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onOpen();
        }
      }}
      onPointerDown={
        editable
          ? (event) => {
              // Stop the map's own pan: in edit mode a drag on a zone moves the
              // zone, and a drag on the floor moves the map.
              event.stopPropagation();
              (event.target as Element).setPointerCapture?.(event.pointerId);
              origin.current = {
                x: event.clientX,
                y: event.clientY,
                zx: zone.x,
                zy: zone.y,
                moved: 0,
              };
            }
          : undefined
      }
      onPointerMove={
        editable
          ? (event) => {
              const start = origin.current;
              if (!start) return;
              start.moved = Math.max(
                start.moved,
                Math.abs(event.clientX - start.x) + Math.abs(event.clientY - start.y),
              );
              onDragMove(
                start.zx,
                start.zy,
                event.clientX - start.x,
                event.clientY - start.y,
              );
            }
          : undefined
      }
      onPointerUp={
        editable
          ? () => {
              // A press that went nowhere is a click: open this zone's gates
              // rather than saving a move to the position it already had.
              if (origin.current) {
                if (origin.current.moved > EDIT_CLICK_SLOP) onDragEnd();
                else onOpen();
              }
              origin.current = null;
            }
          : undefined
      }
    >
      {hasTile ? (
        <image
          href={tileUrl(zone.slug)}
          width={LAYOUT.tile}
          height={LAYOUT.tile}
          filter="url(#dungeon-tile-shadow)"
          // Sealed zones are the same art, desaturated and dimmed — greyed out
          // but readable, never hidden.
          style={{ filter: unlit ? "grayscale(0.7) brightness(0.62)" : undefined }}
        />
      ) : (
        <ProceduralChamber unlit={unlit} />
      )}

      <text
        x={LAYOUT.tile / 2}
        y={LAYOUT.tile + 18}
        textAnchor="middle"
        fill={unlit ? PALETTE.inkDim : PALETTE.ink}
        className="text-[14px] font-semibold"
      >
        {zone.name.length > 24 ? `${zone.name.slice(0, 23)}…` : zone.name}
      </text>
      <text
        x={LAYOUT.tile / 2}
        y={LAYOUT.tile + 33}
        textAnchor="middle"
        fill={PALETTE.inkDim}
        className="text-[11px]"
      >
        {zone.cleared}/{zone.total} cleared
      </text>

      {/* Fog of war: the unexplored map is fogged, and unlocking clears it.
          Drawn after the tile and before the labels, because 017 and 019 both
          hold that fog puts the torches out but never hides what opens a wing. */}
      {fogged && (
        <g className="dungeon-fog" pointerEvents="none" mask="url(#dungeon-fog-mask)">
          <rect
            x={-30}
            y={-30}
            width={LAYOUT.tile + 60}
            height={LAYOUT.tile + 60}
            filter="url(#dungeon-fog-a)"
            opacity={0.3}
            className="dungeon-fog-a"
          />
          <rect
            x={-30}
            y={-30}
            width={LAYOUT.tile + 60}
            height={LAYOUT.tile + 60}
            filter="url(#dungeon-fog-b)"
            opacity={0.22}
            className="dungeon-fog-b"
          />
        </g>
      )}

      {/* Nobody can reach this zone. Admin-only: a player seeing it would just
          be confused by a warning about something they cannot act on. */}
      {stranded && (
        <text
          x={LAYOUT.tile / 2}
          y={-10}
          textAnchor="middle"
          fill={PALETTE.torch}
          className="text-[12px] font-semibold"
        >
          ⚠ unreachable
        </text>
      )}

      {/* The condition is always legible: fog puts the torches out, it never
          hides what opens a wing. Also the non-colour signal that it is shut. */}
      {zone.locked && condition && (
        <text
          x={LAYOUT.tile / 2}
          y={LAYOUT.tile - 10}
          textAnchor="middle"
          fill={PALETTE.torch}
          className="text-[11px]"
        >
          {condition.length > 28 ? `${condition.slice(0, 27)}…` : condition}
        </text>
      )}
    </g>
  );
}

function MapControls({ view }: { view: ReturnType<typeof useMapViewport> }) {
  const button =
    "rounded border border-stone/60 bg-ink/70 px-2.5 py-1 text-sm text-parchment hover:bg-ink";
  return (
    <div className="absolute right-3 top-3 z-10 flex gap-1.5" onPointerDown={(e) => e.stopPropagation()}>
      <button type="button" className={button} onClick={() => view.zoomBy(1.2)} aria-label="Zoom in">
        +
      </button>
      <button
        type="button"
        className={button}
        onClick={() => view.zoomBy(1 / 1.2)}
        aria-label="Zoom out"
      >
        −
      </button>
      <button type="button" className={button} onClick={view.reset} aria-label="Reset view">
        Reset
      </button>
      <button
        type="button"
        className={button}
        onClick={() => view.setFullscreen(!view.fullscreen)}
        aria-label={view.fullscreen ? "Exit fullscreen" : "Fullscreen"}
      >
        {view.fullscreen ? "Exit" : "Fullscreen"}
      </button>
    </div>
  );
}

/** What a zone looks like before its tile exists. */
function ProceduralChamber({ unlit }: { unlit: boolean }) {
  return (
    <>
      <g filter="url(#dungeon-rough)">
        <rect
          x={-6}
          y={-6}
          width={LAYOUT.tile + 12}
          height={LAYOUT.tile + 12}
          rx={20}
          fill={PALETTE.wall}
          opacity={0.95}
        />
        <rect
          width={LAYOUT.tile}
          height={LAYOUT.tile}
          rx={16}
          fill={unlit ? "url(#dungeon-floor-dark)" : "url(#dungeon-floor-lit)"}
        />
      </g>
      <rect
        width={LAYOUT.tile}
        height={LAYOUT.tile}
        rx={16}
        fill="url(#dungeon-flagstone)"
        opacity={unlit ? 0.5 : 1}
      />
    </>
  );
}
