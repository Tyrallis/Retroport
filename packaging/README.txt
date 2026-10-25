Retroport Workbench
===================

Bring retail World of Warcraft to your 3.3.5a (WotLK 12340) client and your AzerothCore server:
items and transmog sets, creatures, mounts and spells, each seen in 3D first and installed in one
click.


Start
-----
1. Unpack this whole folder anywhere. Keep runtime\ and app\ next to the .exe.
2. Run "Retroport Workbench.exe". It opens in a window of its own; closing the window closes it.
   (Windows may say the program is from an unknown publisher - it isn't code-signed. Choose
   "More info", then "Run anyway".)
3. The first time, Settings opens: choose your 3.3.5a client folder (the one with Wow.exe).
   Optionally your server's dbc folder too, so Install adds the new items there as well.
4. Items: pick items and sets (+), look them over in the Basket, give them stats in Stats, then
   Backport > Install.
   Creatures, Mounts: add them to the page's basket, then Install creatures / Install mounts.
   Spells: open a spell, Make a new spell (a retail look on a 3.3.5 template spell), then
   Install new spells, and .learn <id> in game.


What it needs
-------------
- Windows 10 or 11. Its window is Microsoft Edge's app mode (Edge comes with Windows).
- The internet. Retail's items, models and textures come from wago.tools, and the first Install
  downloads the retail backport kit and Equip Plus's tools from their authors' GitHub pages (always
  these copies, at the versions this release is tested with):
    https://github.com/Kirazul/wow-retail-backport
    https://github.com/TheDaveCalaz/wxl-equip-plus
  If wago.tools is down, Settings can read your own retail install instead.
- Items: any 3.3.5a client. The extra 3D pieces (skirts, boot shells, belt buckles, 3D capes) need
  WarcraftXL and Equip Plus in your client; Install adds them only when your client has it.
- Creatures, mounts and spells: the 64-bit WarcraftXL client (https://github.com/Tyrallis/client,
  branch x64-port) with these mods in its Mods folder:
    wxl.modern-m2            retail models (required)
    wxl.equip-plus           live retail physics for items, creatures, mounts and spell models (F9)
    wxl.retail-spellvisuals  retail spell visuals and body glows
  Each is on https://github.com/Tyrallis/<mod name>/releases.
- An AzerothCore server for creatures, mounts and spells (Settings: its dbc folder).


Where it keeps things
---------------------
  %USERPROFILE%\.retroport\workbench.json     your settings
  %USERPROFILE%\.retroport\workbench\         its cache, your baskets and spell ports, the kit's project, its log

Install backs up everything it replaces in your client and server first; Undo puts it back.
The item install shows its SQL for you to apply; the creature and mount installs can run theirs
on the world database named in worldserver.conf.


Not affiliated with or endorsed by Blizzard Entertainment. It ships no Blizzard assets: game data
is read at run time from wago.tools or your own game installs, for your own use. World of
Warcraft and its assets are trademarks and copyright of Blizzard Entertainment.
