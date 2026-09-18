import { useSyncExternalStore } from "react";

/**
 * One version number every `Avatar` in the app hangs off (spec 073).
 *
 * The avatar URL is `/api/users/{id}/avatar` — the same string before and after
 * you change your face. The browser had no way to know the bytes behind it
 * moved, so a new portrait showed up **only in the editor's preview**, which
 * was the one place carrying its own `?v=` buster. Everywhere else kept the old
 * crest until the cache expired.
 *
 * Bumping this re-renders every avatar with a fresh query string, so your own
 * change is immediate across the scoreboard, the roster, the inbox and the nav.
 *
 * It is deliberately **per browser and not persisted**: it fixes the view of
 * the person who made the change. Other people pick it up on their next
 * revalidation, which the endpoint's short `max-age` and its ETag make cheap.
 */
let version = 0;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): number {
  return version;
}

/** Call after anything that changes the current user's rendered avatar. */
export function bumpAvatars(): void {
  version = Date.now();
  for (const listener of listeners) listener();
}

export function useAvatarVersion(): number {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** The `src` for a user's avatar at the current version. */
export function versionedAvatarUrl(base: string, current: number): string {
  // Left clean until something actually changes, so a first page load is not
  // one cache-missing URL per roster row.
  return current === 0 ? base : `${base}?v=${current}`;
}
