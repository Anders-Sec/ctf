import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  candidateImageUrl,
  chooseCandidate,
  getBuilder,
  listJobs,
  startJob,
  AXIS_LABEL,
  type Job,
  type TraitAxis,
} from "../api/portraits";
import { bumpAvatars } from "./avatarVersion";
import ErrorMessage from "./ErrorMessage";
import Spinner from "./Spinner";

/**
 * Building a portrait out of enums (spec 074 §2).
 *
 * Every choice here is a **key** from an authored list. There is no text box,
 * anywhere, and that is the single largest decision in the spec: SDXL Turbo
 * runs at `guidance_scale=0.0` and ignores negative prompts, so the usual NSFW
 * control does not exist and the input vocabulary has to be the filter. It also
 * makes for better portraits — eight fragments tuned once beat two hundred
 * people's first attempt at prompt engineering.
 *
 * The whole component is behind `available`: when the host is dark it is simply
 * not rendered, and everything spec 073 built — crests, accessories, the
 * editor — carries on with no GPU at all.
 */
const SURPRISE_LABEL = "Surprise me";

export default function PortraitBuilder() {
  const queryClient = useQueryClient();
  const builder = useQuery({ queryKey: ["portraits", "builder"], queryFn: getBuilder });
  const jobs = useQuery({ queryKey: ["portraits", "jobs"], queryFn: listJobs });

  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [job, setJob] = useState<Job | null>(null);

  // Your own class, pre-selected: what ties a portrait to progression rather
  // than to a costume box.
  useEffect(() => {
    if (builder.data?.default_class_look && chosen.class_look === undefined) {
      setChosen((current) => ({ ...current, class_look: builder.data.default_class_look! }));
    }
  }, [builder.data, chosen.class_look]);

  // A reloaded page finds its grid again rather than losing a generation.
  useEffect(() => {
    if (!job && jobs.data?.length) setJob(jobs.data[0]!);
  }, [jobs.data, job]);

  const generate = useMutation({
    mutationFn: () => startJob(chosen),
    onSuccess: async (result) => {
      setJob(result);
      await queryClient.invalidateQueries({ queryKey: ["portraits"] });
    },
  });

  const adopt = useMutation({
    mutationFn: (candidateId: string) => chooseCandidate(candidateId),
    onSuccess: async () => {
      setJob(null);
      await queryClient.invalidateQueries({ queryKey: ["portraits"] });
      await queryClient.invalidateQueries({ queryKey: ["avatar"] });
      // The rendered avatar changed behind an unchanged URL. Without this the
      // new portrait shows up in the editor preview and nowhere else.
      bumpAvatars();
    },
  });

  if (builder.isPending) return <Spinner label="Asking the artist…" />;
  const data = builder.data;
  if (!data) return null;

  // Not offered rather than offered and failing (spec 074 §7).
  if (!data.available) return null;

  const surprise = () => {
    const picked: Record<string, string> = {};
    for (const axis of data.axes) {
      const option = axis.options[Math.floor(Math.random() * axis.options.length)];
      if (option) picked[axis.axis] = option.key;
    }
    setChosen(picked);
  };

  const spent = data.remaining <= 0;

  return (
    <div className="rounded-lg border border-border-strong bg-surface-raised p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Have one painted
        </h3>
        <p className="text-xs text-content-muted tabular-nums">
          {data.remaining} left · {data.candidates_per_job} to choose from
        </p>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {data.axes.map((axis) => (
          <label key={axis.axis} className="text-sm">
            {AXIS_LABEL[axis.axis as TraitAxis] ?? axis.axis}
            <select
              value={chosen[axis.axis] ?? ""}
              onChange={(event) =>
                setChosen((current) => {
                  const next = { ...current };
                  if (event.target.value) next[axis.axis] = event.target.value;
                  else delete next[axis.axis];
                  return next;
                })
              }
              className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5"
            >
              {/* Leaving an axis unset is fine: a portrait with no stated
                  background is a portrait with no stated background. */}
              <option value="">Any</option>
              {axis.options.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => generate.mutate()}
          disabled={generate.isPending || spent}
          className="rounded bg-accent-strong px-4 py-2 text-sm font-medium text-accent-content disabled:opacity-50"
        >
          {generate.isPending ? "Painting…" : "Paint it"}
        </button>
        <button
          type="button"
          onClick={surprise}
          className="rounded border border-border px-4 py-2 text-sm"
        >
          {SURPRISE_LABEL}
        </button>
        {spent && (
          <span className="text-xs text-content-muted">
            You have used your portraits. Loot grants more.
          </span>
        )}
      </div>

      <ErrorMessage error={generate.error ?? adopt.error} />

      {job?.state === "failed" && (
        <p role="alert" className="mt-3 text-sm text-content-muted">
          That did not come out. Try different choices.
        </p>
      )}

      {job && job.candidates.length > 0 && (
        <div className="mt-4">
          <p className="text-sm">Pick one.</p>
          <ul className="mt-2 flex flex-wrap gap-3">
            {job.candidates.map((candidate) => (
              <li key={candidate.id}>
                <button
                  type="button"
                  onClick={() => adopt.mutate(candidate.id)}
                  disabled={adopt.isPending}
                  aria-label={`Use portrait ${candidate.seed}`}
                  className="overflow-hidden rounded-lg border-2 border-border hover:border-accent disabled:opacity-50"
                >
                  <img
                    src={candidateImageUrl(candidate.id)}
                    alt=""
                    width={120}
                    height={120}
                    className="block h-[120px] w-[120px] object-cover"
                  />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
