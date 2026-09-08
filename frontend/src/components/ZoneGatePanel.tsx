import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  addCategoryGate,
  removeGate,
  type GraphZone,
  type RequirementKind,
} from "../api/dungeon";
import type { Skill } from "../api/adminSkills";
import { ApiError } from "../api/client";
import ErrorMessage from "./ErrorMessage";

/**
 * Editing what opens a zone (spec 022).
 *
 * A connection *is* a requirement: the map draws a corridor for any gate
 * carrying a source zone, and nothing else creates one. So adding a connection
 * and changing a requirement are the same act, and this is one panel rather
 * than two.
 *
 * Gates with no source zone — XP, player level, skill level — draw no corridor
 * but are shown here all the same. Leaving them out would mean an admin sees a
 * sealed zone with no visible reason for it.
 */

/** What each gate type needs filled in. Drives the form, so a type can never
 *  offer a field the server would reject. */
const NEEDS: Record<RequirementKind, { source?: "zone" | "skill"; threshold?: string }> = {
  percent_in_category: { source: "zone", threshold: "Percent to clear" },
  solves_in_category: { source: "zone", threshold: "Challenges to clear" },
  skill_level: { source: "skill", threshold: "Skill level" },
  min_xp: { threshold: "XP" },
  player_level: { threshold: "Player level" },
  // Challenge prerequisites are edited on the challenge, not the map (014/017).
  challenge_solved: {},
};

const LABELS: Record<RequirementKind, string> = {
  percent_in_category: "Percent of a zone cleared",
  solves_in_category: "Challenges cleared in a zone",
  skill_level: "Skill level",
  min_xp: "Total XP",
  player_level: "Player level",
  challenge_solved: "A specific challenge solved",
};

const OFFERED: RequirementKind[] = [
  "percent_in_category",
  "solves_in_category",
  "min_xp",
  "player_level",
  "skill_level",
];

export default function ZoneGatePanel({
  zone,
  zones,
  skills,
  eventRunning,
  onClose,
}: {
  zone: GraphZone;
  zones: GraphZone[];
  skills: Skill[];
  eventRunning: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);

  const [kind, setKind] = useState<RequirementKind>("percent_in_category");
  const [sourceId, setSourceId] = useState("");
  const [threshold, setThreshold] = useState("100");

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["map-graph"] });
    queryClient.invalidateQueries({ queryKey: ["map"] });
  };

  const add = useMutation({
    mutationFn: () => {
      const needs = NEEDS[kind];
      return addCategoryGate(zone.id, {
        requirement_type: kind,
        required_category_id: needs.source === "zone" ? sourceId : null,
        required_skill_id: needs.source === "skill" ? sourceId : null,
        threshold: needs.threshold ? Number(threshold) : null,
      });
    },
    onSuccess: refresh,
  });
  const drop = useMutation({
    mutationFn: (gateId: string) => removeGate(gateId),
    onSuccess: refresh,
  });

  useEffect(() => {
    heading.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const needs = NEEDS[kind];
  const others = zones.filter((z) => z.id !== zone.id);
  const incomplete =
    (needs.source && !sourceId) || (needs.threshold && threshold.trim() === "");

  return (
    <div
      role="dialog"
      aria-label={`${zone.name} gates`}
      className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-stone bg-parchment p-5 shadow-xl"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold">
          {zone.name}
        </h2>
        <button onClick={onClose} className="text-sm hover:underline" aria-label="Close">
          Close
        </button>
      </div>
      <p className="mt-1 text-sm text-muted">
        {zone.published_challenges} published{" "}
        {zone.published_challenges === 1 ? "challenge" : "challenges"}
      </p>

      {eventRunning && (
        // Worth saying plainly: this is a pre-event tool, and a gate added now
        // re-seals a zone for players who already had it open.
        <p className="mt-3 rounded border border-torch/40 bg-torch/10 px-3 py-2 text-sm">
          The event is running. Changing gates now re-locks zones for players who
          have already opened them.
        </p>
      )}

      {!zone.reachable && (
        <p className="mt-3 rounded border border-stone bg-white/50 px-3 py-2 text-sm">
          No path reaches this zone from a starting zone, so nobody can open it.
        </p>
      )}

      <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-muted">
        Opens when
      </h3>
      {zone.gates.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          Nothing — this zone is open from the start.
        </p>
      ) : (
        <ul className="mt-2 space-y-2">
          {zone.gates.map((gate) => (
            <li
              key={gate.id}
              className="flex items-start justify-between gap-3 rounded border border-stone bg-white/50 px-3 py-2"
            >
              <span className="text-sm">
                {gate.description}
                {gate.source_has_no_challenges && (
                  <em className="mt-1 block not-italic text-xs text-muted">
                    {gate.required_category_name} has nothing published, so this
                    can never be met.
                  </em>
                )}
              </span>
              <button
                onClick={() => drop.mutate(gate.id)}
                disabled={drop.isPending}
                className="shrink-0 text-sm hover:underline disabled:opacity-50"
                aria-label={`Remove gate: ${gate.description}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-6 text-sm font-semibold uppercase tracking-wide text-muted">
        Add a gate
      </h3>
      <form
        className="mt-2 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate();
        }}
      >
        <label className="block text-sm">
          <span className="mb-1 block text-muted">Condition</span>
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as RequirementKind);
              setSourceId("");
            }}
            className="w-full rounded border border-stone bg-white/70 px-2 py-1.5"
            aria-label="Condition"
          >
            {OFFERED.map((option) => (
              <option key={option} value={option}>
                {LABELS[option]}
              </option>
            ))}
          </select>
        </label>

        {needs.source === "zone" && (
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Source zone</span>
            <select
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              className="w-full rounded border border-stone bg-white/70 px-2 py-1.5"
              aria-label="Source zone"
            >
              <option value="">Choose a zone…</option>
              {others.map((other) => (
                <option key={other.id} value={other.id}>
                  {other.name}
                  {other.published_challenges === 0 ? " (empty)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}

        {needs.source === "skill" && (
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Skill</span>
            <select
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              className="w-full rounded border border-stone bg-white/70 px-2 py-1.5"
              aria-label="Skill"
            >
              <option value="">Choose a skill…</option>
              {skills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {needs.threshold && (
          <label className="block text-sm">
            <span className="mb-1 block text-muted">{needs.threshold}</span>
            <input
              type="number"
              min={1}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              className="w-full rounded border border-stone bg-white/70 px-2 py-1.5"
              aria-label={needs.threshold}
            />
          </label>
        )}

        {/* A refused cycle is the one case where the server's own prose beats
            ours: it names the loop, and "invalid requirement" would leave an
            admin hunting through 22 zones for it. */}
        {add.error instanceof ApiError && add.error.code === "requirement_cycle" ? (
          <p role="alert" className="rounded border border-torch bg-torch/15 px-3 py-2 text-sm">
            {add.error.message}
          </p>
        ) : (
          <ErrorMessage error={add.error ?? drop.error} />
        )}

        <button
          type="submit"
          disabled={add.isPending || Boolean(incomplete)}
          className="rounded border border-stone px-4 py-2 text-sm disabled:opacity-50"
        >
          {add.isPending ? "Adding…" : "Add gate"}
        </button>
      </form>
    </div>
  );
}
