"""The authored trait vocabulary (spec 074 §2, rewritten by §11.2).

Seven axes. Players pick keys from these; the server turns the keys into a
prompt. **No player ever writes prompt text**, which is the single largest
decision in spec 074 and pays three times over: it removes NSFW prompts, slurs
and prompt injection outright rather than mitigating them; fragments tuned once
beat two hundred first attempts at prompt engineering; and the vocabulary is the
game's own, so a portrait looks like it came from this event.

It matters more here than it would elsewhere because **SDXL Turbo runs at
guidance_scale=0.0 and ignores negative prompts**, so the usual lever is not
available. The input vocabulary is the filter.

Seeded at boot, for the same reason the accessory roster is: migrations in this
repo never import from ``app``, so a migration would mean a second copy of this
list in SQL.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.avatar_trait import AvatarTrait, TraitAxis

logger = get_logger(__name__)

#: Every assembled prompt ends with this. Turbo ignores a negative prompt, so
#: the only steer available is the positive one — and it steers hard towards
#: **painted portrait**, which is designing with the model's grain rather than
#: against it. Turbo at 512 is weak at photoreal faces and good at stylised
#: work, and a painted portrait also sidesteps the uncanny-valley failure that
#: made work-photo transformation a bad idea in the first place.
STYLE_SUFFIX = (
    "fantasy character portrait, head and shoulders, painted illustration, "
    "clean background, centred composition, tabletop role-playing game art"
)


@dataclass(frozen=True)
class Trait:
    axis: TraitAxis
    key: str
    label: str
    fragment: str


def _traits(axis: TraitAxis, rows: list[tuple[str, str, str]]) -> list[Trait]:
    return [Trait(axis, key, label, fragment) for key, label, fragment in rows]


ANCESTRY = _traits(
    TraitAxis.ANCESTRY,
    [
        ("human", "Human", "a human"),
        ("elf", "Elf", "a slender elf with long pointed ears"),
        ("dwarf", "Dwarf", "a stout dwarf, broad-shouldered, hair worked into braids"),
        ("halfling", "Halfling", "a small bright-eyed halfling"),
        ("orc", "Orc", "a broad orc with tusks and green-grey skin"),
        ("tiefling", "Tiefling", "a tiefling with curling horns and ember eyes"),
        ("dragonborn", "Dragonborn", "a dragonborn with scaled draconic features"),
        ("gnome", "Gnome", "a small gnome with wild hair and bright eyes"),
        ("celestial", "Celestial", "an aasimar with faintly luminous skin and pale gold eyes"),
        ("fiendish", "Fiendish", "a fiend-touched figure, skin like banked coals"),
    ],
)

#: One fragment per class in the 48-roster. **Not all of these are offered.**
#: The builder shows only the classes a player has unlocked, and nothing at all
#: below `class_unlock_level` — the same gate that already governs choosing a
#: class, reused rather than reinvented (spec 074 §11.2). Every fragment stays
#: in the table so the lookup works whichever class they end up earning.
CLASS_LOOK = _traits(
    TraitAxis.CLASS_LOOK,
    [
        ("barbarian", "Barbarian", "a barbarian in furs and warpaint"),
        ("fighter", "Fighter", "a fighter in dented practical plate"),
        ("berserker", "Berserker", "a berserker with scarred arms and wild eyes"),
        ("rogue", "Rogue", "a rogue half in shadow, hood up"),
        ("ranger", "Ranger", "a ranger in oiled leathers with a bowstring across the chest"),
        ("assassin", "Assassin", "an assassin in dark close-fitted cloth"),
        ("guardian", "Guardian", "a guardian behind a tower shield"),
        ("juggernaut", "Juggernaut", "a juggernaut in overlapping heavy plate"),
        ("warden", "Warden", "a warden in bark-green armour with a sprig at the collar"),
        ("wizard", "Wizard", "a wizard in star-strewn robes with a wide-brimmed hat"),
        ("artificer", "Artificer", "an artificer with brass goggles and tool harness"),
        ("archmage", "Archmage", "an archmage wreathed in slow arcane light"),
        ("cleric", "Cleric", "a cleric in white and gold with a holy symbol"),
        ("druid", "Druid", "a druid crowned with antlers and living leaves"),
        ("oracle", "Oracle", "an oracle with bound eyes and a serene expression"),
        ("bard", "Bard", "a bard in bright travelling clothes with a feathered cap"),
        ("warlock", "Warlock", "a warlock with an eldritch sigil burning at the throat"),
        ("sorcerer", "Sorcerer", "a sorcerer with static crackling through their hair"),
        ("analyst", "Analyst", "an analyst surrounded by floating glyph-tables"),
        ("technician", "Technician", "a technician draped in cable and copper wire"),
        ("auditor", "Auditor", "an auditor in severe grey with a ledger chained to their belt"),
        ("help-desk-adept", "Help Desk Adept", "a weary adept behind a counter of scrolls"),
        ("sysadmin", "Sysadmin", "a sysadmin in a coffee-stained robe, keys on a lanyard"),
        ("compliance-officer", "Compliance Officer", "a compliance officer with a wax seal stamp"),
        ("junior-pentester", "Junior Pentester", "a young pentester with lockpicks and a grin"),
        ("scanner", "Scanner", "a scanner with a lens array over one eye"),
        ("packet-sage", "Packet Sage", "a sage wrapped in woven cable, eyes closed, listening"),
        ("cipher-adept", "Cipher Adept", "an adept in a mask of shifting engraved glyphs"),
        ("shadow-broker", "Shadow Broker", "a broker veiled, face unreadable, ledger in hand"),
        ("signal-hunter", "Signal Hunter", "a hunter with an antenna crown and a far-off stare"),
        ("wire-stalker", "Wire Stalker", "a stalker in a coat of frayed wire"),
        ("breachwright", "Breachwright", "a breachwright with a cracked door-sigil pauldron"),
        ("voidcoder", "Voidcoder", "a coder whose outline is faintly absent, edges unresolved"),
        ("ghost-handler", "Ghost Handler", "a handler trailed by a pale indistinct second figure"),
        ("ashborn-analyst", "Ashborn Analyst", "an analyst in ash-grey with ember-lit eyes"),
        ("sentinel-prime", "Sentinel Prime", "a sentinel in seamless white ceramic armour"),
        ("cryptomancer", "Cryptomancer", "a cryptomancer crowned with rotating key-sigils"),
        ("root-ascendant", "Root Ascendant", "an ascendant haloed in pale command-light"),
        ("the-unwritten", "The Unwritten", "a figure with a perfectly blank featureless mask"),
        (
            "herald-of-zero-day",
            "Herald of Zero-Day",
            "a herald with forward-curving horns and a broken seal",
        ),
        ("researcher", "Researcher", "a researcher surrounded by pinned notes and string"),
        ("archivist", "Archivist", "an archivist in dust-grey with a ring of brass keys"),
        ("triage-nurse", "Triage Nurse", "a triage nurse in stained whites, sleeves rolled"),
        ("script-kiddie", "Script Kiddie", "a hooded figure surrounded by borrowed glyphs"),
        (
            "architect-crypt-covenant",
            "Architect of the Unbreakable Crypt-Covenant",
            "an architect of impossible vaults, blueprint light in the air",
        ),
        (
            "imperator-core-kernel",
            "Imperator of the Core-Kernel Continuum",
            "an imperator in absolute regalia, cold and still",
        ),
        (
            "avatar-quantum-superposition",
            "Avatar of the Quantum Superposition",
            "a figure blurred across several overlapping positions",
        ),
        (
            "sovereign-zero-day-nexus",
            "Sovereign of the Absolute Zero-Day Nexus",
            "a sovereign in frost-white crowned with absolute zero",
        ),
    ],
)

GARB = _traits(
    TraitAxis.GARB,
    [
        ("plate", "Heavy Plate Mail", "heavy articulated plate mail, dented and field-repaired"),
        ("scouting", "Leather Scouting Gear", "oiled leather scouting gear with buckled straps"),
        (
            "robes",
            "Flowing Sorcerer Robes",
            "long flowing sorcerous robes, layered and embroidered",
        ),
        ("noble", "Elegant Noble Attire", "elegant noble attire in fine cloth with metal thread"),
        ("hood", "Tattered Rogue Hoods", "a tattered layered hood and travel-worn wraps"),
    ],
)

EXPRESSION = _traits(
    TraitAxis.EXPRESSION,
    [
        ("determined", "Determined", "a determined, focused expression"),
        ("confident", "Confident", "a confident half-smirk"),
        ("serene", "Serene", "a serene, untroubled expression"),
        ("fierce", "Fierce", "a fierce, gritty stare"),
        ("weary", "Weary", "a weary, patient expression"),
        ("amused", "Amused", "a quietly amused expression"),
        ("watchful", "Watchful", "a watchful, guarded look"),
    ],
)

PALETTE = _traits(
    TraitAxis.PALETTE,
    [
        ("warm", "Warm — Crimson & Gold", "a warm palette of crimson and gold"),
        ("cool", "Cool — Arctic Blue & Silver", "a cool palette of arctic blue and silver"),
        ("earthy", "Earthy — Forest Green & Brown", "an earthy palette of forest green and brown"),
        ("shadow", "Shadow — Obsidian & Purple", "a shadowed palette of obsidian and deep purple"),
        ("radiant", "Radiant — White & Gold", "a radiant palette of white and gold"),
    ],
)

#: How the portrait **reads**, not who the player is — which is why every label
#: says "-presenting", and why there is no fourth "prefer not to say": leaving
#: the axis on "Any" already is that, and Any is the default on every axis
#: (spec 074 §11.2). These fragments are art direction and describe nobody.
PRESENTATION = _traits(
    TraitAxis.PRESENTATION,
    [
        ("masculine", "Masculine-presenting", "masculine-presenting features"),
        ("feminine", "Feminine-presenting", "feminine-presenting features"),
        ("androgynous", "Androgynous-presenting", "androgynous features"),
    ],
)

ART_STYLE = _traits(
    TraitAxis.ART_STYLE,
    [
        ("oil", "Oil Painting", "oil painting, visible brushwork"),
        ("ink", "Ink and Wash", "ink and wash, confident linework"),
        ("woodcut", "Woodcut", "woodcut print, bold carved lines"),
        ("illuminated", "Illuminated", "illuminated manuscript, gold leaf, flat perspective"),
        ("watercolour", "Watercolour", "loose watercolour, soft bleeding edges"),
        ("charcoal", "Charcoal", "charcoal drawing, smudged shadow"),
        ("stained-glass", "Stained Glass", "stained glass, heavy leading, luminous colour"),
        ("storybook", "Storybook", "storybook illustration, warm and rounded"),
    ],
)

#: Order matters twice: it is the order the axes appear in the builder, and the
#: order their fragments are joined into the prompt. Subject first, then what
#: they wear and how they look, then how it is painted — which reads to the
#: model roughly the way it reads to a person.
ALL_AXES: list[list[Trait]] = [
    ANCESTRY,
    PRESENTATION,
    CLASS_LOOK,
    GARB,
    EXPRESSION,
    PALETTE,
    ART_STYLE,
]


def authored_traits() -> list[Trait]:
    return [trait for axis in ALL_AXES for trait in axis]


def assemble_prompt(fragments: list[str]) -> str:
    """Turn chosen fragments into the one string the model sees.

    The only place a prompt is built, and it takes fragments the caller has
    already resolved from the database — so there is no path from a request body
    to this function that does not pass through key validation.
    """
    return ", ".join([*fragments, STYLE_SUFFIX])


async def seed(db: AsyncSession) -> int:
    """Make the table match the roster. Returns how many rows were added.

    **The authored list is the source of truth for label and fragment**, so a
    deploy that rewords an option actually rewords it. That is a change from the
    first version, which skipped rows that already existed — and would have left
    spec 074 §11.2's new vocabulary sitting underneath the old one, invisible.

    The operator's lever is `enabled`, which is never overwritten here: pull a
    fragment that is producing bad portraits and it stays pulled.

    Anything no longer authored is **disabled, not deleted**. Retired options
    must stop being offered, but a job that recorded one still has to be
    explicable months later.
    """
    rows = (await db.execute(select(AvatarTrait))).scalars().all()
    by_pair = {(row.axis, row.key): row for row in rows}
    authored = authored_traits()

    added = 0
    for order, trait in enumerate(authored):
        row = by_pair.get((trait.axis, trait.key))
        if row is None:
            row = AvatarTrait(axis=trait.axis, key=trait.key, enabled=True)
            db.add(row)
            added += 1
        row.label = trait.label
        row.prompt_fragment = trait.fragment
        row.display_order = order

    wanted = {(trait.axis, trait.key) for trait in authored}
    retired = 0
    for (axis, key), row in by_pair.items():
        if (axis, key) not in wanted and row.enabled:
            row.enabled = False
            retired += 1

    await db.flush()
    logger.info("trait_roster.seeded", extra={"added": added, "retired": retired})
    return added
