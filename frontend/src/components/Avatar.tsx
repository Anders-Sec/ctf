import { avatarUrl } from "../api/auth";

/**
 * One image, because there is now only one rendering path (spec 073 §3).
 *
 * This used to branch: an `<img>` for anyone with a cached Entra photo, and a
 * coloured circle with their initial for everybody else — which failed the job
 * it existed for, since twenty people whose names begin with S were twenty
 * identical circles.
 *
 * The server now renders *every* avatar, including a procedural heraldic crest
 * for anyone with no photo, so there is no "no avatar" case left to handle here
 * and no second implementation to keep in step with the first.
 */
export default function Avatar({
  userId,
  displayName,
  size = 40,
}: {
  userId: string;
  displayName: string;
  size?: number;
}) {
  return (
    <img
      src={avatarUrl(userId)}
      // Decorative wherever it sits beside the name it belongs to, which is
      // everywhere it is currently used — a roster row reading "Grix, Grix" is
      // worse for a screen reader than one that reads "Grix".
      alt=""
      width={size}
      height={size}
      loading="lazy"
      // The name still reaches a sighted user who hovers, which is the only
      // case where the image is doing work the text beside it is not.
      title={displayName}
      className="shrink-0 rounded-full bg-surface-sunken object-cover"
      style={{ width: size, height: size }}
    />
  );
}
