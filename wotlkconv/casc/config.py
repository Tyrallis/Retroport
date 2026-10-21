"""``.build.info`` and the build/CDN config files.

A CASC install bootstraps like this::

    .build.info          -> the active build's config hash
    Data/config/xx/yy/…  -> build config: hashes of the root and encoding files
    Data/data/*.idx      -> where an EKey lives inside data.NNN
    Data/data/data.NNN   -> the bytes

``.build.info`` is a ``|``-separated table whose header row carries typed
column names (``Build Key!HEX:16``); the build config is plain
``key = value`` lines where a value may be several space-separated hashes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from ..errors import MalformedFileError, MissingDependencyError


def parse_build_info(text: str) -> list[dict[str, str]]:
    """Parse ``.build.info`` into one dict per row, keyed by column name."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise MalformedFileError(".build.info is empty")
    # Column names carry a type suffix: "Build Key!HEX:16" -> "Build Key".
    columns = [c.split("!", 1)[0].strip() for c in lines[0].split("|")]
    rows = []
    for line in lines[1:]:
        values = line.split("|")
        if len(values) < len(columns):
            values += [""] * (len(columns) - len(values))
        rows.append(dict(zip(columns, values)))
    return rows


def parse_config(text: str) -> dict[str, list[str]]:
    """Parse a build or CDN config into ``key -> [values]``."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.split()
    return out


def config_path(data_dir: Path, key: str) -> Path:
    """Config files are filed under two levels of hash prefix."""
    return data_dir / "config" / key[0:2] / key[2:4] / key


@dataclasses.dataclass(slots=True)
class BuildInfo:
    """What the installation says about the build currently checked out."""

    product: str = ""
    branch: str = ""
    version: str = ""
    build_key: str = ""
    cdn_key: str = ""
    root_ckey: str = ""
    encoding_ckey: str = ""
    encoding_ekey: str = ""
    install_ckey: str = ""
    build_name: str = ""
    #: Where the install downloads from, for files it does not store.
    cdn_hosts: list[str] = dataclasses.field(default_factory=list)
    cdn_path: str = ""

    @classmethod
    def load(cls, install_dir: Path, product: str | None = None) -> BuildInfo:
        """Read ``.build.info`` and the build config it points at."""
        info_path = install_dir / ".build.info"
        if not info_path.is_file():
            found = cls.from_configs(install_dir)
            if found is not None:
                return found
            raise MissingDependencyError(
                f"{install_dir} does not look like a game install: no "
                f".build.info and no build config under Data/config. Point "
                f"--casc at the folder containing the game executable and its "
                f"Data directory"
            )
        rows = parse_build_info(info_path.read_text(encoding="utf-8",
                                                    errors="replace"))
        chosen = None
        for row in rows:
            if product and row.get("Product", "") != product:
                continue
            if row.get("Active", "1") == "1":
                chosen = row
                break
        if chosen is None:
            if product:
                available = sorted({r.get("Product", "?") for r in rows})
                raise MissingDependencyError(
                    f"no active build for product {product!r}; this install has "
                    f"{', '.join(available)}")
            chosen = rows[0]

        info = cls(
            product=chosen.get("Product", ""),
            branch=chosen.get("Branch", ""),
            version=chosen.get("Version", ""),
            build_key=chosen.get("Build Key", ""),
            cdn_key=chosen.get("CDN Key", ""),
            cdn_hosts=chosen.get("CDN Hosts", "").split(),
            cdn_path=chosen.get("CDN Path", ""),
        )

        data_dir = install_dir / "Data"
        cfg_path = config_path(data_dir, info.build_key)
        if not cfg_path.is_file():
            raise MissingDependencyError(
                f"build config {info.build_key} is missing from {cfg_path}; "
                f"the install may be mid-update or partially repaired")
        cfg = parse_config(cfg_path.read_text(encoding="utf-8", errors="replace"))
        return info._fill(cfg)

    @classmethod
    def from_configs(cls, install_dir: Path) -> BuildInfo | None:
        """An install without ``.build.info`` (a repacked client: Wow.exe and Data alone): its
        build config is the file under ``Data/config`` naming a root and an encoding file (the
        newest, if several), its CDN config the one naming archives."""
        root = install_dir / "Data" / "config"
        if not root.is_dir():
            return None
        builds, cdns = [], []
        for path in root.glob("*/*/*"):
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            try:
                cfg = parse_config(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if cfg.get("root") and cfg.get("encoding"):
                builds.append((path.stat().st_mtime, path.name, cfg))
            elif cfg.get("archives"):
                cdns.append((path.stat().st_mtime, path.name))
        if not builds:
            return None
        _t, key, cfg = max(builds)
        name = " ".join(cfg.get("build-name", []))
        version = ""
        import re
        m = re.search(r"WOW-(\d+)patch(\d+(?:\.\d+)*)", name)
        if m:
            version = f"{m.group(2)}.{m.group(1)}"
        product = (cfg.get("build-product") or ["wow"])[0].lower()
        info = cls(product=product, version=version, build_key=key, cdn_key=max(cdns)[1] if cdns else "")
        return info._fill(cfg)

    def _fill(self, cfg: dict[str, list[str]]) -> BuildInfo:
        """The root, encoding and install files a build config names."""
        info = self
        root = cfg.get("root", [])
        encoding = cfg.get("encoding", [])
        install = cfg.get("install", [])
        info.root_ckey = root[0] if root else ""
        info.encoding_ckey = encoding[0] if encoding else ""
        # The encoding file is the one thing referenced by EKey as well, because
        # you need it before you can translate CKeys into EKeys.
        info.encoding_ekey = encoding[1] if len(encoding) > 1 else ""
        info.install_ckey = install[0] if install else ""
        info.build_name = " ".join(cfg.get("build-name", []))
        if not info.root_ckey or not info.encoding_ekey:
            raise MalformedFileError(
                f"build config {info.build_key} lists no root or encoding file")
        return info

    def describe(self) -> str:
        return (f"{self.product or 'wow'} {self.version or '?'} "
                f"({self.build_name or self.build_key[:8]})")
