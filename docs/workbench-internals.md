# Retroport Workbench - internals

A developer's reference: how the Workbench reads its data, builds its catalog, draws its previews
and drives the backport kit. For using it, see the [README](../README.md).

## How it's built

An application for anyone with a 3.3.5a client: `Retroport Workbench.exe` opens it in a window of
its own (Edge's app mode - no console, no browser tab; the server behind it listens on
`http://127.0.0.1:8335/` only). Closing the window closes it - after an Install that's running
has finished; started again while it runs, it opens another window on it. Its log is
`%USERPROFILE%\.retroport\workbench\workbench.log`.

- **Game data from wago.tools by default** - nothing to install: retail's tables (as wago's CSV)
  and its files by FileDataID at the newest live build, and BfA 8.3.7's for the bodies the
  character view dresses (`retroport/workbench/wago.py`; checked row-for-row and byte-for-byte
  against local installs at 12.1.5.70391 and 8.3.7.35435 - wago's tables also carry hotfixes).
  Everything fetched is kept on disk, so it opens again while wago is down.
- **Or your own installs** (Settings): a retail and a BfA install read directly - faster, and
  independent of wago; they need WoWDBDefs' definitions and the community listfile.
- **Settings** (the first run opens it): the 3.3.5a client folder, the server's dbc folder, where
  the items come from, the kit's project. Each Browse button opens Windows' own folder picker,
  and each field says what it found there.
- **The kit and Equip Plus are fetched, never bundled - and always the workbench's own copies**: the
  first Install downloads the retail backport kit (it carries no license, so it can't be passed on
  or changed and passed on) and Equip Plus's tools from their authors' GitHub at the commits this
  workbench is checked with (`retroport/workbench/deps.py`), into `<data>\deps`. No setting points
  the workbench at another copy (the Backport Helper's kit, a clone with edits of its own): what
  runs is the same for everyone, and a fix to how the kit runs lives in `kitlocal`.
- **What `kitlocal` changes in the kit's run** - in its process only, the kit's files untouched;
  each is a wrapper around the kit's own function, and each a fix to offer the kit's author:
  * open-folder patches: WarcraftXL clients mount a FOLDER named like an archive
    (`Data\patch-H.MPQ\...`, as Equip Plus installs its pieces); the kit's client reader is shown them;
  * cached tables an older kitlocal wrote with an `ID` column wago's don't have (ModelFileData,
    TextureFileData - newtech called the column new retail technology) are put right;
  * a sequence a model calls external but keys nothing for is made resident, and a model gets only
    the `.anim` files of sequences it streams (the kit copied a source model's every `.anim` to each
    per-race helm and the audit wanted thousands nobody had made: "C1/C2 closure ... .anim missing");
  * the build plan forgets displays no longer selected (the audit checked every display the plan
    ever held);
  * its `tables` step numbers items and displays around every id any of the workbench's projects
    ever gave (`--ids <data>\item-ids.json`, `retroport/workbench/itemids.py`): the kit only skips
    the ids its scanned client tables still hold, so a look taken out - or installed by another
    project, whose patch the new one's tables replace - left its numbers free for another look,
    while the server and players' bags kept the old item (a new project gave Dread Gladiator's
    weapons the numbers an earlier one had given Embered Guise of the Wight). Now no new look gets
    another's id, and a look that comes back gets its first ids again where no row of the client
    and no other look of the project has them. The workbench adds a project's `ids.json` to the
    registry after each tables step;
  * a helm that sits a little off a client body ("P1 placement") is a note, `P1 placement
    (warning)`, not a failure - prove-gates' own audit runs in a process of its own, unwrapped, so
    its planted misplaced helm is still caught;
  * prove-gates plants where the audit can see it (below).
- **The kit's gates, answered on the page**: newtech stopping on retail features the kit hasn't seen
  runs its own `newtech --learn` and the check again (`Kit.learn`); an audit that stops the install
  is listed on the Backport page by piece (`Kit.audit_notes`: a line's display from the
  `d<display>` it names or the model/texture its file was made from) with *Leave this piece out* -
  the basket entry keeps a `leave_out` list, and the kit selects that entry as its other looks
  (`--display` each; the select arguments are recorded with the selection, so leaving a piece out or
  putting it back is a new selection).
- **Its `prove-gates` (which plants 8 known defects in a copy of the build
  and expects the audit to catch each) is shown only the models a planted defect can show in: the
  manifest also lists files the build made but doesn't ship (a shoulder's untrimmed source beside
  its trimmed variant), and the "flying part" defect (M8) moves a model's first keyed bone, which a
  trimmed variant may not skin a single vertex to. Planted there, the defect moves nothing the
  audit reads and prove-gates calls the audit broken ("M8 motion MISSED"); the audit itself is not
  touched.

