# Retroport Workbench

Bring retail World of Warcraft to your **3.3.5a (Wrath of the Lich King, 12340)** client and your
**AzerothCore** server: items and transmog sets, creatures, mounts and spells, each seen in 3D first
and installed in one click, with a backup of everything it changes.

This is the `creatures` branch of [Tyrallis/Retroport](https://github.com/Tyrallis/Retroport), a fork
of [kbtoy/Retroport](https://github.com/kbtoy/Retroport). Its downloads are on the
[Releases](https://github.com/Tyrallis/Retroport/releases) page.

## Pages

| Page | What it's for | Client it needs |
|---|---|---|
| **Items**, **Sets & collections** | retail armour, weapons and transmog sets | any 3.3.5a client |
| **Creatures** | retail creatures and doodads as NPCs | the 64-bit WarcraftXL client with `wxl.modern-m2` |
| **Spells** | new spells with retail's visuals, sounds and glows | the same, plus `wxl.retail-spellvisuals` for the full retail look |
| **Mounts** | retail mounts, with their summon spell and reins | the same as Creatures |
| **Basket**, **Stats**, **Backport** | the item basket, the items' stats, and the item Install | |
| **Settings** | your client and server folders, data source, Equip Plus options | |

The 64-bit client and its mods are listed under [The client](#the-client).

### Items and sets

- **Browse** all of retail's items (about 99,000) and transmog sets (about 5,000). Search by name or
  id; filter by slot, armor or weapon type, expansion, quality and class. A set comes as one card
  with all its versions (Normal, Heroic, Mythic, a PvP season's Gladiator and Elite, and the colours
  of sets retail lists one per colour). Items your client already has are marked.
- **See it in 3D**, animated, with its glows, moving textures and **live physics** (plumes, cloth,
  chains swing as in retail): an item on its own, or a set dressed on a character of any race your
  client plays, male or female.
- **Basket**: everything the next install adds, with every look each entry brings and what overlaps.
  Below it: what's **in your game** from earlier installs (*take out* removes it at the next one),
  and **History**, your last five installs, each with *Put back in the basket*.
- **Stats**: item level, required level, quality, binding, armor type, classes, stats, armor, weapon
  damage and speed, sockets and socket bonus, durability, price, *Unique*, piece by piece, with its
  in-game tooltip and the piece in 3D. *Fill in* uses WotLK's own rules (its stat budget for the item
  level and slot), or copies any real WotLK item's numbers. **Item sets** with set bonuses from your
  client's own sets.
- **Backport > Install** converts the basket, installs the patch, adds the new items to your
  server's `Item.dbc` and `ItemDisplayInfo.dbc`, backs up everything it replaces, and can undo the
  whole install. It shows the item SQL for you to apply.

### Creatures

Retail's own models, unconverted: the client reads them with `wxl.modern-m2`.

- **Browse** every retail creature display (about 121,000), live from wago.tools. Search by name,
  model path, display id or creature id. See each in 3D with its retail glow and physics, along with
  its other skins and its abilities (read from Wowhead).
- **Basket**: give each one its name, subtitle, level, faction, rank and scale.
- **Install creatures**:
  1. It exports the model, skins, `.anim` files, textures and sounds under
     `Creature\Retroport\<model>\`. A model whose skeleton lives in a `.skel` file is made
     self-contained first.
  2. It adds CreatureModelData, CreatureDisplayInfo and SoundEntries rows to the client's own
     tables and packs everything into `Data\patch-R.MPQ`.
  3. It writes a **physics table** (`WXLCreaturePhysics.phy2`) for every model with retail physics
     (hair, cloth, tails, wings), which `wxl.equip-plus` runs live in game.
  4. It adds the same rows to the server's DBCs (the originals are kept the first time).
  5. It writes the `creature_template`, `creature_template_model` and `creature_model_info` rows and
     **runs them** on the world database named in `worldserver.conf`, or saves the SQL for you to
     apply.

  Ids are kept per creature, so installing again never stacks rows. Restart the worldserver, then
  `.npc add <entry>` (each entry has a copy button). An option closes and restarts the client and
  the worldserver for you.
- **Not ported:** dressed humanoid NPCs (their look is built from character parts), and models whose
  `.skel` builds on a shared parent skeleton.

### Spells

- **Browse** retail's spells the way Wowhead groups them: class abilities, specializations,
  talents, hero talents, PvP talents, glyphs, pet abilities, mounts, racial traits, professions and
  the expansion systems. Each spell shows its Wowhead tooltip.
- **Watch it in 3D** as the game plays it, on **your own character**: pick a race and sex, and BfA's
  character body plays retail's caster animations, in the shapeshift form the spell needs. The target
  is a training dummy 12 yards away. Every model of every event of the cast is shown, at its
  attachment point, offset, turn and scale, from precast to impact, aura and channel, with missiles
  in flight and the caster's **body glow** (Avenging Wrath's gold, Bestial Wrath's red). A timeline
  charts each model, with pause, scrub and slow motion.
- **Make a new spell**: choose the retail spell for its **look** and a 3.3.5 spell as its
  **template** for how it works (damage, aura, cast time). The new spell gets retail's name, icon,
  text, visual and sounds, and its own id.
- **Install new spells** writes `Data\patch-S.MPQ`: the spell, its visual and kits, the retail
  models (as Creatures exports them), sounds, icons, and a physics table for spell models (Avenging
  Wrath's wings). The server's `Spell.dbc` gets the same rows. Learn a spell with `.learn <id>`
  (copy button).
  - **Retail visuals**, per spell: on, `wxl.retail-spellvisuals` plays every retail model at retail's
    moments, offsets, turns and delays, with the body glow; off, the visual fits 3.3.5's own kits.
  - **Retail caster animations**: for WoD or BfA character models, the spells play retail's own
    animations.
  - **BfA character bodies**: Install also puts BfA's bodies for every classic race into your client
    (`Data\patch-I.MPQ`); turning it off brings your own back.
  - **Fly everywhere**: flying mounts fly in Eastern Kingdoms, Kalimdor, Outland, Northrend and
    Dalaran (`AreaTable.dbc` in the client and the server).
  - **Restart** closes the client and the worldserver for the install and starts them again.

### Mounts

- **Browse** retail's mounts, ground and flying, in 3D.
- **Install mounts** makes the four things a 3.3.5 mount is, from retail's: its **creature** (model,
  skins, sounds, physics, mount height), its **spell** (retail's name, icon and summon visual on a
  3.3.5 mount spell, with the mount's speeds), its **item** (reins that teach the spell) and its
  **speeds** (from retail's mount type, changeable per mount).

## The client

Items work in any 3.3.5a client. Creatures, mounts and spells use retail's models as they are, so
they need the 64-bit client built from source with WarcraftXL, and these mods in its `Mods` folder:

| Mod | What it does here |
|---|---|
| [wxl.modern-m2](https://github.com/Tyrallis/wxl.modern-m2) | reads retail's models (required for creatures, mounts, spells) |
| [wxl.equip-plus](https://github.com/Tyrallis/wxl.equip-plus) | extra 3D armour pieces, and **live retail physics** for items, creatures, mounts and spell models (F9 opens its panel) |
| [wxl.retail-spellvisuals](https://github.com/Tyrallis/wxl.retail-spellvisuals) | retail spell visuals and body glows for spells ported with *Retail visuals* on |
| [wxl.unit-outline](https://github.com/Tyrallis/wxl.unit-outline) | retail-style outline on your target and mouseover |

The client: [Tyrallis/client](https://github.com/Tyrallis/client/tree/x64-port), with
[core](https://github.com/Tyrallis/core/tree/x64-port) and
[sdk](https://github.com/Tyrallis/sdk/tree/x64-port), all on the `x64-port` branch. The
[Releases](https://github.com/Tyrallis/Retroport/releases) page has a step-by-step install guide.

## Download and run

1. Download `Retroport-Workbench-<version>-win64.zip` from the
   [Releases](https://github.com/Tyrallis/Retroport/releases) page.
2. Unpack the **whole** folder anywhere. Keep `runtime\` and `app\` next to the exe.
3. Run **Retroport Workbench.exe**. It opens in a window of its own; closing the window closes it.
   Windows may warn that the program is from an unknown publisher (it isn't code-signed): choose
   *More info*, then *Run anyway*.
4. The first time, **Settings** opens. Choose your client folder, and optionally your server's dbc
   folder.

## What you need

- **Windows 10 or 11.** The app's window is Microsoft Edge's app mode (Edge comes with Windows).
- **The internet.** Retail's tables, models, textures and sounds come from
  [wago.tools](https://wago.tools). Spell tooltips and creature abilities come from Wowhead. The
  first Install downloads the conversion kit and Equip Plus's tools from their authors' GitHub
  pages (see [Credits](#credits)).
- **A 3.3.5a client**: any client for items; the 64-bit WarcraftXL client for the rest (see
  [The client](#the-client)).
- **An AzerothCore server** for creatures, mounts and spells, and optionally for items: point
  Settings at its dbc folder. The creature and mount installs use the MySQL client and
  `worldserver.conf` to write their rows.

## Settings

- **Client folder** and **server dbc folder**: each *Browse...* opens Windows' folder picker, and
  each field says what it found there.
- **Where the data comes from**: *wago.tools* (the default; nothing to install) or *your own retail
  install* (faster, and works while wago.tools is down; it needs the
  [WoWDBDefs](https://github.com/wowdev/WoWDBDefs) definitions and the
  [community listfile](https://github.com/wowdev/wow-listfile)). The character bodies come from BfA
  8.3.7, the same way.
- **Backport kit**: the project folder the item conversion works in. The kit and Equip Plus's tools
  are downloaded by the first Install, at the versions this release is tested with.
- **Equip Plus**: its 3D pieces (when your client has Equip Plus, always, or never), its **live
  physics** switch (saved in the client's `WXLExtendedEquipment.ini`, and also in Equip Plus's F9
  panel in game) and its *better fit* options.

Everything the app keeps is in your user folder:

| | |
|---|---|
| `%USERPROFILE%\.retroport\workbench.json` | your settings |
| `%USERPROFILE%\.retroport\workbench\` | the cache, your baskets, your spell ports, the conversion project, the log (`workbench.log`) |

Everything it downloads is kept, so what you've already looked at still opens while wago.tools is
down.

## How the item Install works

1. The first time, it downloads the conversion kit and Equip Plus's tools.
2. It converts what's in your game and the basket, rebuilding only what changed since the last
   build. Each step is ticked off as it runs, and a step that fails stops the install before
   anything is installed (the log says why).
3. It applies the Stats step: stats into the item SQL, armor types into the client's and server's
   item tables, item sets into their ItemSet tables.
4. It installs the patch into your client's `Data` folder. With Equip Plus it also installs its
   pieces and their physics table. It adds the new rows to your server's DBCs and clears the client's
   cache. Everything it replaces is backed up first.
5. You apply the item SQL it shows (`retroport-items.sql`, with a copy button) to your world
   database, and restart the worldserver.

**Undo last install** puts back everything that install replaced and removes what it added.

Each kind of port has its own patch: items in the kit's patch, creatures in `patch-R`, spells and
mounts' spells in `patch-S`, BfA bodies in `patch-I`. Removing a port and installing again rebuilds
that patch without it.

## Troubleshooting

- **The window doesn't appear.** Look at `%USERPROFILE%\.retroport\workbench\workbench.log`. Without
  Edge, the app opens in your default browser instead.
- **"Port 8335 is taken"**: another program uses the port the app listens on (only on your own
  machine, `127.0.0.1`). Close it and start the app again.
- **The first look at things is slow**: models and textures are being downloaded, and kept for next
  time. The first visit to Spells reads retail's spell tables once (a few minutes).
- **wago.tools is down**: Settings > *Where the data comes from* > *My own install*.
- **Install stopped**: open the log under the Install button; nothing was installed by that run.
  Close World of Warcraft before installing, because it holds the files Install replaces (or use the
  restart option).
- **A creature or spell is invisible in game**: the client needs `wxl.modern-m2` in its `Mods`
  folder (see `Logs\WarcraftXL.log`).
- **Nothing swings**: press F9 in game and tick *Physics*. Physics needs `wxl.equip-plus` 1.4.0 or
  newer, and the models' physics tables come with the next Install.
- **A spell shows only part of its retail look**: turn on *Retail visuals* for it and install
  `wxl.retail-spellvisuals`.
- **The kit's audit stopped the install**: the Backport page names each piece it stopped on, with
  *Leave this piece out*.
- **The item SQL fails**: it's written for AzerothCore's world database.
- **Items are level 1 with no stats**: the conversion makes cosmetic copies; give them stats in
  **Stats** and Install again.
- **No 3D preview**: the preview needs WebGL 2; update your graphics driver.

## Building from source

Python 3.11 or newer (3.14 is what it's tested with):

```
git clone -b creatures https://github.com/Tyrallis/Retroport
cd Retroport
python -m pip install -e ".[dev]"
python -m pytest -q tests

python -m retroport.cli workbench                      # run it in a console (opens your browser)
python packaging/build_release.py --launcher-only      # or: Retroport Workbench.exe next to the code
python packaging/build_release.py                      # the release folder and zip, in dist\
```

A release bundles Python's official embeddable package, the dependencies and the code, and checks
that it starts before it's zipped.

The Workbench's code is `retroport/workbench/` (the page in `static/`), its game-file readers are
`wotlkconv/` (an unchanged copy of the Converter), and how it works is in
[docs/workbench-internals.md](docs/workbench-internals.md). The preview's physics is
`retroport/workbench/static/physics.wasm`, built from
[physics_wasm/](retroport/workbench/physics_wasm/README.md). The rest of `retroport/` is shared code
and older command-line tools ([docs/command-line-tools.md](docs/command-line-tools.md)).

## Credits

Retroport Workbench is a front end to other people's work:

- **[wow-retail-backport](https://github.com/Kirazul/wow-retail-backport)** by **Kirazul**: the kit
  that converts retail items for 3.3.5a, and the port of retail's physics engine the preview and
  Equip Plus run (used with permission).
- **[Equip Plus](https://github.com/TheDaveCalaz/wxl-equip-plus)** by **TheDaveCalaz**: the 3D armor
  pieces, the live physics in the client, and the tools that prepare them.
- **[wxl.modern-m2](https://github.com/Tyrallis/wxl.modern-m2)**, after **manatactical**'s work: retail
  models in the 3.3.5a client.
- **[WarcraftXL](https://github.com/WarcraftXL)**: the 64-bit client and the mod framework.
- **[kbtoy/Retroport](https://github.com/kbtoy/Retroport)**: the project this fork builds on.
- **[wotlkconv (Converter)](https://github.com/Bar3b0n3s/Converter)** by the Converter contributors:
  the readers for the game's files.
- **[wago.tools](https://wago.tools)** for the game data; **[Wowhead](https://www.wowhead.com)** for
  spell tooltips and creature abilities; **[wowdev](https://wowdev.wiki)** for WoWDBDefs, the
  community listfile and the file-format documentation;
  **[WoW Blender Studio](https://gitlab.com/skarnproject/blender-wow-studio)** by **Skarn** for the
  shader tables the 3D preview follows; **[Conjure](https://github.com/TheDaveCalaz/Conjure)** by
  **TheDaveCalaz** for code retroport adapts.

The kit and Equip Plus's tools are downloaded from their authors on first use and never bundled. The
full list, with every bundled library and its license, is
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT, see [LICENSE](LICENSE). A few files in this repository are under other terms;
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) says which (the preview's physics engine among them).

Retroport Workbench is a fan project, not affiliated with or endorsed by Blizzard Entertainment. It
ships no Blizzard art, models or game data: they're read at run time from wago.tools or your own
installs, for your own use. World of Warcraft and its assets are trademarks and copyright of
Blizzard Entertainment.
