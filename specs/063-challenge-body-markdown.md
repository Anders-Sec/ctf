# Spec 063 — Markdown and Pictures in a Challenge

Status: **draft**
Phase: 3 (Polish & Operability) — quality of life
Depends on: 033 (the `Markdown` component this copies), 040 (CSV authoring),
062 (the overlay the body renders in)

Some challenges need a code block. A few need a picture. Both are close to free,
because most of the machinery is already here and being used.

## 1. What already works

Worth stating plainly, because it changes the size of this:

- **Downloading a file already works.** The detail overlay renders
  `<a href={artifactUrl(…)} download={filename}>`, the backend streams it with a
  checksum header, and uploads accept any content type. A PNG attached to a
  challenge today is downloadable today.
- **`react-markdown` is already a dependency**, and `components/Markdown.tsx`
  already renders the System AI's replies with `code` and `pre` styling.
- **Admin upload and delete endpoints already exist** —
  `POST/DELETE /admin/challenges/{id}/artifacts`. There is simply no UI in front
  of them.
- **The descriptions are already written in markdown.** Of the 98 challenges in
  `challenges-working.csv`, one opens with a ```` ```json ```` fenced block that
  currently renders as literal backticks on screen.

So this spec is less "add markdown" than "render the markdown that is already
authored, and put a UI in front of the upload endpoint that already exists".

## 2. The body renders as markdown

`ChallengeBody`, a sibling of `Markdown` rather than a parameter on it. The
existing one is tuned for model output and says so: text at `0.8rem`, headings
flattened to paragraphs, and **links stripped entirely** because *"a
model-authored href is an open redirect with extra steps"*. A challenge body is
authored by the admin, so it wants the opposite of all three — real headings,
real links, body-sized text.

**`rehype-raw` stays off**, exactly as it is for the System AI. The reason is
different — this is trusted input — but the rule is worth keeping unconditional:
the day somebody wires challenge bodies to a CSV import from a shared drive, the
question should not have to be re-asked.

Code blocks render as a scrolling `<pre>` on a sunken background. **No syntax
highlighting**: a highlighter is a heavy dependency and per-language config, and
the thing these descriptions need is a JSON blob that keeps its shape.

## 3. Pointing at a picture

```markdown
![A diagram of the network](artifact:topology.png)
```

The renderer resolves `artifact:` against the challenge's own artifact list, by
**filename**, and swaps in the real download URL.

**Filename rather than id**, for the reason 059 keys stars on slugs: an author
types this by hand, into a CSV or a textarea, before any upload exists. A UUID
is not something a person writes, and it changes if a file is deleted and
re-added — while the filename is what they already have in front of them.

If nothing matches, the image renders as its alt text. A missing picture should
read as a gap in the page, not as a broken-image icon that looks like the
platform fell over.

Two artifacts with the same filename resolve to the first; the editor (§4) flags
the duplicate, which is the moment it can actually be fixed.

## 4. The editor grows a Files panel

In the challenge drawer, below the description:

- **The files on this challenge** — name, type, size — with delete.
- **Upload**, straight to the endpoint that already exists.
- **Copy reference** on each row, putting `![name](artifact:name.png)` on the
  clipboard.
- **Insert**, which drops that same text **at the cursor** in the description.

Both, because the brief asked for both — *"it could show the reference I'd need
and I could copy it in the description, or it could do it for me."* Insert is at
the cursor rather than appended, because the end of the description is almost
never where a picture belongs.

**A preview toggle on the description field**, rendering with the same
`ChallengeBody` the player sees. Authoring markdown blind is how you ship a
description with a broken fence.

## 5. Backend

One line, and one guard.

- **`image/*` is served `inline`**, everything else stays `attachment`. An
  `<img>` pointing at an `attachment` response is at the mercy of the browser,
  and `inline` also lets a player open the picture in its own tab. The Files
  list keeps its `download` attribute, which forces a save regardless.
- **The artifact route's visibility rules are unchanged** and are what make this
  safe: a locked challenge's files 404 whatever id is supplied, so an `artifact:`
  reference inside a sealed body — which is itself withheld (062) — resolves to
  nothing for anybody who should not have it.

No new endpoint, no migration, no model change.

## 6. What this does to the 98 already written

Markdown collapses a single newline inside a paragraph. Checked against
`challenges-working.csv`:

| | Count |
| --- | --- |
| Descriptions with any newline | 7 |
| …whose hard wraps are inside a fenced block (preserved exactly) | 1 |
| …that genuinely reflow | **2** |
| Descriptions with no newline at all (render identically) | 91 |

Two descriptions to re-read, not a migration. They are listed in the
implementation notes so they get looked at rather than discovered.

## 7. Testing

- A fenced code block renders as a `<pre>`, not as literal backticks.
- Raw HTML in a body renders as text, not as markup — `rehype-raw` is off and a
  test says so.
- `![alt](artifact:name.png)` resolves to that artifact's download URL.
- An `artifact:` reference matching nothing renders its alt text and no broken
  image.
- A plain single-paragraph description renders exactly as before.
- Backend: an `image/*` artifact is served `inline`; a `.zip` is still
  `attachment`.
- Backend: a locked challenge's artifact is still a 404.
- Admin: uploading adds a row; copy and insert both produce the reference;
  insert lands at the cursor, not at the end.
- Admin: two files with one name are flagged.

## 8. What this does not do

- **Syntax highlighting.** §2.
- **Raw HTML in bodies.** §2, deliberately and permanently.
- **A markdown editor.** The description stays a textarea with a preview
  toggle; a toolbar is a different product.
- **Images anywhere else.** Hints, announcements and achievement descriptions
  are untouched.
- **Artifact reordering or renaming.** `display_order` is settable through the
  API and not worth a UI yet.

## 9. Open questions

1. **Should `artifact:` work for non-images too?** `[the capture](artifact:dump.pcap)`
   as a download link inside the prose, rather than only in the Files list.
   Recommend **yes** — it is the same resolver, and "download the file mentioned
   in this sentence" is a better read than "see the list below".
