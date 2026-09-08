# Dungeon Map — Art Generation Guide

Everything needed to generate the map art in ChatGPT, one image at a time.

**How to use this file:** copy the **Master Prompt** below, replace `[SUBJECT]`
with the line for the zone you are generating, paste into ChatGPT, and save the
result under the filename given for that zone. Do the **Base Plate** once,
separately.

The style guide is here so the look stays consistent across 22 separate
generations — the master prompt does the work, but if an image drifts, the guide
tells you which knob to turn.

---

## 1. Style guide

### The reference in one line

A premium virtual-tabletop battle map: dark, painted, lit from within by
torchlight, seen straight down from above.

### Camera

- **Straight down, orthographic.** No perspective, no tilt, no isometric angle.
  Walls are seen from directly above, not from the side.
- Everything reads as a **floor plan that happens to be beautifully painted**.

### Lighting

- **Warm orange torchlight pools on the floor** and falls off fast into deep
  shadow. Light comes from within the scene, never from a sky.
- **Cool teal-cyan** for anything glowing that is not fire: water, magic, screens,
  runes. The warm/cool contrast is most of what makes it feel alive.
- **Deep shadow everywhere else.** Dark is the default; light is the exception.

### Palette

| Role | Colour |
| --- | --- |
| Void / edges | near-black `#0a0f17` |
| Stone, dark | `#241f1b` |
| Stone, lit | `#9c7d59` |
| Torchlight | `#ff9d3d`, hot core `#ffca7a` |
| Water / arcane glow | `#3fd6d0` |
| Grid *(drawn by the app, not the art)* | faint blue `#4a7fa8`, barely visible |

### Materials

Rough hewn stone, worn flagstones with visible chisel marks, rubble, damp patches,
old timber, tarnished brass. Everything should look **used and slightly ruined**,
never clean or new.

### Composition and silhouette

- **Square frame**, subject centred, with generous empty margin around it.
- **Transparent background**, and the shape matters: each zone has an
  **irregular, organic, hand-carved outline** — rough rocky edges, not a square
  or a circle. That silhouette is what makes the map read as a cavern system
  rather than a grid of cards, and it is the whole reason transparency is worth
  having.
- **Clean alpha edges.** No baked backdrop, ground, glow, vignette or drop
  shadow — the app adds shadow and glow itself, following the real silhouette.
- **No border, no frame, no card edge.**

### No grid on the artwork

The faint blue grid is drawn by the app as one overlay across the whole map, so
it always aligns. A grid baked into each tile would never line up with the base
plate or with neighbouring tiles.

### Mood

Abandoned, dangerous, recently occupied by something. Dungeon Crawler Carl: a
familiar place that has been turned into a deathtrap and is quietly enjoying it.

### Always avoid

Text, labels, numbers, letters, people, creatures, UI, borders, frames,
watermarks, angled or isometric perspective, daylight, white or coloured
backgrounds, a drawn checkerboard pattern, cartoon outlines, clean modern
surfaces, baked drop shadows, grid lines.

---

## 2. Master prompt

Copy this whole block. Replace `[SUBJECT]` with a line from section 4.

```
Top-down overhead fantasy battle-map tile of [SUBJECT], as a cut-out asset on a
fully transparent background.

Style: dark, moody, painted digital illustration in the style of a premium
virtual-tabletop battle map. Viewed straight down from directly above,
orthographic, with no perspective distortion and no isometric angle. Warm orange
torchlight pools on the floor and falls off quickly into deep shadow; cool
teal-cyan glow from any water, magic, runes or screens. Rough hewn stone and worn
flagstones with visible chisel marks, rubble and damp patches — everything looks
used and slightly ruined. Painterly brushwork, rich texture, high detail, no
linework or cartoon outlines.

Shape: the location has an irregular, organic, hand-carved outline with rough
rocky edges — not a square, not a circle. Everything around that shape is fully
transparent: no background, no backdrop, no ground, no glow, no drop shadow, no
vignette, and no drawn checkerboard. Clean alpha edges. Leave a small margin of
empty transparent space so the shape never touches the edge of the frame.

Do not include: text, labels, numbers, letters, people, creatures, UI elements,
borders, frames, watermarks, grid lines, angled or isometric perspective,
daylight, or any background colour.
```

**Size:** square, 1024×1024. **Format:** PNG with transparency.

**Check it before saving:** drop the image onto a coloured background. If the
corners show that colour, the alpha is real. If they show white, grey, or a
painted checkerboard, regenerate — see section 5.

---

## 3. Base plate

Generated once. This is the floor the zone tiles sit on.

**Save as:** `frontend/public/map/base.png` · **Size:** landscape, 1536×1024 ·
**Opaque** — this one is the backdrop, so it fills the frame edge to edge.

