import { avatarUrl } from "../api/auth";

/**
 * Guests have no Entra photo, so they get a deterministic colour and initial
 * derived from their id — enough to tell members apart in a roster. Phase 3
 * replaces this with real art.
 */
function initialsColor(userId: string): string {
  let hash = 0;
  for (const char of userId) {
    hash = (hash * 31 + char.charCodeAt(0)) % 360;
  }
  return `hsl(${hash} 45% 42%)`;
}

export default function Avatar({
  userId,
  displayName,
  hasAvatar,
  size = 40,
}: {
  userId: string;
  displayName: string;
  hasAvatar: boolean;
  size?: number;
}) {
  const dimension = { width: size, height: size };

  if (hasAvatar) {
    return (
      <img
        src={avatarUrl(userId)}
        alt=""
        className="rounded-full object-cover"
        style={dimension}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className="inline-flex items-center justify-center rounded-full font-semibold text-white"
      style={{ ...dimension, backgroundColor: initialsColor(userId), fontSize: size * 0.4 }}
    >
      {displayName.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
