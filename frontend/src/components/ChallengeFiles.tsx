import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { deleteArtifact, uploadArtifact } from "../api/adminChallenges";
import type { Artifact } from "../api/challenges";
import ErrorMessage from "./ErrorMessage";

/**
 * The Files panel in the challenge editor (spec 063 §4).
 *
 * The upload and delete endpoints already existed; this is the UI that was
 * missing. Its real job is the **reference**: an author needs
 * `![name](artifact:name.png)` and has no way to know it otherwise.
 *
 * Copy *and* insert, because the brief asked for both. Insert lands at the
 * cursor rather than at the end, since the end of a description is almost never
 * where a picture belongs.
 */
export function referenceFor(artifact: Artifact): string {
  const isImage = artifact.content_type.startsWith("image/");
  const label = artifact.filename.replace(/\.[^.]+$/, "");
  // An image embeds; anything else is a link, so the file is offered where it
  // is mentioned rather than only in a list below (§9.1).
  return isImage
    ? `![${label}](artifact:${artifact.filename})`
    : `[${label}](artifact:${artifact.filename})`;
}

export default function ChallengeFiles({
  challengeId,
  artifacts,
  onInsert,
}: {
  challengeId: string;
  artifacts: Artifact[];
  /** Drops a reference into the description at the cursor. */
  onInsert: (reference: string) => void;
}) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-challenge", challengeId] });
    queryClient.invalidateQueries({ queryKey: ["admin-challenges"] });
  };

  const upload = useMutation({
    mutationFn: (file: File) => uploadArtifact(challengeId, file),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (artifactId: string) => deleteArtifact(challengeId, artifactId),
    onSuccess: refresh,
  });

  const copy = async (artifact: Artifact) => {
    const reference = referenceFor(artifact);
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(artifact.id);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      // No clipboard permission, or an insecure origin. Insert still works, and
      // the reference is on screen to be typed.
      setCopied(null);
    }
  };

  // Two files with one name resolve to the first, so say so here — this is the
  // moment it can actually be fixed (§3).
  const duplicates = new Set(
    artifacts
      .map((artifact) => artifact.filename)
      .filter((name, index, all) => all.indexOf(name) !== index),
  );

  return (
    <section className="mt-4 rounded border border-border bg-surface-raised p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-muted">
          Files
        </h3>
        <label className="cursor-pointer text-sm underline">
          {upload.isPending ? "Uploading…" : "Upload a file"}
          <input
            ref={fileInput}
            type="file"
            className="sr-only"
            aria-label="Upload a file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
              // Cleared so the same file can be picked twice in a row.
              event.target.value = "";
            }}
          />
        </label>
      </div>

      <ErrorMessage error={upload.error ?? remove.error} />

      {artifacts.length === 0 ? (
        <p className="mt-2 text-sm text-content-muted">
          None yet. Upload one and its reference appears here to drop into the
          description.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {artifacts.map((artifact) => (
            <li key={artifact.id} className="rounded border border-border px-3 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="min-w-0">
                  <span className="text-sm font-medium">{artifact.filename}</span>
                  <span className="ml-2 text-xs text-content-muted">
                    {artifact.content_type} · {(artifact.size_bytes / 1024).toFixed(1)} KB
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => remove.mutate(artifact.id)}
                  disabled={remove.isPending}
                  className="text-xs text-danger underline disabled:opacity-50"
                >
                  Delete
                </button>
              </div>

              {duplicates.has(artifact.filename) && (
                <p className="mt-1 text-xs text-warning">
                  Another file has this name. A reference to it resolves to
                  whichever was uploaded first.
                </p>
              )}

              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-xs">
                  {referenceFor(artifact)}
                </code>
                <button
                  type="button"
                  onClick={() => copy(artifact)}
                  className="text-xs underline"
                >
                  {copied === artifact.id ? "Copied" : "Copy"}
                </button>
                <button
                  type="button"
                  onClick={() => onInsert(referenceFor(artifact))}
                  className="text-xs underline"
                >
                  Insert
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