```
Top-down overhead view of a vast empty underground cavern floor, dark moody
painted digital illustration in the style of a premium virtual-tabletop battle
map. Viewed straight down from directly above, orthographic, no perspective
distortion. Almost entirely deep shadow and near-black rock, with a few very dim
pools of distant amber light near the corners. Damp bedrock, scattered rubble,
cracks and old scorch marks. Painterly brushwork, subtle texture, very low
contrast, nothing bright. Fills the whole frame, opaque, no transparency.

This is an empty background plate: no rooms, no structures, no doors, no
corridors, no focal point, no grid lines, no people, no creatures, no text, no
borders. It must read as empty dark ground that other artwork will be placed on
top of.
```

---

## 4. Zone subjects

22 tiles, PNG with transparency. Save each as `frontend/public/map/zones/<filename>`.

> **The filename is the wiring.** It is matched to the zone by its slug, so a tile
> appears on the map automatically the moment the file exists under the right
> name. A typo means the zone silently keeps its plain fallback.

| # | Zone | Save as | `[SUBJECT]` |
| --- | --- | --- | --- |
| 1 | Intro | `intro.png` | a small orientation chamber with cracked motivational banners and a single lit doorway |
| 2 | Networking | `networking.png` | stone canals of glowing teal data flowing under narrow footbridges |
| 3 | Governance, Risk & Compliance | `governance-risk-compliance.png` | a vast archive hall of chained ledgers and toppled filing stacks |
| 4 | Hacker Game Show | `hacker-game-show.png` | a lit arena stage ringed by buzzer podiums and dead spotlights |
| 5 | CTI | `cti.png` | a trophy hall of broken siege weapons mounted on stone walls |
| 6 | Incident Response | `incident-response.png` | a burned-out server hall of collapsed racks, rubble and glowing embers |
| 7 | AI/LLM Security | `ai-llm-security.png` | a shrine chamber built around one vast glowing eye set into the floor |
| 8 | Prompt Injection | `prompt-injection.png` | a whispering gallery lined with carved stone mouths |
| 9 | Forensics | `forensics.png` | a frozen morgue of open specimen drawers and hanging tape reels |
| 10 | Threat Detection | `threat-detection.png` | a ring of watchtowers casting sweeping amber lantern beams |
| 11 | Cloud Security | `cloud-security.png` | a molten foundry of pipes, vents and glowing forges |
| 12 | OSINT | `osint.png` | an open-air records court strewn with unrolled maps and pinned notes |
| 13 | Red teaming | `red-teaming.png` | a war room around a great siege table covered in battle plans |
| 14 | Hardware Hacking | `hardware-hacking.png` | a workbench pit of solder irons, cabling and exposed circuit boards |
| 15 | Social Engineering | `social-engineering.png` | a masquerade bazaar of false storefronts and hanging masks |
| 16 | Identity & Access | `identity-access.png` | a labyrinth of numbered doors with brass badge readers |
| 17 | Web Attacks | `web-attacks.png` | a caustic glowing green slime marsh creeping over cracked tiling |
| 18 | Codes and Ciphers | `codes-and-ciphers.png` | a frozen vault of enormous rotating brass cipher rings |
| 19 | Crypto | `crypto.png` | a sealed sanctum of tall glowing glyph-carved pillars |
| 20 | Mobile Security | `mobile-security.png` | a shrine of hand-sized glowing slabs on stone plinths |
| 21 | Reverse Engineering | `reverse-engineering.png` | a dissection hall of opened machines with their guts laid out |
| 22 | Malware Analysis | `malware-analysis.png` | a sealed quarantine cell marked with glowing warning sigils |

---

## 5. If the results drift

| Problem | Fix |
| --- | --- |
| Angled or 3D-looking | Re-emphasise *"straight down from directly above, orthographic, no perspective"* |
| Too bright or washed out | Add *"very dark overall, deep shadow, only small pools of light"* |
| Background came out solid | Re-emphasise *"fully transparent background, cut-out asset, PNG with alpha, no backdrop of any kind"* |
| A checkerboard is painted into the image | Add *"do not draw a checkerboard pattern; the background must be genuinely transparent, not a picture of transparency"* |
| Shape is a square or a neat circle | Re-emphasise *"irregular organic hand-carved outline with rough rocky edges"* |
| Text or symbols creeping in | Add *"absolutely no text, letters, numbers or symbols"* |
| Style drifting between zones | Regenerate in one sitting; start a fresh chat and re-paste the full master prompt each time |
| Too busy to read as a map | Add *"simple readable layout, one clear focal structure"* |

**Consistency tip:** generate all 22 in one session, master prompt re-pasted in
full every time. Changing only `[SUBJECT]` between images is what keeps them
looking like one dungeon.

Any zone without a tile falls back to a plain stone chamber, so partial sets are
fine — the map improves one file at a time.
