import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import type { Components } from "react-markdown";

import type { Artifact } from "../api/challenges";

/**
 * A challenge description (spec 063).
 *
 * A sibling of `Markdown` rather than a parameter on it. That one renders the
 * System AI's replies and is tuned for model output — 0.8rem text, headings
 * flattened to paragraphs, and links stripped entirely because "a model-authored
 * href is an open redirect with extra steps". A challenge body is written by the
 * admin and wants the opposite of all three.
 *
 * **`rehype-raw` stays off**, exactly as it is there. The reason differs — this
 * is trusted input — but the rule is worth keeping unconditional: the day
 * somebody wires descriptions to an import from a shared drive, the question
 * should not have to be re-asked.
 *
 * No syntax highlighting. A highlighter is a heavy dependency and per-language
 * config, and what these descriptions need is a JSON blob that keeps its shape.
 */

/** What an author writes before any upload exists: `artifact:topology.png`. */
const ARTIFACT_PREFIX = "artifact:";

/**
 * Resolves `artifact:name` against this challenge's own files, by **filename**.
 *
 * Filename rather than id for the reason spec 059 keys stars on slugs: an author
 * types this by hand, into a CSV or a textarea, before the file is uploaded. A
 * UUID is not something a person writes, and it changes if a file is deleted and
 * re-added — the filename is what they already have in front of them.
 *
 * Returns null when nothing matches, so the caller can degrade rather than
 * render a broken-image icon that looks like the platform fell over.
 */
export function resolveArtifact(
  href: string | undefined,
  artifacts: Artifact[],
  urlFor: (artifactId: string) => string,
): string | null {
  if (!href?.startsWith(ARTIFACT_PREFIX)) return null;
  const wanted = href.slice(ARTIFACT_PREFIX.length).trim();
  // First match wins; the editor flags a duplicate filename, which is the moment
  // it can actually be fixed.
  const artifact = artifacts.find((candidate) => candidate.filename === wanted);
  return artifact ? urlFor(artifact.id) : null;
}

/**
 * Lets `artifact:` through the URL sanitiser, and nothing else.
 *
 * `react-markdown` strips unknown schemes by default, which is why it has to be
 * asked: the default would replace `artifact:topology.png` with an empty string
 * before any component saw it. Everything that is *not* our own scheme still
 * goes through `defaultUrlTransform`, so `javascript:` is refused exactly as it
 * was.
 */
function allowArtifactScheme(url: string): string {
  return url.startsWith(ARTIFACT_PREFIX) ? url : defaultUrlTransform(url);
}

export default function ChallengeBody({
  children,
  artifacts = [],
  urlFor,
}: {
  children: string;
  artifacts?: Artifact[];
  /** How to turn an artifact id into a URL. Passed in so the admin preview can
   *  render the same markdown without a live challenge behind it. */
  urlFor?: (artifactId: string) => string;
}) {
  const resolve = (href: string | undefined) =>
    urlFor ? resolveArtifact(href, artifacts, urlFor) : null;

  const components: Components = {
    p: ({ children: kids }) => <p className="mb-3 last:mb-0">{kids}</p>,
    strong: ({ children: kids }) => <strong className="font-semibold">{kids}</strong>,
    em: ({ children: kids }) => <em className="italic">{kids}</em>,
    ul: ({ children: kids }) => <ul className="mb-3 list-disc pl-5 last:mb-0">{kids}</ul>,
    ol: ({ children: kids }) => <ol className="mb-3 list-decimal pl-5 last:mb-0">{kids}</ol>,
    li: ({ children: kids }) => <li className="mb-1">{kids}</li>,
    blockquote: ({ children: kids }) => (
      <blockquote className="mb-3 border-l-2 border-accent/60 pl-3 last:mb-0">{kids}</blockquote>
    ),
    h1: ({ children: kids }) => <h2 className="mb-2 mt-4 text-lg font-semibold">{kids}</h2>,
    h2: ({ children: kids }) => <h2 className="mb-2 mt-4 text-lg font-semibold">{kids}</h2>,
    h3: ({ children: kids }) => <h3 className="mb-2 mt-3 font-semibold">{kids}</h3>,
    hr: () => <hr className="my-4 border-border" />,
    code: ({ children: kids }) => (
      <code className="rounded bg-surface-sunken px-1 py-0.5 font-mono text-sm">{kids}</code>
    ),
    // A JSON blob that keeps its shape. Scrolls rather than wraps, because a
    // wrapped payload is a payload you cannot read.
    pre: ({ children: kids }) => (
      <pre className="mb-3 overflow-x-auto rounded bg-surface-sunken p-3 text-sm last:mb-0">
        {kids}
      </pre>
    ),

    img: ({ src, alt }) => {
      const resolved = resolve(typeof src === "string" ? src : undefined);
      if (!resolved) {
        // A missing picture reads as a gap in the prose, not as a failure.
        return <span className="text-sm italic text-content-muted">{alt}</span>;
      }
      return (
        <img
          src={resolved}
          alt={alt ?? ""}
          className="my-3 max-w-full rounded border border-border"
        />
      );
    },

    a: ({ href, children: kids }) => {
      const resolved = resolve(href);
      if (resolved) {
        // The file, offered where it is mentioned rather than in a list below
        // (spec 063 §9.1). `download` forces a save even though images are
        // served inline.
        return (
          <a href={resolved} download className="underline">
            {kids}
          </a>
        );
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="underline"
        >
          {kids}
        </a>
      );
    },
  };

  return (
    <ReactMarkdown components={components} urlTransform={allowArtifactScheme}>
      {children}
    </ReactMarkdown>
  );
}
