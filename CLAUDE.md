# CLAUDE.md

This project is built using **Spec-Driven Development (SDD)**. The phase roadmap
and Phase 1 scope live in `plan.md` at the repo root — read it before starting any
work, and treat it as the current source of truth for what's in scope right now
(Phase 1 only, unless told otherwise).

## Spec-Driven Development Workflow

1. **Don't write implementation code from a one-line request.** Before building any
   feature described in `plan.md`, write a short feature spec first (a markdown
   file under `specs/`, e.g. `specs/challenge-flag-system.md`) covering: purpose,
   data model changes, API surface (endpoints/contracts), and edge cases /
   open questions. Keep it tight — this is a working spec, not documentation.
2. **Get explicit sign-off on the spec before implementing it.** Present the spec,
   flag anything ambiguous or undecided as an open question rather than guessing,
   and wait for confirmation before writing code.
3. **Implement against the approved spec.** If reality forces a deviation from the
   spec mid-implementation, stop and call it out rather than silently diverging —
   update the spec afterward so it stays accurate.
4. **One feature/spec at a time.** Don't bundle multiple `plan.md` sections into a
   single spec-and-build pass; keep specs scoped enough to review quickly.
5. **Verify against the spec's stated scope when a feature is "done."** Definition
   of done for the phase overall is listed at the bottom of `plan.md`.

## Git Workflow

This repo has a GitHub remote. There is likely a separate IaC repo (Bicep/
Terraform/etc. for Azure resources and AKS deployment config) — this repo
(`CLAUDE.md`/`plan.md`) is the application code; don't put infrastructure
definitions here unless told otherwise, and don't assume you can see or edit
the IaC repo unless it's explicitly present in the working environment.

- **Commit in logical units, not one giant commit per feature.** Break a spec's
  implementation into the same natural seams you'd review it in — e.g. schema/
  migration, then backend endpoint, then frontend, then tests — each as its own
  commit rather than one commit dumping the whole feature.
- **Commit before moving to the next work item.** Once a logical unit of work is
  done (and, per the SDD flow above, matches its spec), commit it before starting
  the next piece. Don't let uncommitted work pile up across multiple work items.
- **Write real commit messages.** Short imperative summary line, body if the
  "why" isn't obvious from the diff. Reference the relevant spec file under
  `specs/` when a commit implements one.
- **Don't push or open PRs without being asked.** Committing locally as you go is
  expected and doesn't need confirmation; pushing to the remote, opening a PR, or
  merging does.
- **Never commit secrets, connection strings, or the local AI model's network
  address** into this repo — those belong in config/environment, not source.

## Notes

- Stay inside the current phase's scope in `plan.md`. Later-phase features
  (D&D mechanics, art/creative pass) are intentionally deferred — don't build
  ahead of them, but don't design Phase 1 in a way that forecloses them either.
- Anything marked as an "Open Item" in `plan.md` needs a decision (from the user)
  before it's implemented — surface these rather than assuming an answer.