import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";

/**
 * Renders the System AI's replies (spec 033).
 *
 * The approved prompt formats its notification blocks as markdown blockquotes
 * with bold and italic, and the gate messages do the same — rendering them as
 * plain text would show the player raw asterisks and angle brackets.
 *
 * **Never enable `rehype-raw` here.** This is model output, steered by whatever
 * the player just typed, and a prompt-injection ladder is precisely the place
 * someone will try to get `<script>` into a reply. `react-markdown` escapes raw
 * HTML by default, which is the property this component exists to keep.
 *
 * The element map is deliberately small. The prompt asks for prose and at most
 * one notification block, but an 8B model wanders; anything it emits that is not
 * listed here still renders as readable text, just unstyled.
 */
const COMPONENTS: Components = {
  // The notification block — the persona's one piece of ceremony.
  blockquote: ({ children }) => (
    <blockquote className="my-1 border-l-2 border-accent/60 pl-2 text-[0.8rem] leading-snug">
      {children}
    </blockquote>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  code: ({ children }) => (
    <code className="rounded bg-surface-sunken px-1 font-mono text-[0.75rem]">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded bg-surface-sunken p-2 text-[0.75rem] last:mb-0">
      {children}
    </pre>
  ),
  // Links are stripped to their text. The System AI has no business sending
  // players off-site, and a model-authored href is an open redirect with extra
  // steps.
  a: ({ children }) => <>{children}</>,
  h1: ({ children }) => <p className="mb-2 font-semibold last:mb-0">{children}</p>,
  h2: ({ children }) => <p className="mb-2 font-semibold last:mb-0">{children}</p>,
  h3: ({ children }) => <p className="mb-2 font-semibold last:mb-0">{children}</p>,
  hr: () => <hr className="my-2 border-border" />,
};

export default function Markdown({ children }: { children: string }) {
  return <ReactMarkdown components={COMPONENTS}>{children}</ReactMarkdown>;
}
