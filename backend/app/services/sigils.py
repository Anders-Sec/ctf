"""Procedural heraldic crests (spec 073 §4).

The default avatar used to be a coloured circle with one letter in it, which
fails the job it exists for: twenty people whose names begin with S are twenty
identical circles in a roster.

A crest is **deterministic from the user id** — same id, same bytes, for ever —
and distinguishable at 40px because it varies in four independent ways at once:
shield division, charge, and two colours. That is roughly 4 x 8 x 12 x 11
combinations before the field pattern, which is plenty for 200 players.

No GPU, no network, no setup. This is what everybody has on day one, and the
fallback whenever generation is unavailable or declined.
"""

import hashlib
import io
import math

from PIL import Image, ImageDraw

#: Rendered large and downsampled, because Pillow has no antialiasing on
#: polygons — drawing at 4x and shrinking is the cheap way to smooth edges.
SUPERSAMPLE = 4

#: Theme-invariant, per spec 048: a crest has to look deliberate on both the
#: light and the dark ground, so these are chosen to sit on either.
TINCTURES: list[tuple[str, tuple[int, int, int]]] = [
    ("gules", (166, 43, 49)),
    ("azure", (42, 78, 138)),
    ("vert", (46, 105, 66)),
    ("purpure", (104, 54, 122)),
    ("sable", (48, 48, 54)),
    ("tenne", (168, 94, 38)),
    ("murrey", (124, 40, 76)),
    ("bleu-celeste", (72, 132, 168)),
    ("cendree", (96, 100, 110)),
    ("sanguine", (132, 40, 40)),
    ("vairy", (64, 92, 110)),
    ("brunatre", (94, 68, 48)),
]

#: The lighter half of a division, and the charge's colour. Deliberately few:
#: metals are what make a crest legible when it is 40 pixels wide.
METALS: list[tuple[str, tuple[int, int, int]]] = [
    ("or", (214, 174, 84)),
    ("argent", (222, 222, 226)),
    ("copper", (198, 140, 96)),
    ("bone", (226, 214, 190)),
]

DIVISIONS = ["plain", "per-pale", "per-fess", "per-bend"]
CHARGES = ["mullet", "lozenge", "roundel", "chevron", "cross", "crescent", "pile", "bars"]


def _digest(user_id: str) -> list[int]:
    """A stable stream of numbers for one id.

    SHA-256 rather than ``hash()``, which is salted per process and would give a
    player a different crest on every API pod.
    """
    return list(hashlib.sha256(user_id.encode("utf-8")).digest())


def _shield(size: int) -> list[tuple[float, float]]:
    """A heater shield: straight sides, shoulders, and a point at the bottom."""
    w = h = size
    top, side = h * 0.06, w * 0.10
    return [
        (side, top),
        (w - side, top),
        (w - side, h * 0.52),
        (w * 0.5, h * 0.94),
        (side, h * 0.52),
    ]


