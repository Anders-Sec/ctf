import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import type { DungeonMap as MapData, Room, Zone } from "../api/dungeon";

/**
 * The dungeon map (spec 017) — a view over the challenges the player can already
 * see. Every lock it draws was decided by the backend; nothing here gates.
 *
 * Drawn as a lit battle map: a dark void, stone caverns, and torchlight that
 * pools where the player has been. That carries the game state without needing
 * legends — a cleared room burns warm, an open one is lit but cold, a shut one
 * is unlit stone, and a locked wing is dark and unexplored. Fog of war is simply
 * the torches going out, which is why it reads without hiding anything.
 *
 * Rooms sit at server-supplied grid coordinates, so every player sees the same
 * dungeon. All the tuning lives in LAYOUT and PALETTE below.
 */
const LAYOUT = {
  roomWidth: 168,
  roomHeight: 74,
  columnGap: 46,
  rowGap: 64,
  /** Stone floor extending past the rooms, so a wing reads as a cavern. */
  zonePadding: 34,
  zoneHeaderHeight: 40,
  zoneGap: 46,
  /** Wings wrap to a new row past this width. */
  maxRowWidth: 1220,
  /** Enough that a wing's name and its progress count never collide. */
  minZoneWidth: 310,
  /** Breathing room around the whole dungeon, for the vignette. */
  margin: 40,
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
  torchDeep: "#c2571a",
  water: "#3fd6d0",
  ink: "#f0e2c8",
  inkDim: "#9b8f7d",
};

const COLUMN = LAYOUT.roomWidth + LAYOUT.columnGap;
const ROW = LAYOUT.roomHeight + LAYOUT.rowGap;

