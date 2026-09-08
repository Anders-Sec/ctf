# Dungeon Map — Art Prompts

Paste **MASTER PROMPT**, then paste the **SUBJECT** block for the zone. Save to
`frontend/public/map/zones/<filename>`. The filename is what wires the tile to
its zone.

---

## MASTER PROMPT

```
Generate a top-down overhead fantasy battle-map tile as a cut-out asset with a
fully transparent background. Output a 1024x1024 square PNG with a real alpha
channel.

CAMERA: Viewed straight down from directly above. Orthographic. No perspective
distortion, no tilt, no isometric angle. Structures are seen from directly
overhead, like a floor plan.

LIGHTING: Dark by default; light is the exception. Warm orange torchlight
(#ff9d3d, hot cores #ffca7a) pools on the floor and falls off quickly into deep
shadow. Cool teal-cyan (#3fd6d0) glow from any water, magic, runes or screens.
All light comes from sources inside the scene, never from a sky. Strong warm
versus cool contrast.

PALETTE: near-black #0a0f17, dark stone #241f1b, lit stone #9c7d59, torch orange
#ff9d3d, hot highlight #ffca7a, arcane teal #3fd6d0.

MATERIALS: Rough hewn stone, worn flagstones with visible chisel marks, rubble,
damp patches, old timber, tarnished brass. Everything looks used, weathered and
slightly ruined. Never clean, never modern.

RENDERING: Painterly digital illustration in the style of a premium
virtual-tabletop battle map. Rich texture, high detail, visible brushwork. No
linework, no cartoon outlines, no cel shading, no flat vector look.

SHAPE AND COMPOSITION: The location has an irregular, organic, hand-carved
outline with rough rocky edges — not a square, not a circle, not a rounded
rectangle. It sits centred in the frame with a margin of empty space on all sides
so the shape never touches the frame edge.

TRANSPARENCY: Everything outside the shape is fully transparent alpha. No
background, no backdrop, no ground plane, no glow, no drop shadow, no vignette,
no fade, and no painted checkerboard pattern. Clean, crisp alpha edges.

MOOD: Abandoned, dangerous, recently occupied by something hostile. A familiar
place turned into a deathtrap.

DO NOT INCLUDE: text, letters, numbers, labels, symbols, people, creatures, UI
elements, borders, frames, cards, watermarks, grid lines, drop shadows,
background colour of any kind, daylight, bright or washed-out areas, angled or
isometric perspective, corridors or passages extending beyond the shape.

SUBJECT:
```

---

## BASE PLATE

Once only. Save as `frontend/public/map/base.png`. This one is **opaque**.

```
Generate a top-down overhead view of a vast empty underground cavern floor.
Output a 1536x1024 landscape image, fully opaque, filling the entire frame.

CAMERA: Viewed straight down from directly above. Orthographic. No perspective
distortion, no tilt, no isometric angle.

CONTENT: Almost entirely deep shadow and near-black damp bedrock (#0a0f17 to
#241f1b), with scattered rubble, cracks and old scorch marks. A few very dim
distant pools of amber light near the corners only. Very low contrast, nothing
bright, nothing in focus.

RENDERING: Painterly digital illustration in the style of a premium
virtual-tabletop battle map. Subtle texture, visible brushwork, no linework.

This is an empty background plate that other artwork will be placed on top of. It
must read as bare dark ground.

DO NOT INCLUDE: rooms, structures, buildings, doors, corridors, bridges, any
focal point, grid lines, text, letters, numbers, symbols, people, creatures,
borders, frames, watermarks, transparency, bright areas, daylight.
```

---

## SUBJECTS

### Intro → `intro.png`
```
a small orientation chamber with cracked motivational banners on the walls and a
lit doorway
```

### Networking → `networking.png`
```
stone canals of glowing teal data flowing under narrow footbridges, with sluice
gates and channel junctions
```

### Governance, Risk & Compliance → `governance-risk-compliance.png`
```
a vast archive hall of chained ledgers on iron lecterns, with toppled filing
stacks and spilled scrolls
```

### Hacker Game Show → `hacker-game-show.png`
```
a lit arena stage ringed by buzzer podiums, with dead spotlight rigs overhead and
scattered scoring tokens
```

### CTI → `cti.png`
```
a trophy hall of broken siege weapons and shattered battering rams mounted on
stone walls
```

### Incident Response → `incident-response.png`
```
a burned-out server hall of collapsed equipment racks, fallen beams, rubble and
still-glowing embers
```

