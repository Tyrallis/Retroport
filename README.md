# Retroport Workbench

Browse every retail World of Warcraft item and transmog set in 3D, pick the ones you want, and
backport them to your **3.3.5a (Wrath of the Lich King, 12340)** client and your **AzerothCore**
server - in one click, with a backup of everything it changes and an Undo.

## What it does

- **Browse** all of retail's items (about 99,000) and transmog sets (about 5,000). Search by name or
  id (the box at the start of the filters); filter by slot, armor or weapon type, expansion, quality
  and class. A set comes as one card
  with all its versions (Normal, Heroic, Mythic, a PvP season's Gladiator and Elite - and the colours
  of sets retail lists one per colour, like the 18 Sweatsuits), and items your client already has
  are marked.
- **See it in 3D** before you port it, animated, with its glows and moving textures: an item on its
  own, a set dressed on a character of any race your client plays (male or female), weapons and
  other one-kind sets one at a time with ◀ ▶. Every version is a click away under the preview.
- **Collect** what you like in the **Basket** - what the next install adds to your game. It shows
  every look each entry brings and the entries that overlap, so a mistake is easy to spot and remove
  (with Undo). Below it: what's **in your game** from earlier installs (every install keeps it; *take
  out* removes it at the next one), and **History** - your last five installs (and undos), each with
  *Put back in the basket*.
- **Give them stats** in **Stats** - every piece in the basket (to change something in your game, put
  it back in the basket from the History): item level, required
  level, quality, binding and armor type for every piece; armor type, the role its stats are for,
  which classes may wear it, stats, armor, weapon damage and speed, sockets and socket bonus,
  durability, price and *Unique* piece by piece - its in-game tooltip, and the piece in 3D under it,
  show the result as you go. *Fill in* uses WotLK's own rules (its stat budget for the item level and
  slot, split the way real WotLK items of the role split it, with armor, damage and durability as
  real WotLK items have them), or copy any real WotLK item's numbers. **Item sets** with set bonuses too:
  the bonuses come from your client's own item sets, with their in-game text.
- **Install** with one button, on the **Backport** page. It converts the basket for your client and
  adds it to what's in your game, installs the patch, adds the
  new items to your server's `Item.dbc` and `ItemDisplayInfo.dbc`, backs up everything it replaces,
  and can undo the whole install. It never touches your database: it shows the item SQL for you to
  apply.

## Spells (preview)

The **Spells** page shows retail's spells as the game plays them. Open a spell and its visual plays on
a stand-in caster (Jaina) and a training post 12 yards away: every model each event of the cast
(precast, cast, travel, impact, aura, channel, area trigger) puts on the caster, the target or the
ground, at its attachment point, offset, turn and scale, from its moment to its end, and the
missiles in flight - timed from the spell's retail cast time, missile speed and duration. A
timeline charts each model; pause, scrub and slow motion (down to a tenth) let you study it.

The first visit reads retail's spell tables from wago.tools once (a few minutes) into
`cache\spells-<build>.pickle`. Not shown yet: positioners (scripted paths - the model stays at
its point), caster animations, sounds, chain effects, and the extra layers of multi-texture
particles. Porting spells to a 3.3.5 client and server is the next step.

## Creatures (WarcraftXL clients with wxl.modern-m2)

The **Creatures** page ports retail's creatures and doodads. It needs a client that reads modern
models natively: the x64 WarcraftXL client with the `wxl.modern-m2` mod. Nothing is converted:
the client gets retail's own files.

- **Browse** every retail creature display (about 121,000), live from wago.tools. Search by name,
  model path, display id or creature id, and see each one in 3D with the same viewer the items use.
  Variations of one model (its other skins) are a click away.
