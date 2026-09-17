# Spec 049 — Admin Navigation

Status: **approved** (2026-09-17)
Phase: 3 (Polish & Operability)
Depends on: 048 (tokens — the shell is new chrome and should not be built on raw colours)
Blocks: 050–057, which all need somewhere to live

Twelve flat top-level tabs, no grouping, and inconsistent naming. This spec
replaces the admin nav with a persistent grouped sidebar, renames the pages, and
splits one route that is currently two different jobs wearing one hat.

## 1. What is wrong with the tab row

[`AppLayout.tsx`](../frontend/src/components/AppLayout.tsx) renders the admin nav
as twelve `NavLink`s in a single flex row inside a `max-w-3xl` container:

> Console · Ops · Signals · System AI · Dungeons · Manage · Map · Skills ·
> Classes · Achievements · Approvals · Event

- **It is past the point of scanning.** Twelve peers with no grouping means
  finding a page is a linear read every time.
- **It overflows.** Twelve labels do not fit `max-w-3xl` at anything but a wide
  desktop, and there is no wrap or scroll handling — they just squeeze.
- **The names are in two registers.** Themed (`Console`, `Signals`, `Dungeons`)
  sitting next to literal (`Manage`, `Approvals`, `Event`). `Manage` in
  particular names nothing.
- **Work waiting is invisible.** Open reports and pending approvals are counted
  on the dashboard, so noticing them requires navigating somewhere to look.
- **Adding a page makes it worse**, and Phase 3 adds eight.

## 2. The shape: a sidebar, not two levels of tabs

A **persistent left sidebar with grouped sections**, and no top-level group tabs.

```
┌──────────────┬────────────────────────────────────┐
│  CTF · Admin │                                    │
│              │                                    │
│  Dashboard   │                                    │
│              │   (page)                           │
│  OPERATIONS  │                                    │
│  Reports  ③  │                                    │
│  Signals     │                                    │
│  Metrics     │                                    │
│  System AI   │                                    │
│  Instances   │                                    │
│  Approvals ⑦ │                                    │
│  Audit log   │                                    │
│  Announce…   │                                    │
│  Health      │                                    │
│              │                                    │
│  CONTENT     │                                    │
│  Challenges  │                                    │
│  Skills      │                                    │
│  Classes     │                                    │
│  Achievements│                                    │
│  Map         │                                    │
│                                                   │
│  SETTINGS    │                                    │
│  Event       │                                    │
│  Theme       │                                    │
│  Templates   │                                    │
│  Email       │                                    │
│  Export      │                                    │
│  Data        │                                    │
│              │                                    │
│  [Player view]                                    │
└──────────────┴────────────────────────────────────┘
```

**Why one level and not a group-tab row plus a sidebar.** The alternative
sketched at the start of this phase was group tabs across the top, each revealing
its own sidebar. That is two navigation steps to reach anything, and it makes the
common mid-event move — Reports to Signals to Instances, repeatedly, chasing one
problem — cost a group switch each time. Group *headers* give the same visual
organisation for free, because a header is a label rather than a step. Everything
stays one click away, which matters most on exactly the pages you are in a hurry
to reach.

Group headers are not collapsible. There are 22 items; collapsing sections to
save space that is not scarce just hides things from the person who already
struggles to find them.

## 3. Grouping and naming

Admin pages get **practical, non-themed names**, per the standing Phase 3
decision in `CLAUDE.md`. Dungeon flavour is reserved for player-facing surfaces —
it lands harder there for not being diluted across the tooling.

| Group | Item | Route | Was |
| --- | --- | --- | --- |
| — | **Dashboard** | `/admin` | "Console" |
| Operations | **Reports & Adjustments** | `/admin/ops` | "Ops" |
| Operations | **Anti-Cheat Signals** | `/admin/signals` | "Signals" |
| Operations | **Metrics** | `/admin/metrics` | new — spec 050 |
| Operations | **System AI** | `/admin/assistant` | unchanged (it is the product name) |
| Operations | **Live Instances** | `/admin/instances` | "Dungeons" |
| Operations | **Approvals** | `/admin/users/approvals` | "Approvals" |
| Operations | **Audit Log** | `/admin/audit` | new — spec 051 |
| Operations | **Announcements** | `/admin/announcements` | new — spec 054 |
| Operations | **Platform Health** | `/admin/health` | new — spec 057 |
| Content | **Challenges** | `/admin/challenges` | "Manage" |
| Content | **Skills** | `/admin/skills` | unchanged |
| Content | **Classes** | `/admin/classes` | unchanged |
| Content | **Achievements** | `/admin/achievements` | unchanged |
| Content | **Map** | `/admin/map` | unchanged |
| Settings | **Event** | `/admin/event` | unchanged |
| Settings | **Theme** | `/admin/theme` | new — spec 048 |
| Settings | **Container Templates** | `/admin/templates` | split out of "Dungeons" |
| Settings | **Email Delivery** | `/admin/email` | new — spec 055 |
| Settings | **Export** | `/admin/export` | new — spec 056 |
| Settings | **Data & Reset** | `/admin/data` | split out of "Ops" |

