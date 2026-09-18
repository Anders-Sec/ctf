import { NOTIFICATION_KINDS, type NotificationKind } from "../api/notifications";

/**
 * What each kind is, and which half of the inbox it belongs to (spec 065 §2).
 *
 * The split is by **audience**, not by kind alone. A player checking "did I
 * level" and a player checking "what did I miss" are doing different jobs, and
 * one undifferentiated stream makes both worse — which is the brief's own worry
 * about a meaningless feed nobody reads.
 *
 * Grouping lives here rather than on the server: adding a kind later needs a
 * line in this map, not a migration. A test asserts every kind appears exactly
 * once, so a tenth cannot quietly go missing from both tabs.
 */
export type InboxTab = "yours" | "event";

export interface KindMeta {
  label: string;
  icon: string;
  tab: InboxTab;
  /** Text colour. Never the only carrier — the label rides beside it (§3). */
  tone: string;
  /** Whether it interrupts, or just lands in the inbox (§5). */
  toasts: boolean;
}

export const KIND_META: Record<NotificationKind, KindMeta> = {
  achievement: {
    label: "Achievement",
    icon: "★",
    tab: "yours",
    tone: "text-success",
    toasts: true,
  },
  level_up: {
    label: "Level up",
    icon: "▲",
    tab: "yours",
    tone: "text-accent-strong",
    toasts: true,
  },
  class_unlocked: {
    label: "Class",
    icon: "◈",
    tab: "yours",
    tone: "text-accent-strong",
    toasts: true,
  },
  zone_unlocked: {
    label: "Zone",
    icon: "⌸",
    tab: "yours",
    tone: "text-accent-strong",
    toasts: true,
  },
  ability_milestone: {
    label: "Ability",
    icon: "◆",
    tab: "yours",
    tone: "text-accent-strong",
    toasts: true,
  },

  announcement: {
    label: "Announcement",
    icon: "❖",
    tab: "event",
    tone: "text-warning",
    // An admin saying "the network is back" is worth interrupting for.
    toasts: true,
  },
  boss_kill: {
    label: "Boss kill",
    icon: "☠",
    tab: "event",
    tone: "text-info",
    // Interesting once and irrelevant the forty-first time. At 200 players this
    // is the loudest thing on the platform and the least about you (§5).
    toasts: false,
  },
  dispatch: {
    label: "Dispatch",
    icon: "▤",
    tab: "event",
    tone: "text-info",
    toasts: false,
  },
  system: {
    // Anything not clearly about your progress belongs with the news, which
    // keeps "Yours" meaning exactly one thing (§9.1).
    label: "System",
    icon: "▸",
    tab: "event",
    tone: "text-info",
    toasts: false,
  },
};

export function metaFor(kind: string): KindMeta {
  return KIND_META[kind as NotificationKind] ?? KIND_META.system;
}

export const KINDS_IN: Record<InboxTab, NotificationKind[]> = {
  yours: NOTIFICATION_KINDS.filter((kind) => KIND_META[kind].tab === "yours"),
  event: NOTIFICATION_KINDS.filter((kind) => KIND_META[kind].tab === "event"),
};
