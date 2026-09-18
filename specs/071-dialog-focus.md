# Spec 071 — Focus and the Keyboard in Dialogs

Status: **draft**
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

## 8. Open questions

1. **Should the challenge overlay restore focus to the row, or to the board's
   scroll position?** They are different: the row may have moved if the board
   refetched. Recommend **the row by id, falling back to the board container**,
   since spec 062's ordering is stable precisely so it will still be there.
2. **Does `BulkToolbar` want this at all?** It is a bar rather than an overlay
   and declares `role="dialog"` arguably wrongly. Recommend **changing its role
   to `region`** instead of trapping focus in a toolbar the admin is using
   alongside the table.