interface PlacedZone {
  zone: Zone;
  rooms: Room[];
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Wing sizes, then pack them into rows. Pure geometry — no data decisions. */
function layout(data: MapData) {
  const roomsByZone = new Map<string, Room[]>();
  for (const room of data.rooms ?? []) {
    roomsByZone.set(room.zone_id, [...(roomsByZone.get(room.zone_id) ?? []), room]);
  }

  const zones = [...(data.zones ?? [])].sort(
    (a, b) => a.display_order - b.display_order || a.name.localeCompare(b.name),
  );

  const placed: PlacedZone[] = [];
  let rowX = LAYOUT.margin;
  let rowY = LAYOUT.margin;
  let rowHeight = 0;

  for (const zone of zones) {
    const rooms = roomsByZone.get(zone.id) ?? [];
    const columns = Math.max(1, ...rooms.map((r) => r.x + 1));
    const depth = Math.max(1, ...rooms.map((r) => r.y + 1));
    const width = Math.max(
      LAYOUT.minZoneWidth,
      columns * COLUMN - LAYOUT.columnGap + LAYOUT.zonePadding * 2,
    );
    const height =
      depth * ROW - LAYOUT.rowGap + LAYOUT.zonePadding * 2 + LAYOUT.zoneHeaderHeight;

    if (rowX > LAYOUT.margin && rowX + width > LAYOUT.maxRowWidth) {
      rowY += rowHeight + LAYOUT.zoneGap;
      rowX = LAYOUT.margin;
      rowHeight = 0;
    }

    placed.push({ zone, rooms, x: rowX, y: rowY, width, height });
    rowX += width + LAYOUT.zoneGap;
    rowHeight = Math.max(rowHeight, height);
  }

  const totalWidth = Math.max(...placed.map((p) => p.x + p.width), 1) + LAYOUT.margin;
  const totalHeight = rowY + rowHeight + LAYOUT.margin;
  return { placed, totalWidth, totalHeight };
}

/** How far to nudge each depth row so it sits centred in its wing. */
function rowOffsets(zone: PlacedZone): Map<number, number> {
  const perRow = new Map<number, number>();
  for (const room of zone.rooms) {
    perRow.set(room.y, Math.max(perRow.get(room.y) ?? 0, room.x + 1));
  }
  const widest = Math.max(1, ...perRow.values());
  const offsets = new Map<number, number>();
  for (const [depth, count] of perRow) {
    offsets.set(depth, ((widest - count) * COLUMN) / 2);
  }
  return offsets;
}

/** Absolute centre of a room, for running corridors between wings. */
function centres(placed: PlacedZone[]) {
  const points = new Map<string, { cx: number; cy: number }>();
  for (const zone of placed) {
    const offsets = rowOffsets(zone);
    for (const room of zone.rooms) {
      points.set(room.challenge_id, {
        cx:
          zone.x +
          LAYOUT.zonePadding +
          (offsets.get(room.y) ?? 0) +
          room.x * COLUMN +
          LAYOUT.roomWidth / 2,
        cy:
          zone.y +
          LAYOUT.zoneHeaderHeight +
          LAYOUT.zonePadding +
          room.y * ROW +
          LAYOUT.roomHeight / 2,
      });
    }
  }
  return points;
}

export default function DungeonMap({ data }: { data: MapData }) {
  const navigate = useNavigate();
  const { placed, totalWidth, totalHeight } = useMemo(() => layout(data), [data]);
  const points = useMemo(() => centres(placed), [placed]);

  const lockedZones = new Set((data.zones ?? []).filter((z) => z.locked).map((z) => z.id));
  const roomZone = new Map((data.rooms ?? []).map((r) => [r.challenge_id, r.zone_id]));

  if ((data.rooms ?? []).length === 0) {
    return <p className="mt-8 text-muted">The dungeon is empty for now.</p>;
  }

  const litRooms = (data.rooms ?? []).filter(
    (room) => room.state !== "shut" && !(data.fog_of_war && lockedZones.has(room.zone_id)),
  );

  return (
    <figure
      className="mt-4 overflow-x-auto rounded-lg border border-stone"
      aria-label="Dungeon map"
      style={{ background: PALETTE.void }}
    >
      <svg
        role="group"
        width={totalWidth}
        height={totalHeight}
        viewBox={`0 0 ${totalWidth} ${totalHeight}`}
        className="max-w-none"
      >
        <Defs width={totalWidth} height={totalHeight} />

        <rect width={totalWidth} height={totalHeight} fill={PALETTE.void} />
        <rect width={totalWidth} height={totalHeight} fill="url(#dungeon-grid)" />

        {/* Cavern floors, carved with a turbulence filter so the walls are rough
            rather than boxy. Applied per wing, not per room, to stay cheap at
            event scale. */}
        <g filter="url(#dungeon-rough)">
          {placed.map((zone) => (
            <rect
              key={`floor-${zone.zone.id}`}
              x={zone.x}
              y={zone.y + LAYOUT.zoneHeaderHeight * 0.55}
              width={zone.width}
              height={zone.height - LAYOUT.zoneHeaderHeight * 0.55}
              rx={26}
              fill={PALETTE.stoneDark}
              stroke={PALETTE.wall}
              strokeWidth={14}
              opacity={data.fog_of_war && lockedZones.has(zone.zone.id) ? 0.5 : 1}
            />
          ))}
        </g>

        {/* Torchlight, under the rooms so it pools on the floor around them. */}
        <g filter="url(#dungeon-bloom)" opacity={0.85}>
          {litRooms.map((room) => {
            const point = points.get(room.challenge_id);
            if (!point) return null;
            return (
              <circle
                key={`light-${room.challenge_id}`}
                cx={point.cx}
                cy={point.cy}
                r={room.state === "cleared" ? 118 : 86}
                fill={
                  room.state === "cleared" ? "url(#dungeon-torch)" : "url(#dungeon-coldlight)"
                }
              />
            );
          })}
        </g>

        {/* Corridors: a dark wall stroke with a lit floor drawn on top. */}
        <g>
          {(data.edges ?? []).map((edge) => {
            const from = points.get(edge.from_challenge_id);
            const to = points.get(edge.to_challenge_id);
            if (!from || !to) return null;
            const dark =
              data.fog_of_war &&
              (lockedZones.has(roomZone.get(edge.from_challenge_id) ?? "") ||
                lockedZones.has(roomZone.get(edge.to_challenge_id) ?? ""));
            return (
              <g key={`${edge.from_challenge_id}-${edge.to_challenge_id}`}>
                <line
                  x1={from.cx}
                  y1={from.cy}
                  x2={to.cx}
                  y2={to.cy}
                  stroke={PALETTE.wall}
                  strokeWidth={22}
                  strokeLinecap="round"
                />
                <line
                  x1={from.cx}
                  y1={from.cy}
                  x2={to.cx}
                  y2={to.cy}
                  stroke={dark ? PALETTE.stoneMid : PALETTE.stoneLit}
                  strokeWidth={13}
                  strokeLinecap="round"
                  opacity={dark ? 0.45 : 0.85}
                />
              </g>
            );
          })}
        </g>

        {placed.map((zone) => (
          <ZoneGroup
            key={zone.zone.id}
            placed={zone}
            unlit={data.fog_of_war && lockedZones.has(zone.zone.id)}
            onOpen={(room) => navigate(`/challenges/${room.challenge_id}`)}
          />
        ))}

        {/* Vignette last, so the edges of the world fall away into the dark. */}
        <rect
          width={totalWidth}
          height={totalHeight}
          fill="url(#dungeon-vignette)"
          pointerEvents="none"
        />
      </svg>
    </figure>
  );
}

function Defs({ width, height }: { width: number; height: number }) {
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

      {/* Rough-hewn cavern walls. Cheap enough applied to a handful of wings. */}
      <filter id="dungeon-rough" x="-8%" y="-8%" width="116%" height="116%">
        <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves={3} seed={7} />
        <feDisplacementMap in="SourceGraphic" scale={14} xChannelSelector="R" yChannelSelector="G" />
      </filter>

      <pattern id="dungeon-flagstone" width={22} height={22} patternUnits="userSpaceOnUse">
        <rect width={22} height={22} fill="none" />
        <path
          d="M 22 0 L 0 0 0 22"
          fill="none"
          stroke={PALETTE.wall}
          strokeWidth={1}
          opacity={0.45}
        />
      </pattern>

      <filter id="dungeon-bloom" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation={22} />
      </filter>

      <radialGradient id="dungeon-torch">
        <stop offset="0%" stopColor="#ffca7a" stopOpacity={0.95} />
        <stop offset="35%" stopColor={PALETTE.torch} stopOpacity={0.55} />
        <stop offset="100%" stopColor={PALETTE.torchDeep} stopOpacity={0} />
      </radialGradient>

      <radialGradient id="dungeon-coldlight">
        <stop offset="0%" stopColor={PALETTE.water} stopOpacity={0.6} />
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

      <radialGradient id="dungeon-vignette" cx="50%" cy="50%" r="75%">
        <stop offset="55%" stopColor="#000" stopOpacity={0} />
        <stop offset="100%" stopColor="#000" stopOpacity={0.75} />
      </radialGradient>

      <clipPath id="dungeon-bounds">
        <rect width={width} height={height} />
      </clipPath>
    </defs>
  );
}

