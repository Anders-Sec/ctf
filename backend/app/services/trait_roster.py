"""The authored trait vocabulary (spec 074 §2).

Eight axes. Players pick keys from these; the server turns the keys into a
prompt. **No player ever writes prompt text**, which is the single largest
decision in spec 074 and pays three times over: it removes NSFW prompts, slurs
and prompt injection outright rather than mitigating them; eight fragments tuned
once beat two hundred first attempts at prompt engineering; and the vocabulary
is the game's own, so a portrait looks like it came from this event.

It matters more here than it would elsewhere because **SDXL Turbo runs at
guidance_scale=0.0 and ignores negative prompts**, so the usual lever is not
available. The input vocabulary is the filter.

Seeded at boot like the accessory roster, and for the same reason: migrations in
this repo never import from ``app``, so a migration would mean a second copy of
this list in SQL.
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
        ("half-elf", "Half-Elf", "a half-elf with faintly pointed ears"),
        ("dwarf", "Dwarf", "a stout dwarf with a heavy braided beard"),
        ("halfling", "Halfling", "a small bright-eyed halfling"),
        ("gnome", "Gnome", "a small gnome with wild hair"),
        ("orc", "Orc", "a broad orc with tusks and green-grey skin"),
        ("half-orc", "Half-Orc", "a half-orc with small tusks"),
        ("tiefling", "Tiefling", "a tiefling with curling horns and ember eyes"),
        ("dragonborn", "Dragonborn", "a dragonborn with scaled draconic features"),
        ("goliath", "Goliath", "a towering goliath with stone-grey skin markings"),
        ("aasimar", "Aasimar", "an aasimar with faintly luminous skin"),
        ("firbolg", "Firbolg", "a tall firbolg with a long nose and kind eyes"),
        ("construct", "Construct", "a clockwork construct with a brass faceplate"),
    ],
)

#: One fragment per real class. The heaviest-lifting axis, and the one that ties
#: a portrait to progression rather than to a costume box — which is why the
#: builder defaults it to the player's actual class.
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
        ("script-kiddie", "Script Kiddie", "a hooded teenager surrounded by borrowed glyphs"),
        # The four mythic labels are the class names **exactly** as migration
        # 0027 spells them, because the builder defaults this axis to the
        # player's real class by matching on the name. Shortened labels here
        # meant four classes silently fell through to the default.
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
        ("robes", "Robes", "flowing layered robes"),
        ("plate", "Plate", "heavy articulated plate armour"),
        ("leather", "Leather", "worn practical leather armour"),
        ("chain", "Chain", "fine chain mail under a surcoat"),
        ("rags", "Rags", "patched travelling rags"),
        ("finery", "Finery", "embroidered courtly finery"),
        ("scholar", "Scholar's Coat", "a long scholar's coat with ink-stained cuffs"),
        ("furs", "Furs", "thick furs and leather straps"),
        ("vestments", "Vestments", "ceremonial vestments with metal thread"),
        ("workwear", "Workwear", "a heavy canvas apron over practical clothes"),
    ],
)

HEADWEAR = _traits(
    TraitAxis.HEADWEAR,
    [
        ("bare", "Bare", "bare-headed"),
        ("hood", "Hood", "a deep drawn hood"),
        ("helm", "Helm", "a battered steel helm"),
        ("circlet", "Circlet", "a thin silver circlet"),
        ("wide-hat", "Wide Hat", "a wide-brimmed pointed hat"),
        ("crown", "Crown", "a heavy iron crown"),
        ("bandana", "Bandana", "a knotted bandana"),
        ("veil", "Veil", "a fine drifting veil"),
        ("goggles", "Goggles", "brass goggles pushed up on the forehead"),
        ("laurel", "Laurel", "a laurel of dry leaves"),
    ],
)

EXPRESSION = _traits(
    TraitAxis.EXPRESSION,
    [
        ("stoic", "Stoic", "a calm unreadable expression"),
        ("grim", "Grim", "a grim set jaw"),
        ("weary", "Weary", "a tired patient expression"),
        ("fierce", "Fierce", "a fierce defiant stare"),
        ("amused", "Amused", "a faint knowing smile"),
        ("serene", "Serene", "a serene untroubled expression"),
        ("wary", "Wary", "a wary sidelong look"),
        ("delighted", "Delighted", "an open delighted grin"),
    ],
)

#: Drawn from the theme-invariant ladders (spec 048), so a portrait sits
#: deliberately on either ground rather than only on the one it was made for.
PALETTE = _traits(
    TraitAxis.PALETTE,
    [
        ("ember", "Ember", "a warm ember palette of rust, amber and deep red"),
        ("frost", "Frost", "a cold palette of pale blue, white and steel"),
        ("moss", "Moss", "an earthy palette of moss green, bark and ochre"),
        ("dusk", "Dusk", "a dusk palette of violet, indigo and faded rose"),
        ("bone", "Bone", "a bleached palette of bone, sand and grey"),
        ("ink", "Ink", "a near-monochrome palette of black, slate and paper white"),
        ("brass", "Brass", "a warm metallic palette of brass, copper and oiled leather"),
        ("verdigris", "Verdigris", "a palette of oxidised copper green and weathered stone"),
        ("wine", "Wine", "a rich palette of wine red, gold and shadow"),
        ("storm", "Storm", "a storm palette of grey, white and sudden pale blue"),
    ],
)

SETTING = _traits(
    TraitAxis.SETTING,
    [
        ("plain", "Plain", "a plain neutral background"),
        ("dungeon", "Dungeon", "a dark stone dungeon corridor behind them"),
        ("forest", "Forest", "a deep misted forest behind them"),
        ("tavern", "Tavern", "a warm crowded tavern behind them"),
        ("library", "Library", "towering shelves of scrolls behind them"),
        ("arcane", "Arcane", "a circle of drifting arcane glyphs behind them"),
        ("void", "Void", "an empty starless void behind them"),
        ("forge", "Forge", "a glowing forge behind them"),
        ("battlement", "Battlement", "a windswept castle battlement behind them"),
        ("server-crypt", "Server Crypt", "racks of humming machines behind them, lit from below"),
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

ALL_AXES: list[list[Trait]] = [
    ANCESTRY,
    CLASS_LOOK,
    GARB,
    HEADWEAR,
    EXPRESSION,
    PALETTE,
    SETTING,
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


async def seed(db: AsyncSession, *, overwrite: bool = False) -> int:
    """Insert anything missing. Returns how many rows were added.

    Idempotent on (axis, key). Existing rows are left alone unless `overwrite`,
    so an operator who retuned a fragment during setup keeps it.
    """
    existing = {
        (axis, key)
        for axis, key in (await db.execute(select(AvatarTrait.axis, AvatarTrait.key))).all()
    }

    added = 0
    for order, trait in enumerate(authored_traits()):
        if (trait.axis, trait.key) in existing and not overwrite:
            continue
        if (trait.axis, trait.key) in existing:
            row = (
                await db.execute(
                    select(AvatarTrait).where(
                        AvatarTrait.axis == trait.axis, AvatarTrait.key == trait.key
                    )
                )
            ).scalar_one()
        else:
            row = AvatarTrait(axis=trait.axis, key=trait.key)
            db.add(row)
            added += 1
        row.label = trait.label
        row.prompt_fragment = trait.fragment
        row.display_order = order

    await db.flush()
    logger.info("trait_roster.seeded", extra={"added": added})
    return added
