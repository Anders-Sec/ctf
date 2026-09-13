# Ladder research — how the numbers in spec 033 were arrived at

Source material for [spec 033](../../033-system-ai-ladder.md). Read it when
something about the ladder surprises you, and **before** changing a prompt, a
gate, or a level's configuration — most of what looks like a mistake in there is
a measured decision, and several of the obvious "fixes" were tried and made
things worse.

| File | What it answers |
| --- | --- |
| `IMPLEMENTATION.md` | The original integration guide: non-negotiables, model gotchas, expected solve rates, tuning knobs |
| `ladder-design.md` | Level composition, the calibration matrix, and why each gate sits where it does |
| `ablation-l4.md` | Why level 4 was unsolvable as first built, and the gate ablation that fixed it |
| `findings-persona.md` | What the persona work found, including the leak filter written for a bot that must never leak |
| `transcripts-all-levels.md` | Real exchanges at every level |

## Flags are redacted

Every real flag value in these documents has been replaced with
`LEVEL_N_FLAG`. The originals are calibrated artefacts and they are live
answers for six challenges; this repository is public.

Two consequences worth knowing when reading:

- Where a document argues that a flag's *text* affected difficulty — the level 4
  and 5 random suffixes, and `LEVEL_4_FLAG_UNSUFFIXED` / `LEVEL_5_FLAG_UNSUFFIXED`
  standing for the plain-English versions that were extractable — the argument
  survives the redaction but the example has lost its force. The point is real:
  a flag whose inner text is ordinary English can have its *meaning* conveyed
  without the model ever emitting the string, which defeats the router, the
  regex and the warden at once.
- Invented flags quoted as examples of the decoy problem are the model's own
  fabrications, never real answers, and are left as they were.

`IMPLEMENTATION.md` describes a standalone Node service that no longer exists;
it was ported into `backend/app/services/ladder/` by spec 033. Its reasoning
still applies, its file paths do not.