function ZoneGroup({
  placed,
  unlit,
  onOpen,
}: {
  placed: PlacedZone;
  unlit: boolean;
  onOpen: (room: Room) => void;
}) {
  const { zone } = placed;
  const offsets = rowOffsets(placed);
  const condition = zone.unlock_requirements.map((r) => r.description).join(", ");

  return (
    <g transform={`translate(${placed.x}, ${placed.y})`}>
      <text
        x={LAYOUT.zonePadding}
        y={24}
        fill={unlit ? PALETTE.inkDim : PALETTE.ink}
        className="text-[15px] font-semibold"
        style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}
      >
        {zone.name}
      </text>
      <text
        x={placed.width - LAYOUT.zonePadding}
        y={24}
        textAnchor="end"
        fill={PALETTE.inkDim}
        className="text-[12px]"
      >
        {zone.cleared}/{zone.total}
        {zone.locked ? " · sealed" : ""}
      </text>

      {/* The condition is always legible: fog puts the torches out, it never
          hides what opens a wing. Also the non-colour signal that it is shut. */}
      {zone.locked && condition && (
        <g transform={`translate(${LAYOUT.zonePadding}, ${placed.height - 22})`}>
          <Lock fill={PALETTE.torch} />
          <text x={16} y={11} fill={PALETTE.torch} className="text-[12px]">
            {condition}
          </text>
        </g>
      )}

      <g
        transform={`translate(${LAYOUT.zonePadding}, ${
          LAYOUT.zoneHeaderHeight + LAYOUT.zonePadding
        })`}
      >
        {placed.rooms.map((room) => (
          <RoomNode
            key={room.challenge_id}
            room={room}
            zoneLocked={zone.locked}
            unlit={unlit}
            // Same centring the corridor endpoints use, so they line up.
            offsetX={offsets.get(room.y) ?? 0}
            onOpen={onOpen}
          />
        ))}
      </g>
    </g>
  );
}

