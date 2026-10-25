# physics.wasm

The preview's retail physics (hair, cloth, wings, chains, plumes). `static/physics.wasm` is built from
`physics_wasm.cpp` and Equip Plus's copy of the physics engine, `physics_domino.h/.cpp`
(`D:\Server\WXL\mods\wxl.equip-plus\src\physics`).

The engine is **Kirazul's port of the retail client's engine** (from
[Kirazul/wow-retail-backport](https://github.com/Kirazul/wow-retail-backport)), shipped in Equip Plus with
the author's permission. It is not covered by the workbench's licence; the copyright position of the
original engine is Blizzard's. Keep it out of anything published without checking that first.

Build (only when the engine changes), with Zig's bundled clang:

    python build.py <zig.exe> <folder with physics_domino.h/.cpp>

`shim/xmmintrin.h` stands in for the two SSE estimates the engine uses (rsqrtss, rcpss) with exact
values: WebAssembly has no SSE.
