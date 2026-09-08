import { useEffect, useMemo, useState } from "react";

import type { DungeonMap as MapData, Zone } from "../api/dungeon";
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
const LAYOUT = {
  tile: 172,
  columnGap: 76,
  rowGap: 104,
  margin: 64,
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
  water: "#3fd6d0",
  ink: "#f0e2c8",
  inkDim: "#9b8f7d",
};

const COLUMN = LAYOUT.tile + LAYOUT.columnGap;
const ROW = LAYOUT.tile + LAYOUT.labelHeight + LAYOUT.rowGap;

const tileUrl = (slug: string) => `/map/zones/${slug}.png`;

function centre(zone: Zone) {
  return {
    cx: LAYOUT.margin + zone.x * COLUMN + LAYOUT.tile / 2,
    cy: LAYOUT.margin + zone.y * ROW + LAYOUT.tile / 2,
  };
}

/**
 * Which zones have artwork. Probed once rather than handled per-element, so a
 * zone renders its fallback immediately instead of flashing a broken image.
 */
function useAvailableTiles(slugs: string[]): Set<string> {
  const key = slugs.join(",");
  const [available, setAvailable] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    for (const slug of key ? key.split(",") : []) {
      const probe = new Image();
      probe.onload = () => {
        if (!cancelled) setAvailable((have) => new Set(have).add(slug));
      };
      probe.src = tileUrl(slug);
    }
    return () => {
      cancelled = true;
    };
  }, [key]);

  return available;
}

export default function DungeonMap({ data }: { data: MapData }) {
  const [openZone, setOpenZone] = useState<Zone | null>(null);

  const zones = data.zones ?? [];
  const slugs = useMemo(() => zones.map((z) => z.slug), [zones]);
  const tiles = useAvailableTiles(slugs);

  const { width, height } = useMemo(() => {
    const columns = Math.max(1, ...zones.map((z) => z.x + 1));
    const rows = Math.max(1, ...zones.map((z) => z.y + 1));
    return {
      width: LAYOUT.margin * 2 + columns * COLUMN - LAYOUT.columnGap,
      height: LAYOUT.margin * 2 + rows * ROW - LAYOUT.rowGap,
    };
  }, [zones]);

  const points = useMemo(() => new Map(zones.map((z) => [z.id, centre(z)])), [zones]);

  if (zones.length === 0) {
    return <p className="mt-8 text-muted">The dungeon is empty for now.</p>;
  }

  return (
    <>
      <figure
        className="dungeon mt-4 overflow-x-auto rounded-lg border border-stone"
        aria-label="Dungeon map"
        style={{ background: PALETTE.void }}
      >
        <svg
          role="group"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="max-w-none"
        >
          <Defs />

          <rect width={width} height={height} fill={PALETTE.void} />
          <rect width={width} height={height} fill="url(#dungeon-base)" opacity={0.9} />
          <rect width={width} height={height} fill="url(#dungeon-grid)" />

          {/* Torchlight pools under the zones you can enter. */}
          <g filter="url(#dungeon-bloom)" opacity={0.75} className="dungeon-torch">
            {zones
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
              const target = zones.find((z) => z.id === edge.to_zone_id);
              const dark = data.fog_of_war && target?.locked;
              return (
                <g key={`${edge.from_zone_id}-${edge.to_zone_id}`}>
                  <line
                    x1={from.cx}
                    y1={from.cy}
                    x2={to.cx}
                    y2={to.cy}
                    stroke={PALETTE.wall}
                    strokeWidth={30}
                    strokeLinecap="round"
                  />
                  <line
                    x1={from.cx}
                    y1={from.cy}
                    x2={to.cx}
                    y2={to.cy}
                    stroke={dark ? PALETTE.stoneMid : PALETTE.stoneLit}
                    strokeWidth={17}
                    strokeLinecap="round"
                    opacity={dark ? 0.35 : 0.8}
                  />
                </g>
              );
            })}
          </g>

          {zones.map((zone) => (
            <ZoneNode
              key={zone.id}
              zone={zone}
              hasTile={tiles.has(zone.slug)}
              unlit={data.fog_of_war && zone.locked}
              onOpen={() => setOpenZone(zone)}
            />
          ))}

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

function Defs() {
  return (
    <defs>
      <pattern id="dungeon-base" width={1536} height={1024} patternUnits="userSpaceOnUse">
        <image href="/map/base.png" width={1536} height={1024} preserveAspectRatio="none" />
      </pattern>

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
  onOpen,
}: {
  zone: Zone;
  hasTile: boolean;
  unlit: boolean;
  onOpen: () => void;
}) {
  const { cx, cy } = centre(zone);
  const x = cx - LAYOUT.tile / 2;
  const y = cy - LAYOUT.tile / 2;
  const condition = zone.unlock_requirements.map((r) => r.description).join(", ");

  // Spelled out rather than left to the lighting, so the state survives
  // greyscale and reaches a screen reader.
  const label = zone.locked
    ? `${zone.name} — sealed${condition ? `, needs ${condition}` : ""}`
    : `${zone.name} — open, ${zone.cleared} of ${zone.total} cleared`;

  return (
    <g
      transform={`translate(${x}, ${y})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      className="dungeon-zone cursor-pointer"
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
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
