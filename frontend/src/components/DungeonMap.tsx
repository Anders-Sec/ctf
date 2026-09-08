import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import type { DungeonMap as MapData, Room, Zone } from "../api/dungeon";

/**
 * The dungeon map (spec 017) — a view over the challenges the player can already
 * see. Every lock it draws was decided by the backend; nothing here gates.
 *
 * Zones (categories) are wings, packed into rows. Rooms sit at server-supplied
 * grid coordinates, so every player sees the same dungeon. Locked wings are
 * greyed but stay readable — fog dims, it never withholds.
 *
 * All the tuning lives in LAYOUT below.
 */
const LAYOUT = {
  roomWidth: 150,
  roomHeight: 46,
  columnGap: 26,
  rowGap: 44,
  zonePadding: 16,
  zoneHeaderHeight: 34,
  zoneGap: 28,
  /** Wings wrap to a new row past this width. */
  maxRowWidth: 1180,
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
  let rowX = 0;
  let rowY = 0;
  let rowHeight = 0;

  for (const zone of zones) {
    const rooms = roomsByZone.get(zone.id) ?? [];
    const columns = Math.max(1, ...rooms.map((r) => r.x + 1));
    const depth = Math.max(1, ...rooms.map((r) => r.y + 1));
    const width = columns * COLUMN - LAYOUT.columnGap + LAYOUT.zonePadding * 2;
    const height =
      depth * ROW - LAYOUT.rowGap + LAYOUT.zonePadding * 2 + LAYOUT.zoneHeaderHeight;

    if (rowX > 0 && rowX + width > LAYOUT.maxRowWidth) {
      rowY += rowHeight + LAYOUT.zoneGap;
      rowX = 0;
      rowHeight = 0;
    }

    placed.push({ zone, rooms, x: rowX, y: rowY, width, height });
    rowX += width + LAYOUT.zoneGap;
    rowHeight = Math.max(rowHeight, height);
  }

  const totalWidth = Math.max(...placed.map((p) => p.x + p.width), 1);
  const totalHeight = rowY + rowHeight;
  return { placed, totalWidth, totalHeight };
}

/** Absolute centre of a room, for drawing corridors between wings. */
function centres(placed: PlacedZone[]) {
  const points = new Map<string, { cx: number; cy: number }>();
  for (const zone of placed) {
    for (const room of zone.rooms) {
      points.set(room.challenge_id, {
        cx: zone.x + LAYOUT.zonePadding + room.x * COLUMN + LAYOUT.roomWidth / 2,
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

  if ((data.rooms ?? []).length === 0) {
    return <p className="mt-8 text-muted">The dungeon is empty for now.</p>;
  }

  return (
    <figure className="mt-4 overflow-x-auto" aria-label="Dungeon map">
      <svg
        role="group"
        width={totalWidth}
        height={totalHeight}
        viewBox={`0 0 ${totalWidth} ${totalHeight}`}
        className="max-w-none"
      >
        {/* Corridors first so rooms sit on top of them. */}
        <g>
          {(data.edges ?? []).map((edge) => {
            const from = points.get(edge.from_challenge_id);
            const to = points.get(edge.to_challenge_id);
            if (!from || !to) return null;
            return (
              <line
                key={`${edge.from_challenge_id}-${edge.to_challenge_id}`}
                x1={from.cx}
                y1={from.cy}
                x2={to.cx}
                y2={to.cy}
                className="stroke-stone"
                strokeWidth={2}
              />
            );
          })}
        </g>

        {placed.map((zone) => (
          <ZoneGroup
            key={zone.zone.id}
            placed={zone}
            dimmed={data.fog_of_war && lockedZones.has(zone.zone.id)}
            onOpen={(room) => navigate(`/challenges/${room.challenge_id}`)}
          />
        ))}
      </svg>
    </figure>
  );
}

function ZoneGroup({
  placed,
  dimmed,
  onOpen,
}: {
  placed: PlacedZone;
  dimmed: boolean;
  onOpen: (room: Room) => void;
}) {
  const { zone } = placed;
  const condition = zone.unlock_requirements.map((r) => r.description).join(", ");

  return (
    <g transform={`translate(${placed.x}, ${placed.y})`} opacity={dimmed ? 0.45 : 1}>
      <rect
        width={placed.width}
        height={placed.height}
        rx={10}
        className={zone.locked ? "fill-stone/10 stroke-stone" : "fill-white/40 stroke-stone"}
        strokeWidth={1}
        strokeDasharray={zone.locked ? "6 4" : undefined}
      />
      <text x={LAYOUT.zonePadding} y={22} className="fill-ink text-[13px] font-semibold">
        {zone.name}
      </text>
      <text
        x={placed.width - LAYOUT.zonePadding}
        y={22}
        textAnchor="end"
        className="fill-muted text-[11px]"
      >
        {zone.cleared}/{zone.total}
        {zone.locked ? " · locked" : ""}
      </text>
      {/* The condition is always legible: fog dims, it never hides what opens a
          wing. Also the non-colour signal that this zone is shut. */}
      {zone.locked && condition && (
        <text
          x={LAYOUT.zonePadding}
          y={placed.height - 8}
          className="fill-muted text-[11px]"
        >
          {condition}
        </text>
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
            onOpen={onOpen}
          />
        ))}
      </g>
    </g>
  );
}

function RoomNode({
  room,
  zoneLocked,
  onOpen,
}: {
  room: Room;
  zoneLocked: boolean;
  onOpen: (room: Room) => void;
}) {
  const shut = room.state === "shut";
  const enterable = !shut && !zoneLocked;
  const reasons = room.unlock_requirements.map((r) => r.description).join(", ");

  // Spelled out rather than left to colour alone, so the state survives greyscale
  // and reaches a screen reader.
  const label = `${room.title} — ${
    room.state === "cleared" ? "cleared" : shut ? "shut" : "open"
  }${shut && reasons ? `, needs ${reasons}` : ""}`;

  const fill = room.state === "cleared" ? "fill-ink" : shut ? "fill-stone/20" : "fill-white";
  const textClass =
    room.state === "cleared" ? "fill-parchment" : shut ? "fill-muted" : "fill-ink";

  return (
    <g
      transform={`translate(${room.x * COLUMN}, ${room.y * ROW})`}
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
      <rect
        width={LAYOUT.roomWidth}
        height={LAYOUT.roomHeight}
        rx={7}
        className={`${fill} stroke-stone`}
        strokeWidth={room.state === "cleared" ? 0 : 1}
        strokeDasharray={shut ? "5 3" : undefined}
      />
      <text
        x={10}
        y={19}
        className={`${textClass} text-[12px] font-medium`}
      >
        {room.title.length > 20 ? `${room.title.slice(0, 19)}…` : room.title}
      </text>
      <text x={10} y={34} className={`${textClass} text-[10px] opacity-70`}>
        {room.state === "cleared" ? "cleared" : shut ? "shut" : `${room.value} XP`}
      </text>
    </g>
  );
}