- **Basket**: give each creature its name, subtitle, level, faction, rank and scale.
- **Install creatures** does it all in one go:
  1. It downloads the model, its skins, `.anim` files and every texture. Each file is named the way
     the client looks for it, under `Creature\Retroport\<model>\`, with a wow.export manifest so
     the mod resolves textures by FileDataID. A model whose skeleton lives in a `.skel` file is made
     self-contained first.
  2. It adds a CreatureModelData and a CreatureDisplayInfo row for each creature to the client's own
     tables, and packs everything into `Data\patch-R.MPQ`.
  3. It adds the same rows to the server's dbc folder. A copy of the originals is kept the first
     time, and every install builds on it.
  4. It writes `creature_template`, `creature_template_model` and `creature_model_info` rows, and
     **runs them** with the MySQL client on the world database that `worldserver.conf` names. Turn
     that off and it saves the SQL for you instead.

  Ids are kept per creature, so installing again (with new names, say) or taking one out never
  stacks rows. Restart the worldserver, then `.npc add <entry>` (each entry is listed with a copy
  button).
- **Not ported:** dressed humanoid NPCs (their look is baked from character parts), and models
  whose `.skel` builds on a shared parent skeleton.

## Download and run

1. Download `Retroport-Workbench-<version>-win64.zip` from the [Releases](../../releases) page.
2. Unpack the **whole** folder anywhere. Keep `runtime\` and `app\` next to the exe.
3. Run **Retroport Workbench.exe**. It opens in a window of its own; closing the window closes it.
   Windows may warn that the program is from an unknown publisher (it isn't code-signed): choose
   *More info*, then *Run anyway*.
4. The first time, **Settings** opens. Choose your 3.3.5a client folder (the one with `Wow.exe`), and
   optionally your server's dbc folder. That's all the setup there is.
5. Find items and sets, add them with **+**, look them over in **Basket**, give them stats in
   **Stats**, then **Backport > Install**. When it's done: apply the item SQL it shows to your world database, restart the
   worldserver, and log in.

## What you need

- **Windows 10 or 11.** The app's window is Microsoft Edge's app mode (Edge comes with Windows).
- **The internet.** Retail's items, models and textures come from [wago.tools](https://wago.tools).
  The first Install also downloads the two programs that do the conversion from their authors'
  GitHub pages (see [Credits](#credits)).
- **A 3.3.5a client** - a stock one works: it shows ported weapons, shields, helms, shoulders and
  every other slot's armor drawn on the body. *Optional:* the extra 3D pieces modern armor adds -
  skirts, collars, boot shells, belt buckles, 3D capes - need
  [WarcraftXL](https://github.com/WarcraftXL/wxl-core) and
  [Equip Plus](https://github.com/TheDaveCalaz/wxl-equip-plus) in your client. Install adds them when
  your client has Equip Plus, and leaves them out when it doesn't (Settings can turn them on or off).
- **Optionally, an AzerothCore server** whose dbc folder you point it at, so the new items exist on
  the server too.

## Settings

- **3.3.5a client folder** and **server dbc folder** - each *Browse...* opens Windows' folder picker,
  and each field says what it found there.
- **Where the items come from** - *wago.tools* (the default; nothing to install) or *your own retail
  install* (faster, and works while wago.tools is down; it needs the
  [WoWDBDefs](https://github.com/wowdev/WoWDBDefs) definitions folder and the
  [community listfile](https://github.com/wowdev/wow-listfile)). The bodies the character view
  dresses come from BfA 8.3.7, the same way.
- **Backport kit** - the project folder the conversion works in (a folder of its own: the kit fills
  it with its files). The kit and Equip Plus's tools are always the app's own copies, downloaded by
  the first Install at the versions this release is tested with - the same for everyone. Equip
  Plus's 3D pieces (when your client has Equip Plus, always, or never), and its live physics and
  better-fit options in your client.

Everything the app keeps is in your user folder:

| | |
|---|---|
| `%USERPROFILE%\.retroport\workbench.json` | your settings |
| `%USERPROFILE%\.retroport\workbench\` | the cache, your basket, the conversion project, the log (`workbench.log`) |

Everything it downloads is kept, so what you've already looked at still opens while wago.tools is
down.

## How Install works

1. The first time, it downloads the conversion kit and Equip Plus's tools.
2. It converts what's in your game and the basket - only what changed since the last build. Each
   install ticks its steps off as it goes, from a clear list, and a step that fails stops it before
   anything is installed (the log says why). Measuring how helms sit on your client's bodies (a few
   minutes, once per client) waits until something worn on the body is in the basket.
3. It applies the Stats step: the items' stats into the item SQL, a changed armor type into the
   client's and server's item tables, the item sets into their ItemSet tables.
4. It installs: the patch (and Equip Plus's pieces, when your client has Equip Plus) into your
   client's `Data` folder, the new rows into your server's DBCs, and clears the client's cache.
   Everything it replaces is backed up first.
5. You apply the item SQL it shows (`retroport-items.sql`: a `SOURCE` line with a copy button) to
   your world database, and restart the worldserver.

When it worked, the basket empties - what it held is in your game now - and the install goes into
the History (a failed one too, with the step it stopped at).

**Undo last install** puts back everything that install replaced and removes what it added (its
basket stays in the History).

**Coming from the Backport Helper?** The Workbench uses the same conversion project, and an Install
builds exactly what's in the basket. Looks the project built before - with the Backport Helper -
show at the top of the Basket: bring them into the basket to keep them in your game (Install waits
until you've chosen). They're rebuilt as they were, with the same kit and Equip Plus steps.

**Live physics.** Plumes, ribbons and chains can swing as in retail: the kit ports retail's own
Domino physics engine, and Equip Plus 1.3.0 runs it in the client (experimental, off by default).
Install writes each piece's physics data with Equip Plus 1.3.0's tools, and Settings has the switch
(*Live physics*, saved in your client's `WXLExtendedEquipment.ini` - also in Equip Plus's F9 panel in
game) next to its *better fit* options. Your client needs Equip Plus 1.3.0 or newer.

## Troubleshooting

- **The window doesn't appear.** Look at `%USERPROFILE%\.retroport\workbench\workbench.log`. Without
  Edge, the app opens in your default browser instead.
- **"Port 8335 is taken"** - another program uses the port the app listens on (only on your own
  machine, `127.0.0.1`). Close it and start the app again.
- **The first look at things is slow** - models and textures are being downloaded; they're kept
  for next time.
- **wago.tools is down** - Settings > *Where the items come from* > *My own install*.
- **Install stopped** - open the log under the Install button; nothing was installed by that run.
  Close World of Warcraft before installing: it holds the files Install replaces.
- **Install stopped at prove-gates: "M8 motion MISSED <- the gate is broken"** - a false alarm in
  0.1.0 (the kit's self-test planted a fault in a part of a model the patch doesn't ship); 0.2.0
  plants it where the check can see it. Update the app and Install again.
- **The kit's audit stopped the install** - the Backport page names each piece it stopped on, with
  *Leave this piece out*: the rest of its set installs, and the Basket page can put it back. A helm
  that only sits a little off on some bodies (often a race your client added) doesn't stop the
  install: it's listed as a warning - look at its picture (*preview pictures folder*: the kit draws
  one of each piece into the project's `sheets` folder).
- **"Retail uses something the kit hasn't seen before"** - new retail technology: the kit learns it
  for your project and goes on; the audit still checks every file it makes.
- **Which copy of the app is running?** - the version is next to the name at the top (hover it for
  the folder it runs from). Starting another copy while one runs asks to replace it.
- **The item SQL fails** - it's written for AzerothCore's world database. Install again after
  updating: older versions wrote a `StatsCount` column AzerothCore doesn't have, and a sell price can
  no longer go past what the column holds (429,496 gold).
- **Items ported before show a red question mark** - before 0.3.0 each install replaced what the
  last one put in, so earlier baskets' items lost their looks in the client while the server and
  your bags kept them; and a new project could give their numbers to other items. Put those sets in
  the basket again and Install: the Workbench now remembers every number any of your projects gave
  and gives a returning look its old numbers, so the items you carry show again.
- **Items are level 1 with no stats** - the conversion makes cosmetic copies; give them stats in
  **Stats** and Install again (the Backport page says how many pieces still have none).
- **No 3D preview** - the preview needs WebGL 2; update your graphics driver.

## Building from source

Python 3.11 or newer (3.14 is what it's tested with):

```
git clone https://github.com/kbtoy/Retroport
cd Retroport
python -m pip install -e ".[dev]"
python -m pytest -q tests

