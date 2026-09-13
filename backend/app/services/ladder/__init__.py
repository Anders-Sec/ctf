"""The System AI ladder (spec 033).

Six levels, each holding a flag behind a different defence, selected by how many
ladder flags the player has already solved. Ported from the `dcc-system-ai`
package, which was calibrated against the model we actually run.

Three things in here are load-bearing and easy to "tidy" into breakage:

1. **Gates are distinct per level, not cumulative.** An earlier build stacked
   them and level 4 became harder than level 5, at zero solves in ~60 attempts.
2. **Level N's prompt contains only level N's flag.** One shared context would
   mean breaking level 0 hands over the whole ladder.
3. **The flag reaching the player is the win condition**, so nothing here
   filters it out. :func:`verdict.is_solve` exists to *log* that, never to gate.

See `specs/research/ladder/` before changing a prompt, a gate or a level.
"""
