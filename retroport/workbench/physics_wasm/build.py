"""Builds ../static/physics.wasm from physics_wasm.cpp and Equip Plus's copy of the engine.

    python build.py <zig.exe> <folder holding physics_domino.h/.cpp>

Zig's bundled clang targets wasm32-wasi; the module is a reactor (no main) and imports only the few
WASI calls libc++ keeps, which the page stubs. Only needed when the engine changes.
"""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
zig, engine = sys.argv[1], sys.argv[2]
out = os.path.join(here, "..", "static", "physics.wasm")
cmd = [zig, "c++", "-target", "wasm32-wasi", "-O2", "-s", "-w", "-std=c++17", "-fno-exceptions",
       "-mexec-model=reactor", "-I", os.path.join(here, "shim"), "-I", engine,
       os.path.join(here, "physics_wasm.cpp"), os.path.join(engine, "physics_domino.cpp"),
       "-o", out]
print(" ".join(cmd))
subprocess.run(cmd, check=True)
print(out, os.path.getsize(out), "bytes")
