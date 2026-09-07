import { useCallback, useSyncExternalStore } from "react";

/**
 * Player view vs admin view, CTFd-style (spec 013).
 *
 * Everyone — admins included — defaults to the player navigation, so an admin
 * sees the event the way a player does. An admin can flip to an admin-only nav
 * and back. The choice is per-device and survives reloads, so an admin building
 * the event is not flipped back to player view on every refresh.
 *
 * Purely presentational: the server gates the admin routes regardless of what
 * this returns, so a stale or forged value changes what is shown, never what is
 * allowed.
 */
const KEY = "ctf.adminView";

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    // Private windows and blocked storage throw; default to player view.
    return false;
  }
}

// A tiny external store so every consumer re-renders together when the flag
// flips, without a context provider for one boolean.
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function write(value: boolean): void {
  try {
    localStorage.setItem(KEY, value ? "1" : "0");
  } catch {
    // Ignore — the in-memory listeners still fire, so the nav updates for this
    // session even when it cannot be persisted.
  }
  for (const listener of listeners) listener();
}

export function useAdminView(): [boolean, (value: boolean) => void] {
  const adminView = useSyncExternalStore(subscribe, read, () => false);
  const setAdminView = useCallback((value: boolean) => write(value), []);
  return [adminView, setAdminView];
}
