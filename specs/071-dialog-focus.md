# Spec 071 — Focus and the Keyboard in Dialogs

Status: **done**
Phase: 3 (Polish & Operability) — quality of life
Depends on: 058, 059, 060, 062, 064, 065, 066 — every spec that added a dialog
First of two: **071** focus, 072 the party page's tests.

Twelve components declare `role="dialog"`. **Two of them manage focus, and both
predate Phase 3.** Everything added since spec 058 announces itself as a dialog
and then leaves the keyboard exactly where it was.

## 1. What is actually there

Counted rather than remembered, because the first version of this claim was
wrong in the telling:

| | |
| --- | --- |
| `role="dialog"` | 12 components |
| …that move focus **in** | 2 — `ZoneGatePanel`, `ZonePanel` |
| …that **trap** focus | **0** |
| …that **restore** focus on close | **0** |
| `aria-modal="true"` | 3 — `Tour`, `ZonePanel`, `ChallengeDetailPage` |
| `role="menu"` | 1 — `ProfileMenu` |

The first draft of this table claimed two components did all three. They do not:
there is no `activeElement` reference anywhere in `src/`, so **nothing traps or
restores focus**. The two that handle it at all only move focus in and listen
for Escape. Corrected before building rather than after.

The ten with no focus handling whatsoever: the challenge overlay (062), `PartyPanel` (059),
the class dialog in `PlayerInfo` (060), `Tour` (066), `NotificationCentre` (065),
`ContentDrawer` (058), `UserDetailDrawer` (052), `PartyDetailDrawer` (053),
`BulkToolbar` (042), and the puzzle editor's dialog in `AdminChallengesPage`.

`ProfileMenu` is a menu rather than a dialog and wants the lighter treatment in
§4.

## 2. What goes wrong

A keyboard user presses Enter on a challenge row. The overlay opens. Focus is
still on the row **behind** it. Tab moves through the board underneath — which is
still there, still focusable, and now covered by a translucent sheet. Escape
closes the dialog and focus is wherever it drifted to.

A screen-reader user is told a dialog opened and then reads the page behind it.

`aria-modal="true"` makes this worse in the three that declare it: it tells
assistive technology *"everything outside this is inert"*, which is a promise
none of them keep. A wrong claim is worse than a missing one.

## 3. The fix

One hook, `useDialogFocus(ref, { onClose })`, doing four things:

1. **Move focus in** on open — to the first focusable element, or the dialog
   itself when it has none.
2. **Trap Tab and Shift+Tab** inside it, cycling at both ends.
3. **Restore focus** on close to whatever had it before, so closing a challenge
   returns you to the row you opened.
4. **Escape closes**, which nine of the ten already do individually and which
   belongs with the rest of it.

Plus `aria-modal="true"` on every dialog once the trap is real, and `role` left
alone otherwise.

**It replaces the Escape handlers already written**, rather than sitting beside
them. Ten hand-rolled `keydown` listeners is nine too many, and two of them
already differ in whether they re-bind on every render.

## 4. The menu is not a dialog

`ProfileMenu` gets focus moved to its first item and Escape returning focus to
the trigger — but **no trap**. A menu is not modal: Tab should leave it, which is
what a menu does everywhere else, and trapping would make it behave unlike every
other menu a person has used.

## 5. The two that half-do it

`ZoneGatePanel` and `ZonePanel` move focus in and handle Escape. They **adopt
the hook** like everything else, which preserves what they already do and adds
the trap and the restore they are missing. They are a head start, not a
reference implementation — there is nothing in the codebase to copy.

## 6. Testing

Per dialog, and the same four assertions each time, because a shared hook is
worth exactly as much as its weakest caller:

- Opening moves focus inside.
- Tab from the last focusable element returns to the first; Shift+Tab from the
  first goes to the last.
- Escape closes it.
- Closing returns focus to the element that opened it.

Plus:

- Every `role="dialog"` in the codebase uses the hook — a test that enumerates
  them, so an eleventh dialog cannot quietly ship without it.
- `ProfileMenu` moves focus and **does not** trap: Tab leaves it.
- `ZoneGatePanel` and `ZonePanel` keep their existing tests passing, and gain
  the trap and restore assertions along with everyone else.

## 7. What this does not do

- **A full accessibility audit.** Focus is the specific, verified gap. Colour
  already has automated contrast tests (048) and `sr-only` is used throughout;
  landmarks, heading order and form labelling are not surveyed here.
- **Touch the puzzle boards.** `CrosswordBoard` manages its own grid focus and
  is its own problem.
- **Add a focus-trap dependency.** It is about forty lines and a dependency
  would be a larger thing to keep current than the code it replaces.

## 8. Decisions

1. **The challenge overlay restores focus to the row, and needed no code to do
   it.** `App.tsx` nests the overlay *inside* the board, so the board never
   unmounts and the row is still there; capturing `document.activeElement` at
   open time lands on it. The fallback this question proposed is unnecessary.
2. **`BulkToolbar` is an `alertdialog`, not a `region`** — amending this
   spec's own recommendation. Reading it showed it is a destructive delete
   confirmation rendered inline under the toolbar, not a landmark and not an
   overlay. It gets focus moved to it and Escape to cancel, with **no trap**:
   the page behind it genuinely is still usable, so holding focus would strand
   an admin in a strip of a page they can see past. Its four existing tests
   moved from `role="dialog"` to `role="alertdialog"`.

## 9. What the build changed

- **§1's table was wrong and was corrected before any code was written.** It
  claimed two components already moved focus in, trapped it and restored it.
  They only moved it in: there is no `activeElement` reference anywhere in
  `src/`, so nothing trapped or restored anything.
- **The hook holds `onClose` in a ref.** Callers pass an inline arrow almost
  every time, which as a dependency re-ran the effect on every parent render —
  re-capturing the opener and snapping focus back to the first field while
  somebody was typing in the third. This also gives `ContentDrawer` the
  property its hand-rolled handler needed a deliberately missing dependency
  array to get: the Escape path always sees the current `dirty`.
- **A visibility filter was written and then removed.** `offsetParent !== null`
  is untestable under jsdom, which has no layout and reports null for
  everything — the filter silently emptied the focusable list and made the hook
  a no-op in every test. Nothing in these dialogs CSS-hides a focusable
  control, so the selector now carries `:not([hidden])` and nothing more.
- **§6's "same four assertions per dialog" became coverage plus depth.** Twelve
  near-identical copies of the hook's own tests would assert the hook, not the
  callers. Instead: the hook is tested once and thoroughly, a source-walking
  guard proves every dialog uses it and that **every hook call names a ref that
  is actually attached** — the silent failure, since a null ref makes the hook
  do nothing with no error — and the dialogs with the interesting wiring
  (`ChallengeDetailPage`, `NotificationCentre`, `ContentDrawer`, `Tour`) get
  real behavioural tests. The guard was verified by sabotaging `ZonePanel` and
  confirming it named the file.
- **Counts, for the record:** 11 elements with `role="dialog"`, 1
  `role="alertdialog"`, 1 `role="menu"`, 13 components using the hook, 636
  frontend tests passing (up from 608).
