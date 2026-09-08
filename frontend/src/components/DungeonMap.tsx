import { useMemo, useState } from "react";

import type { DungeonMap as MapData, Zone } from "../api/dungeon";
import ZonePanel from "./ZonePanel";

/**
 * The dungeon map (specs 017, 019) — 22 zones, not 231 challenges. Clicking a
 * zone opens its challenges in a panel over the map, so you never lose your
 * place in the dungeon.
 *
 * Every lock it draws was decided by the backend; nothing here gates. Lighting
 * carries the state: a fully cleared zone burns warm, an open one is lit cold, a
 * sealed one sits dark. Fog of war is the torches going out, which is why it
 * reads without hiding anything.
 *
 * Layout comes from the server, so every player sees the same dungeon. Artwork
 * (spec 020) layers onto these positions; until a tile exists a zone draws as a
 * procedural stone chamber.
 */
const LAYOUT = {
  zoneWidth: 190,
  zoneHeight: 104,
  columnGap: 58,
  rowGap: 86,
  margin: 56,
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

const COLUMN = LAYOUT.zoneWidth + LAYOUT.columnGap;
const ROW = LAYOUT.zoneHeight + LAYOUT.rowGap;

/** Centre of a zone, for running corridors between them. */
function centre(zone: Zone) {
  return {
    cx: LAYOUT.margin + zone.x * COLUMN + LAYOUT.zoneWidth / 2,
    cy: LAYOUT.margin + zone.y * ROW + LAYOUT.zoneHeight / 2,
  };
}

export default function DungeonMap({ data }: { data: MapData }) {
  const [openZone, setOpenZone] = useState<Zone | null>(null);

  const zones = data.zones ?? [];
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
        className="mt-4 overflow-x-auto rounded-lg border border-stone"
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
          <rect width={width} height={height} fill="url(#dungeon-grid)" />

          {/* Torchlight pools under the zones you can enter. */}
          <g filter="url(#dungeon-bloom)" opacity={0.8}>
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
                    rx={cleared ? 150 : 118}
                    ry={cleared ? 110 : 86}
                    fill={cleared ? "url(#dungeon-torch)" : "url(#dungeon-coldlight)"}
                  />
                );
              })}
          </g>

          {/* Corridors: what opens what. */}
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
                    strokeWidth={26}
                    strokeLinecap="round"
                  />
                  <line
                    x1={from.cx}
                    y1={from.cy}
                    x2={to.cx}
                    y2={to.cy}
                    stroke={dark ? PALETTE.stoneMid : PALETTE.stoneLit}
                    strokeWidth={15}
                    strokeLinecap="round"
                    opacity={dark ? 0.4 : 0.85}
                  />
                </g>
              );
            })}
          </g>

          {zones.map((zone) => (
            <ZoneNode
              key={zone.id}
              zone={zone}
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
          opacity={0.16}
        />
      </pattern>

      {/* Rough-hewn walls. One filter shared by every zone, so it stays cheap. */}
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
        <feGaussianBlur stdDeviation={26} />
      </filter>

      <radialGradient id="dungeon-torch">
        <stop offset="0%" stopColor="#ffca7a" stopOpacity={0.9} />
        <stop offset="35%" stopColor={PALETTE.torch} stopOpacity={0.5} />
        <stop offset="100%" stopColor={PALETTE.torch} stopOpacity={0} />
      </radialGradient>

      <radialGradient id="dungeon-coldlight">
        <stop offset="0%" stopColor={PALETTE.water} stopOpacity={0.5} />
        <stop offset="100%" stopColor={PALETTE.water} stopOpacity={0} />
      </radialGradient>

      <linearGradient id="dungeon-floor-lit" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={PALETTE.stoneLit} />
        <stop offset="100%" stopColor={PALETTE.stoneMid} />
      </linearGradient>

      <linearGradient id="dungeon-floor-dark" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={PALETTE.stoneMid} />
        <stop offset="100%" stopColor={PALETTE.stoneDark} />
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
  unlit,
  onOpen,
}: {
  zone: Zone;
  unlit: boolean;
  onOpen: () => void;
}) {
  const { cx, cy } = centre(zone);
  const x = cx - LAYOUT.zoneWidth / 2;
  const y = cy - LAYOUT.zoneHeight / 2;
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
      className="cursor-pointer"
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <g filter="url(#dungeon-rough)">
        <rect
          x={-6}
          y={-6}
          width={LAYOUT.zoneWidth + 12}
          height={LAYOUT.zoneHeight + 12}
          rx={14}
          fill={PALETTE.wall}
        />
        <rect
          width={LAYOUT.zoneWidth}
          height={LAYOUT.zoneHeight}
          rx={10}
          fill={unlit ? "url(#dungeon-floor-dark)" : "url(#dungeon-floor-lit)"}
        />
      </g>
      <rect
        width={LAYOUT.zoneWidth}
        height={LAYOUT.zoneHeight}
        rx={10}
        fill="url(#dungeon-flagstone)"
        opacity={unlit ? 0.5 : 1}
      />

      <text
        x={14}
        y={30}
        fill={unlit ? PALETTE.inkDim : PALETTE.ink}
        className="text-[14px] font-semibold"
      >
        {zone.name.length > 22 ? `${zone.name.slice(0, 21)}…` : zone.name}
      </text>
      <text x={14} y={52} fill={PALETTE.inkDim} className="text-[11px]">
        {zone.cleared}/{zone.total} cleared
      </text>

      {/* The condition is always legible: fog puts the torches out, it never
          hides what opens a wing. Also the non-colour signal that it is shut. */}
      {zone.locked && condition && (
        <text
          x={14}
          y={LAYOUT.zoneHeight - 14}
          fill={PALETTE.torch}
          className="text-[11px]"
        >
          {condition.length > 30 ? `${condition.slice(0, 29)}…` : condition}
        </text>
      )}
    </g>
  );
}