/** Drawn rather than typed: the chain/lock emoji is missing from the system font
 *  and renders as tofu. */
function Lock({ fill }: { fill: string }) {
  return (
    <g aria-hidden="true" fill="none" stroke={fill} strokeWidth={1.6}>
      <rect x={2} y={6} width={10} height={8} rx={1.5} fill={fill} stroke="none" />
      <path d="M 4.5 6 V 4 a 2.5 2.5 0 0 1 5 0 V 6" />
    </g>
  );
}

function RoomNode({
  room,
  zoneLocked,
  unlit,
  offsetX,
  onOpen,
}: {
  room: Room;
  zoneLocked: boolean;
  unlit: boolean;
  offsetX: number;
  onOpen: (room: Room) => void;
}) {
  const shut = room.state === "shut";
  const enterable = !shut && !zoneLocked;
  const reasons = room.unlock_requirements.map((r) => r.description).join(", ");
  const dim = shut || unlit;

  // Spelled out rather than left to the lighting, so the state survives
  // greyscale and reaches a screen reader.
  const label = `${room.title} — ${
    room.state === "cleared" ? "cleared" : shut ? "shut" : "open"
  }${shut && reasons ? `, needs ${reasons}` : ""}`;

  return (
    <g
      transform={`translate(${offsetX + room.x * COLUMN}, ${room.y * ROW})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-disabled={!enterable}
      className={enterable ? "cursor-pointer" : "cursor-default"}
      onClick={() => enterable && onOpen(room)}
      onKeyDown={(event) => {
        if (enterable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onOpen(room);
        }
      }}
    >
      {/* Chamber: carved wall, then flagstone floor. */}
      <rect
        x={-4}
        y={-4}
        width={LAYOUT.roomWidth + 8}
        height={LAYOUT.roomHeight + 8}
        rx={10}
        fill={PALETTE.wall}
        opacity={0.9}
      />
      <rect
        width={LAYOUT.roomWidth}
        height={LAYOUT.roomHeight}
        rx={7}
        fill={dim ? "url(#dungeon-floor-dark)" : "url(#dungeon-floor-lit)"}
      />
      {/* Flagstones, so a chamber reads as built rather than painted. */}
      <rect
        width={LAYOUT.roomWidth}
        height={LAYOUT.roomHeight}
        rx={7}
        fill="url(#dungeon-flagstone)"
      />
      {/* A lip of light along the top edge, as if the torch is above. */}
      <path
        d={`M 7 1 H ${LAYOUT.roomWidth - 7}`}
        stroke={dim ? PALETTE.stoneMid : PALETTE.torch}
        strokeWidth={2}
        opacity={dim ? 0.35 : 0.5}
        strokeLinecap="round"
      />

      {room.state === "cleared" && (
        <circle cx={LAYOUT.roomWidth - 16} cy={17} r={4.5} fill={PALETTE.torch} />
      )}
      {shut && (
        <g transform={`translate(${LAYOUT.roomWidth - 26}, 10)`}>
          <Lock fill={PALETTE.inkDim} />
        </g>
      )}

      <text
        x={12}
        y={30}
        fill={dim ? PALETTE.inkDim : PALETTE.ink}
        className="text-[13px] font-semibold"
      >
        {room.title.length > 20 ? `${room.title.slice(0, 19)}…` : room.title}
      </text>
      <text x={12} y={51} fill={PALETTE.inkDim} className="text-[11px]">
        {room.state === "cleared" ? "cleared" : shut ? "shut" : `${room.value} XP`}
      </text>
    </g>
  );
}