From a checkout: `python packaging/build_release.py --launcher-only` builds `Retroport Workbench.exe`
next to the code (it runs the `pythonw` on PATH), or run `retroport workbench` / `Workbench.bat` in a
console - with `--bfa` / `--retail <install> --dbd ... --listfile ...` to read local installs:

```
retroport workbench --bfa "<BfA install>" --retail "<retail install>" --client "<3.3.5 client>" ^
    --dbd "<WoWDBDefs\definitions>" --listfile "<listfile.csv>"
```

Options are remembered in `%USERPROFILE%\.retroport\workbench.json`. **A release** -
`python packaging/build_release.py` - is a folder and its zip: the launcher (built with the C#
compiler every Windows has), Python's official embeddable package with retroport's dependencies
and numpy, and the code (retroport, wotlkconv); it imports and serves the page with its own Python
before it's zipped. It holds nothing of Blizzard's, the kit's or Equip Plus's.

Each source's catalog is built from its own tables once per build (seconds; then under a second
from the cache) - every item with a look and a search name (89,490 in BfA 8.3.7, 99,076 in retail
12.1.5), its appearances and display ids, the transmog sets as families of versions
(Normal/Heroic/Mythic, a PvP set's seasons) and the classic item sets. A partial local retail
install fetches what it doesn't store from Blizzard's CDN, verified and kept in the cache.

- **Items**: search by name or by item, appearance or display id; filter by slot, armor or weapon
  type, expansion, quality, class; *one per look* folds items that share an appearance. Items your
  3.3.5 client already has (same id) are marked; Blizzard's test items are hidden unless asked.
- **Sets & collections**: one card per family with its pieces (a class set names its class: one PvP
  name covers a Hunter's, a Shaman's and an Evoker's looks). Retail lists some sets once per colour
  without linking them as versions (Aquatic, Azure, Brick... Sweatsuit; Prowler's Pink, Plum...
  Headgear): `catalog.fold_variants` makes three or more sets of no family of their own, named alike
  but for one colour word (`COLOR_WORDS` - another word is another set: a race's heritage armor, a
  season's plate), with the same slots and expansion, one family - the colour each one's label, the
  card named without it. The card of the family whose set is open stays marked whichever version is
  shown (`data-root`); the detail lists every version and
  piece, one per look - items that look the same (a Helm and a Faceguard for two armor types) under
  the one the set marks primary, "+1 same look". A set that is only a fragment of another of the
  same name - no version label or group, every look of it in the other (retail sells a PvP season's
  Elite looks two slots at a time as their own sets) - is folded into that one (717 in retail
  12.1.5; still found by id). Ids are the game's own - the ones the retail backport kit's
  `select --set/--item` takes.
- **Basket**: kept in the workbench folder; what the next Install adds to the game, to look over
  first. Each entry shows the looks it brings as the kit selects them - one per model: a set's
  pieces, every version of an item (an item set: of each of its items) - and opens in the drawer from
  its name or any look; one whose looks all come with another entry already says so, one that shares
  some says with which. × removes (with Undo); Empty the basket empties it.
- **In your game**: installs add up. What Install builds (`Workbench.install_list`) is what the last
  install put in the game - the entries recorded in its `install.json`, kept by every install - minus
  what's marked *take out* (`<project>\workbench-take-out.json`), then the basket; a basket entry
  stands for the game's entry of the same key (a piece left out of something installed copies its
  entry into the basket). An install that worked takes what it installed out of the basket and
  clears the take-outs; every install, worked or not, goes into `<data>\basket-history.json` (the
  last five: when, the result and the step it stopped at, the basket, what was taken out) - the
  Basket's *History*, each with *Put back in the basket*. Installs it has no record of (made before it
  kept one, or undone: Undo keeps an install's record as `install.json.undone`) come from the
  project's own records, each one's basket worked out as what it added to the install before it.
  The Stats page lists the basket's pieces only: something in the game gets new stats by going back
  in the basket.
- **Preview** (in an item's panel, at the top, its versions under it beside the race and sex -
  Normal / Heroic / Mythic, a PvP piece's Gladiator / Elite, named by the set that uses them, one
  per look - each a click away; a set's versions sit there too): its models
  in 3D (WebGL2: left-drag turns, right-drag moves, the wheel zooms, double-click resets), playing
  their Stand animation - bones, scrolling and turning textures, colour and transparency tracks,
  particle emitters - for a race and sex of the ones your 3.3.5 client plays (helms and shoulders
  differ; a race without its own model wears ChrRaces' fallback race's: a Nightborne the Night
  Elf's; heritage armor made for one race shows as theirs, and says so). A piece with no model -
  a cloth cloak (ModelType 5: its texture on the body's cape), armor drawn on the body - shows on
  a character wearing only it, a cloak from behind. Each batch is drawn with the client's
  own combiner for its shader id (the table for 0x8000 ids, the bits for older ones): how its up
  to three textures mix - a glow added over an environment map, a pattern moving under a mask -
  and whether each reads the first UVs, the second or the environment. Shoulders sit as worn; a
  held item stands up facing you: weapons and shields are modelled from the grip along +X, so +X
  goes up (an axe's head, a staff's crown, a shield's top) and you face the flat side (a shield's
  front is +Y; one modelled leaning, as it sits on the forearm, has its long axis stood up - the long
  axis of what it draws, each triangle weighted by its area, so a kite shield's chains and ribbons
  don't outweigh its face); a shield
  or off-hand modelled along Z instead (Shadowlands' PvP ones, lanterns: Dread Gladiator's Barrier,
  Reprieve, Galactic Warmonger's Lantern) has +Z up - a shield's top, the grip an off-hand hangs
  from; guns, bows and crossbows stay level. A texture animation moves the coordinates, not the
  texture: the first UVs by the batch's first transform, the second UVs by its second, an
  environment map by none (two textures on the first UVs move together - Venomous Aspirant's
  Chopper's leaves keep still while its glow, on the second UVs, scrolls). A held piece shown by itself has no race and sex to pick. A see-through batch
  isn't drawn until its texture is loaded (without it, it would be a solid grey card). A model's batches
  are drawn as the client draws them, by priority plane, lowest first (a hood's glowing eyes,
  priority 4, over its dark inside, priority 0). Armor drawn on the body shows its section textures. Icons and
  textures a source can't open (BfA 8.3.7 keeps its last sets' art encrypted) come from the other
  source.
- **A set of one kind** - weapons, masks, cloaks, shoulders - shows its pieces one at a time in that
  preview, ◀ ▶ (or the arrow keys) in the row under it to step through, the piece shown marked in
  the list.
- **On a character** (in any other set's panel, above its pieces): the set's first piece of each slot on
  BfA's body of the race and sex - `<race><sex>_hd.m2` for the classic races (the plain one is the
  pre-WoD model on the 512x512 layout), Kul Tiran and Pandaren their own - animated. Its skin is
  composited as the client does (CharSections skin, face, scalp, underwear on the race's layout -
  the HD rows, BaseSection 5-9, where the race has them - then each piece's section textures in
  dressing order); geosets from the race's hair and facial
  hair, then each piece's GeosetGroup values (a value the BfA body has no geoset for - retail has
  more boot shapes - takes the nearest below; retail's boots say -1, no feet, where its newer
  bodies' boots cover them, and BfA's body keeps its feet for the boot's foot texture, as BfA's own
  data has those boots), what a helm hides (HelmetGeosetData). ModelType 0
  models hang on body points (helm 11, shoulders 6/5, buckle 53...); ModelType 1 *collections* are
  skinned to the body's bones by bone name hash - one collection is shared by many items, and each
  shows only the parts of the body groups its slot controls (at 1 + its AttachmentGeosetGroup
  value). A piece opens on its own with a Back button.
- **Backport**: one **Install** puts the basket into the client and the server - it fetches the kit
  and Equip Plus the first time, creates the kit's project if there's none, has the kit `select` the
  basket when it changed since the last selection
  (which un-ticks every later step in the kit's ledger; an unchanged basket isn't selected or built
  again), runs every step that hasn't passed (scan when needed, with the kit's own patch out of Data
  meanwhile, then fetch ... sheet), then installs; its progress is ticked off step by step, the log
  is folded below, and a step that fails stops it before anything is installed. The folders are in
  Settings; the kit's own steps - *redo from here*, *Build only* - are folded away. The kit's
  preview pictures (its sheet step) stay in the project's `sheets` folder; the page only opens it
  (`/api/kit/open-sheets`, Explorer). Install / Undo work the Backport
  Helper's way (backups under
  `<project>\backups\<time>\install.json`, the helper's `last_backup` updated, so either tool undoes
  the other's): Equip Plus's 3D-piece patch, the kit's patches into Data, the client's Cache cleared,
  the server's Item/ItemDisplayInfo.dbc merged when a server dbc folder is set. The item SQL is never
  run - its `SOURCE` line is shown to apply yourself.

**Retail from your own install.** With `--retail`, a kit project pinned to that install's build
reads retail locally: `retroport/workbench/kitlocal.py` runs the kit unchanged and answers its
downloads (`wago._get`) from the install - tables as wago's CSV (checked text-identical to wago's
on ChrRaces, ParticleColor, ItemNameDescription, HelmetGeosetData at 12.1.5.70391), files by
FileDataID (byte-identical). What the install can't give - another build, a table its listfile
doesn't name, an encrypted file, the community listfile - still goes to wago.tools; each run
ends with a count of what came from where. wago's tables also carry Blizzard's hotfixes, which an
install's own tables don't (2 of ParticleColor's 2,122 rows at 12.1.5).

## The Stats step

The kit makes every look a cosmetic copy (its SQL says so: *any class, any race, level 1, no stats*),
one item per retail display id (`ids.json` maps display -> entry). The Stats page
(`static/stats.js`) gives each piece of the basket its game values,
kept in `<data>/item-stats.json`: item level, required level, quality and binding are *for every
piece* (`global`) only; armor type and the role the stats are for are for every piece unless a
piece sets its own; classes are each piece's own; stats, armor, damage, durability and price are
stored per piece as numbers. (An earlier version's every-piece classes, and a piece's own levels,
quality and binding, are tidied into that when the page loads.) The piece's model is shown under its
tooltip - the workbench's one viewer, which moves there from the item panel.

- **Fill in** follows WotLK's rules, from `retroport/workbench/wotlk.py` - Wrath Classic's tables
  (3.4.5.63697) on wago.tools, cached as one reference: the stat budget (`RandPropPoints`, by item
  level, quality and slot group), weapon damage per second (`ItemDamageOneHand`, `TwoHand`,
  `Ranged`, `Wand` and the caster tables), and armor, durability, speed and sell price as the real
  items of the same class, subclass, slot and quality have them (the median at each item level, a
  curve to interpolate). Stats are the budget split the way real items of the role split it, in
  WotLK's costs (a point of Stamina 2/3, attack power 1/2, spell power 6/7; the 1.5-power sum):
  an item-level-264 leather chest comes out Agility 159, Stamina 156, attack power 184 and two ratings
  at 104/92, armor 665, durability 120 - Sanctified Shadowblade Breastplate has 162, 162, 184,
  108/92, 665, 120. Caster weapons carry their power as spell power (2.41 x the slot-0 budget: 741
  at 264, as Frozen Bonespike and Nibelung). A piece filled in follows its level, quality, type
  and role as they change, until a number is edited by hand.
- **Copy a WotLK item** takes a real item's numbers (`/api/stats/reference`: the reference's 26,550
  equippable WotLK items, same slot first).
- **Set bonuses** are spells the 3.3.5 client has: every bonus of its own `ItemSet.dbc`, its
  `Spell.dbc` description with `$s1`, `$h`, `$d` and `$12345s1` filled in (`itemstats.spell_text`),
  or any spell by id. **Socket bonuses** are the enchantments real WotLK items use as one.

Right after the kit writes its item tables (`Kit.hooks["tables"]`, so the SQL is there even when a
later step stops) and again after its steps (`Kit.hooks["built"]`): a piece whose armor type changed
gets that subclass and material in the kit's `out/dbc/Item.dbc` (from the kit's own values, so it's
idempotent; after the steps, the kit packs again when the table changed); `out/sql/retroport-items.sql`
is the kit's SQL followed by one `UPDATE item_template` per piece - the file the Backport page shows.
A look the kit named after another retail item that shares it gets the name the Basket and Stats
show (`Workbench.look_names`; a name typed on the Stats page wins). The UPDATEs are AzerothCore's columns (it has no `StatsCount`: it counts the stats it loads), each
value kept inside its column's range (`itemstats.LIMITS`; `BuyPrice` as the int32 the worldserver
reads it as) - MySQL refuses a whole UPDATE with one value out of range, and the piece would stay
the kit's level-1 copy. After
the patches are placed (`Kit.hooks["installed"]`): the item sets (ids from 3000, kept per set in
`<data>/item-set-ids.json`) are added to the client's own `ItemSet.dbc` - read from below the kit's
patch - written *into* the kit's patch (`retroport.mpq.add_files`: the file is stored after the
archive's data, new hash and block tables follow, the header is changed last), and merged into the
server's `ItemSet.dbc` (backed up; Undo restores it).

## Looks built outside the workbench

The Backport Helper adds each selection to its project (`select --add`); the workbench uses the
same project and selects exactly the basket. So `Kit.foreign_looks` lists the displays the
project ever built (`ids.json` keeps them all) that the basket lacks and the workbench never chose
(`workbench-basket.json` "known"): the Basket offers to bring them in (as `look` entries, selected
with `--display`) or let them go (`/api/kit/let-go`), and Install waits until one is chosen.

## Equip Plus

Its 3D pieces need WarcraftXL with Equip Plus in the client: the 32-bit
`Extensions\wxl-equip-plus\wxl-equip-plus.dll`, or the 64-bit client's
`Mods\wxl.equip-plus\bin\x64\wxl-equip-plus.dll` (`kit._equip_plus_files` finds either; the 64-bit
one's settings file is in its mod folder). `KitSettings.equip_plus` is `auto` (run its
converter when the client has it), `on` or `off`; without it the kit's patch alone is installed,
which a stock client draws.

**Live physics**: the kit ports retail's Domino engine and
documents the client-mod contract (its `references/client-extension.md` section 5); Equip Plus 1.3.0
runs it, from `DBFilesClient\WXLEquipPlusPhysics.phy2`, which its converter (`physics_table.py`)
writes into the Equip Plus patch from the kit's `.phys` data. So the converter Install runs must be
1.3.0 or newer: `deps.PINNED` holds its commit, a fetched copy carries the commit it is
(`.retroport-ref`) and is fetched again when the pin moves. The client's DLL is new enough when it names that table. The switch
is the client's: `[Physics] Enabled` and `[Fit] RetargetPivots` / `RetargetScale` in
`WXLExtendedEquipment.ini`, which Settings changes in place (`Kit.set_equip_plus_options`: those keys
only, a copy of the file kept the first time).

The 64-bit Equip Plus (1.4.0) reads two more tables, written the same way by `physics.py` (which runs
Equip Plus's `physics_table.py` through `physics_job.py`): `WXLCreaturePhysics.phy2` in `patch-R`, from
each ported creature's and mount's `.phys`, and `WXLSpellPhysics.phy2` in `patch-S`, from the spell
models' (a model moved for its slot carries its offset as a shift). A retail model's older `SHOJ` joint
chunk is upgraded to `SHJ2` on the way. The preview runs the same engine in the browser:
`static/physics.wasm` (`physics_wasm/`), stepped after each pose by `viewer.js`.