### AI/LLM Security → `ai-llm-security.png`
```
a shrine chamber built around one vast glowing eye set into the floor, ringed by
kneeling stones
```

### Prompt Injection → `prompt-injection.png`
```
a whispering gallery lined with carved stone mouths, curved walls and echo
channels cut into the floor
```

### Forensics → `forensics.png`
```
a frozen morgue of open specimen drawers, hanging tape reels and frost-covered
examination slabs
```

### Threat Detection → `threat-detection.png`
```
a ring of squat watchtowers casting sweeping amber lantern beams across a central
courtyard
```

### Cloud Security → `cloud-security.png`
```
a molten foundry of pipes, vents and glowing forges, with catwalks over channels
of liquid fire
```

### OSINT → `osint.png`
```
an open records court strewn with unrolled maps, pinned notes and string
connecting scattered evidence boards
```

### Red teaming → `red-teaming.png`
```
a war room around a great siege table covered in battle plans, with weapon racks
along the walls
```

### Hardware Hacking → `hardware-hacking.png`
```
a workbench pit of solder irons, tangled cabling and exposed circuit boards
pinned open on stone slabs
```

### Social Engineering → `social-engineering.png`
```
a masquerade bazaar of false storefronts and hanging masks, with empty stalls and
overturned crates
```

### Identity & Access → `identity-access.png`
```
a labyrinth of numbered doors set into stone walls, each with a tarnished brass
badge reader beside it
```

### Web Attacks → `web-attacks.png`
```
a caustic glowing green slime marsh creeping over cracked tiling, bubbling up
through broken drainage grates
```

### Codes and Ciphers → `codes-and-ciphers.png`
```
a frozen vault of enormous rotating brass cipher rings set into the floor, ringed
by frost-cracked stone
```

### Crypto → `crypto.png`
```
a sealed sanctum of tall glowing glyph-carved pillars arranged around a locked
central plinth
```

### Mobile Security → `mobile-security.png`
```
a shrine of hand-sized glowing slabs mounted on stone plinths in a small
candle-lit chamber
```

### Reverse Engineering → `reverse-engineering.png`
```
a dissection hall of opened machines with their gears and guts laid out in rows
on stone tables
```

### Malware Analysis → `malware-analysis.png`
```
a sealed quarantine cell with heavy barred doors and glowing warning sigils burnt
into the floor
```

---

## GROUND OVERLAYS (optional)

Scatter art laid over the base plate to break up its tiling (spec 023). Each is
placed **once** at large scale, so any number of them helps and none are
required — the map is correct with zero of these files present.

Save to `frontend/public/map/overlays/<filename>`. Transparent, like the tiles:
paste the **MASTER PROMPT** above, then the block below.

### Rubble drift → `rubble.png`
```
a wide, irregular scatter of broken stone, fallen masonry and gravel drifting
across bare cavern floor, thickest at the centre and thinning to nothing at the
edges, with no structure, no walls and no room shape of any kind
```

### Cracks → `cracks.png`
```
a branching network of deep cracks and fissures splitting bare bedrock, spreading
outward and fading to nothing at the edges, with no structure, no walls and no
room shape of any kind
```

### Scorch → `scorch.png`
```
a sprawling burn mark of blackened stone, soot and ash across bare cavern floor,
darkest at the centre and fading to nothing at the edges, with no structure, no
walls and no room shape of any kind
```

### Standing water → `water.png`
```
a shallow irregular pool of still dark water with faint teal reflections, seeping
across bare cavern floor and thinning to nothing at the edges, with no structure,
no walls and no room shape of any kind
```

For these four, append to the master prompt:

```
This is a ground detail overlay, not a location. It must have no enclosing
outline, no walls, no doorways and no defined room shape — only the material
itself, fading to fully transparent at every edge.
```

---

## CORRECTIVE PHRASES

Append to the master prompt when a result drifts.

```
The background must be genuinely transparent alpha, not a picture of
transparency. Do not draw a checkerboard pattern.
```

```
Viewed straight down from directly above only. Orthographic. No perspective, no
tilt, no isometric angle, no visible walls from the side.
```

```
Much darker overall. Deep shadow across most of the image, with only small
isolated pools of warm light.
```

```
The outline must be irregular and organic with rough rocky edges. Not a square,
not a circle, not a rounded rectangle.
```

```
Absolutely no text, letters, numbers, symbols or labels anywhere in the image.
```

```
Simpler, more readable layout with one clear central structure and less clutter.
```