Two placements worth defending:

- **Approvals is Operations, not Settings.** It is a queue worked during the
  event, not a thing configured before it.
- **Map is Content, not Settings.** It is the zone-layout *editor* — authoring,
  the same as writing a challenge.

**Users** is not in this table. Spec 052 replaces the approvals-only page with a
full roster; where that lands is settled there, and this spec leaves
`/admin/users/approvals` in place so nothing is orphaned in between.

## 4. Splitting Live Instances from Container Templates

[`AdminInstancesPage.tsx`](../frontend/src/routes/AdminInstancesPage.tsx) renders
two sections on one route: "Live dungeons" and "Container templates". They are
different jobs on different clocks —

- **Live instances** is runtime and mid-event: what is running now, for whom,
  when it expires, force-teardown.
- **Container templates** is configuration, set up before the event and rarely
  touched during it.

— and per the standing note that admin tools are setup tools, mixing them means
the page you open in a hurry is half filled with things you are not looking for.
They split into `/admin/instances` (Operations) and `/admin/templates`
(Settings), sharing the API client they already share.

## 5. Badge counts

The sidebar carries counts for work waiting, so the dashboard's "needs attention"
block becomes ambient instead of somewhere you have to go and check:

| Item | Count |
| --- | --- |
| Reports & Adjustments | open reports |
| Approvals | users pending approval |
| Anti-Cheat Signals | undismissed findings |
| Live Instances | instances in an error state |

These all exist in `GET /api/admin/dashboard`'s `attention` block, except the
signal and instance counts. Rather than have the shell fan out to four endpoints
on a timer, `/admin/dashboard` gains a `nav_counts` object holding exactly these
four, and the shell polls that one endpoint on the existing 10s interval.

A badge shows only when non-zero. A zero badge is noise that trains you to ignore
the badge.

## 6. Layout and responsiveness

- The sidebar is fixed-width (about 15rem) and full height, scrolling
  independently of the page.
- The content column drops `max-w-3xl`. Several admin pages are tables that were
  already fighting it — spec 041 went full-width for exactly this reason. Pages
  keep their own max width where a form wants one.
- **Below `lg`, the sidebar collapses to a drawer** behind a menu button. The
  admin area is desktop-first and stays that way; this is so a tablet is not
  locked out, not an endorsement of running an event from a phone.
- Current page is marked by a filled background plus a left rule, not colour
  alone.

## 7. The player nav is not in scope

`AppLayout` currently branches between the admin nav and the player nav in one
component. This spec **extracts the admin shell** into its own layout under the
`/admin` routes and leaves the player nav exactly as it is — same markup, same
four links, same view switcher.

The player-side navigation pass belongs to the QoL workstream, which is specced
after the manual walkthrough. Touching it here would mean rebuilding it twice.

The **view switcher** (Player view / Admin view) moves to the bottom of the
sidebar, where it is out of the way of a nav that is now scannable, and stays a
single control.

## 8. API changes

- `GET /api/admin/dashboard` gains `nav_counts`:
  `{ open_reports, pending_approvals, open_signals, failed_instances }`.
  Computed in the same pass as `attention`, which already counts the first two.

No other backend change. Every route in §3 that exists today keeps its endpoint;
the new ones bring their own in their own specs.

## 9. Redirects

Renaming a route breaks a bookmark, and there is exactly one person with these
bookmarked. Still cheap to be kind: the two moved routes
(`/admin/instances` → templates half) keep working via a redirect from the old
path to the new one for the rest of the phase. Everything else keeps its URL —
the renames in §3 are label changes, not route changes, except where marked.

## 10. Testing

- The sidebar renders every item in §3, in the right group, in the listed order.
- The active item is marked, and marked for a nested route
  (`/admin/challenges/…` marks Challenges).
- A badge appears only when its count is non-zero, and reflects `nav_counts`.
- `nav_counts` matches the underlying tables for each of the four counts.
- Below the `lg` breakpoint the sidebar is a drawer, and opening it traps focus
  and closes on Escape.
- A non-staff user hitting any `/admin/*` route is still bounced by
  `RequireAuth staffOnly` — the shell change must not become an auth change.
- The player nav is byte-for-byte what it was: the existing `AppLayout` tests
  pass unchanged.
- `/admin/instances` no longer renders container templates, and `/admin/templates`
  does.

## 11. Open questions

Signed off 2026-09-17. Each recommendation below was accepted as written
unless a **Decision** line says otherwise.

1. **Does "Data & Reset" belong in Settings, or is it dangerous enough to want its
   own separated placement?** It holds the play-data reset from spec 043, which is
   the single most destructive control in the app. Recommend: Settings, at the
   bottom, visually separated — the standing note that admin tools are setup tools
   argues against inventing mid-event friction, and the reset already has its own
   confirmation.
2. **Should the sidebar show the event clock and running/stopped state?** It is on
   the dashboard today. Recommend yes, as a small persistent footer above the view
   switcher — "has the event started" is context for every other page, and it
   costs nothing since `/admin/dashboard` is already polled for badges.