python -m retroport.cli workbench                      # run it in a console (opens your browser)
python packaging/build_release.py --launcher-only      # or: Retroport Workbench.exe next to the code
python packaging/build_release.py                      # the release folder and zip, in dist\
```

A release bundles Python's official embeddable package, the dependencies and the code, and checks
that it starts before it's zipped. Pushing a version tag (`v0.2.0`) builds it on GitHub and attaches
the zip to that release.

The Workbench's code is `retroport/workbench/` (the page in `static/`), its game-file readers are
`wotlkconv/` (an unchanged copy of the Converter, see below), and how it all works is in
[docs/workbench-internals.md](docs/workbench-internals.md). The rest of `retroport/` is shared code and
older command-line tools ([docs/command-line-tools.md](docs/command-line-tools.md)).

## Credits

Retroport Workbench is a front end to other people's work:

- **[wow-retail-backport](https://github.com/Kirazul/wow-retail-backport)** by **Kirazul** - the kit
  that converts retail items for 3.3.5a: everything Install builds.
- **[Equip Plus](https://github.com/TheDaveCalaz/wxl-equip-plus)** by **TheDaveCalaz** - the 3D armor
  pieces, and the tools that prepare them and merge the server's DBCs.
- **[WarcraftXL](https://github.com/WarcraftXL/wxl-core)** - the client framework Equip Plus runs on.
- **[wotlkconv (Converter)](https://github.com/Bar3b0n3s/Converter)** by the Converter contributors -
  the readers for the game's files.
- **[wago.tools](https://wago.tools)** - the game data; **[wowdev](https://wowdev.wiki)** -
  WoWDBDefs, the community listfile and the file-format documentation;
  **[WoW Blender Studio](https://gitlab.com/skarnproject/blender-wow-studio)** by **Skarn** - the
  shader tables the 3D preview follows; **[Conjure](https://github.com/TheDaveCalaz/Conjure)** by
  **TheDaveCalaz** - code retroport adapts.

The kit and Equip Plus are downloaded from their authors on first use and never bundled. The full
list, with every bundled library and its license, is [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT - see [LICENSE](LICENSE): use it, change it, share it, sell it, as you like. A few files in this
repository are under other terms; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) says which.

Retroport Workbench is a fan project, not affiliated with or endorsed by Blizzard Entertainment. It
ships no Blizzard art, models or game data: they're read at run time from wago.tools or your own
installs, for your own use. World of Warcraft and its assets are trademarks and copyright of
Blizzard Entertainment.