def _charge(size: int, kind: str, colour: tuple[int, int, int]) -> Image.Image:
    """The charge on its own transparent layer, ready to composite.

    A layer rather than drawing straight onto the shield, because the crescent
    is made by *removing* part of a disc. Punching that hole in the shield
    itself showed the page through it — a transparent bite, not a crescent.
    """
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = size * 0.5, size * 0.42
    r = size * 0.19

    if kind == "mullet":
        points = []
        for index in range(10):
            angle = math.pi / 2 + index * math.pi / 5
            radius = r if index % 2 == 0 else r * 0.45
            points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
        draw.polygon(points, fill=colour)
    elif kind == "lozenge":
        draw.polygon(
            [(cx, cy - r), (cx + r * 0.7, cy), (cx, cy + r), (cx - r * 0.7, cy)], fill=colour
        )
    elif kind == "roundel":
        draw.ellipse([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], fill=colour)
    elif kind == "chevron":
        t = r * 0.42
        draw.polygon(
            [
                (cx - r, cy + r * 0.5),
                (cx, cy - r * 0.5),
                (cx + r, cy + r * 0.5),
                (cx + r - t * 0.8, cy + r * 0.5 + t * 0.4),
                (cx, cy - r * 0.5 + t),
                (cx - r + t * 0.8, cy + r * 0.5 + t * 0.4),
            ],
            fill=colour,
        )
    elif kind == "cross":
        t = r * 0.33
        draw.rectangle([cx - t, cy - r, cx + t, cy + r], fill=colour)
        draw.rectangle([cx - r, cy - t, cx + r, cy + t], fill=colour)
    elif kind == "crescent":
        draw.ellipse([cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85], fill=colour)
        # The bite. Cleared from this layer's alpha only, so whatever the
        # shield has underneath — field, or either half of a division — shows
        # through unharmed.
        bite = Image.new("L", (size, size), 255)
        ImageDraw.Draw(bite).ellipse(
            [cx - r * 0.35, cy - r * 0.95, cx + r * 1.15, cy + r * 0.65], fill=0
        )
        alpha = layer.split()[3]
        layer.putalpha(Image.composite(alpha, Image.new("L", (size, size), 0), bite))
    elif kind == "pile":
        draw.polygon([(cx - r, cy - r), (cx + r, cy - r), (cx, cy + r)], fill=colour)
    elif kind == "bars":
        for index in range(3):
            y = cy - r + index * r * 0.75
            draw.rectangle([cx - r, y, cx + r, y + r * 0.34], fill=colour)

    return layer


def render_sigil(user_id: str, size: int = 512) -> bytes:
    """A PNG crest for this id. Same id, same bytes."""
    stream = _digest(user_id)
    field = TINCTURES[stream[0] % len(TINCTURES)][1]
    second = TINCTURES[stream[1] % len(TINCTURES)][1]
    metal = METALS[stream[2] % len(METALS)][1]
    division = DIVISIONS[stream[3] % len(DIVISIONS)]
    charge = CHARGES[stream[4] % len(CHARGES)]

    # A division wants two colours that are actually different; neighbouring
    # tinctures at 40px are one colour with extra steps.
    if division != "plain" and second == field:
        second = TINCTURES[(stream[1] + 5) % len(TINCTURES)][1]

    big = size * SUPERSAMPLE
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    shield = _shield(big)
    draw.polygon(shield, fill=field)

    if division != "plain":
        half = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        hd = ImageDraw.Draw(half)
        if division == "per-pale":
            hd.rectangle([big * 0.5, 0, big, big], fill=second)
        elif division == "per-fess":
            hd.rectangle([0, big * 0.42, big, big], fill=second)
        else:  # per-bend
            hd.polygon([(0, 0), (big, big), (0, big)], fill=second)
        # Masked to the shield so a division never bleeds past the edge.
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).polygon(shield, fill=255)
        canvas.paste(
            half, (0, 0), Image.composite(mask, Image.new("L", (big, big), 0), half.split()[3])
        )
        draw = ImageDraw.Draw(canvas)

    canvas.alpha_composite(_charge(big, charge, metal))
    draw = ImageDraw.Draw(canvas)

    # The border last, so it sits over both halves of a division.
    draw.line(shield + [shield[0]], fill=(28, 28, 32), width=max(2, big // 90), joint="curve")

    out = io.BytesIO()
    canvas.resize((size, size), Image.LANCZOS).save(out, format="PNG", optimize=True)
    return out.getvalue()


def describe_sigil(user_id: str) -> str:
    """Plain words for the crest, for an ``alt`` attribute and for tests."""
    stream = _digest(user_id)
    field = TINCTURES[stream[0] % len(TINCTURES)][0]
    metal = METALS[stream[2] % len(METALS)][0]
    division = DIVISIONS[stream[3] % len(DIVISIONS)]
    charge = CHARGES[stream[4] % len(CHARGES)]
    shape = "a plain field" if division == "plain" else division.replace("-", " ")
    article = "an" if metal[0] in "aeiou" else "a"
    return f"A {field} shield, {shape}, bearing {article} {metal} {charge}."
