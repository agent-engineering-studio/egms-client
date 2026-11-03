"""``egms``: the archive from the command line.

    egms releases
    egms search   --bbox 14.4,40.0,15.7,41.0 --level L2B
    egms download --tile E47N19 --component U --keep tiff --out egms
    egms convert  egms/EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv
    egms mosaic   --bbox 13.9,40.7,14.6,41.0 --component U --out naples-U.tif

The key comes from ``--key-file``, else from ``EGMS_SERVICE_KEY`` or
``EGMS_SERVICE_KEY_FILE``. Downloads go to ``--out``, else to
``EGMS_DATA_DIR``, else to the user cache. A download larger than
``--max-gb`` (10 by default) stops before the first byte.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from egms_client.archive import LEVELS, PRODUCT_TYPES, Hit, Level, Query, parse_tile_id
from egms_client.auth import ServiceKey
from egms_client.client import EgmsArchive, Keep, default_directory
from egms_client.errors import EgmsError

if TYPE_CHECKING:
    import httpx


def main(argv: Sequence[str] | None = None, *, client: httpx.AsyncClient | None = None) -> int:
    """Run the command line; the exit status."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "convert":
            return _convert(args)
        key = ServiceKey.from_file(args.key_file) if args.key_file else ServiceKey.from_env()
        return asyncio.run(_run(args, key, client))
    except (EgmsError, LookupError, ValueError, OSError) as exc:
        print(f"egms: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        extra = "raster" if args.command == "mosaic" else "tables"
        print(f"egms: {exc} (pip install 'egms-client[{extra}]')", file=sys.stderr)
        return 1


async def _run(args: argparse.Namespace, key: ServiceKey, client: httpx.AsyncClient | None) -> int:
    async with EgmsArchive(client, key) as archive:
        if args.command == "releases":
            print("\n".join(await archive.releases()))
            return 0
        if args.command == "levels":
            print("\n".join(await archive.levels()))
            return 0
        query = _query(args, args.release or (await archive.releases())[-1])
        if args.command == "search":
            hits = [h for s in await archive.find(query) for h in s.hits]
            for hit in hits:
                print(f"{hit.filename}\t{hit.level or '-'}\t{hit.filesize / 1e6:.0f} MB")
            total = sum(h.filesize for h in hits)
            print(f"{len(hits)} files, {total / 1e9:.2f} GB", file=sys.stderr)
            return 0
        if args.command == "mosaic":
            return await _mosaic(args, archive, query)
        out = Path(args.out) if args.out else default_directory()
        paths = await _fetch(args, archive, query, out, cast("list[Keep]", args.keep or ["zip"]))
        print(f"{len(paths)} files in {out}", file=sys.stderr)
        return 0


async def _fetch(
    args: argparse.Namespace, archive: EgmsArchive, query: Query, out: Path, keep: list[Keep]
) -> list[Path]:
    meter = _Meter(sys.stderr)
    paths = await archive.fetch(
        query,
        out,
        keep=keep,
        concurrency=args.concurrency,
        max_bytes=None if args.max_gb <= 0 else int(args.max_gb * 1e9),
        on_plan=meter.plan,
        on_progress=meter.progress,
        on_file=meter.file,
    )
    meter.close()
    return paths


async def _mosaic(args: argparse.Namespace, archive: EgmsArchive, query: Query) -> int:
    from egms_client.mosaic import lonlat_to_laea, mosaic, to_cog

    if query.bbox is None:
        raise ValueError("mosaic needs --bbox west,south,east,north in degrees")
    tiles = Path(args.data_dir) if args.data_dir else default_directory()
    tiffs = await _fetch(args, archive, query, tiles, ["tiff"])
    minx, miny, maxx, maxy = lonlat_to_laea(*query.bbox)
    m = await asyncio.to_thread(mosaic, tiffs, minx=minx, miny=miny, maxx=maxx, maxy=maxy)
    out = Path(args.out or f"egms-{args.component}-{query.release}.tif")
    to_cog(m, out)
    rows, cols = m.values.shape
    print(f"{out}: {cols} x {rows} pixels of 100 m from {len(tiffs)} tiles", file=sys.stderr)
    return 0


class _Meter:
    """Download progress on stderr: one updating line on a terminal, a line per file otherwise."""

    def __init__(self, stream: TextIO, clock: Any = time.monotonic) -> None:
        self._stream = stream
        self._clock = clock
        self._live = stream.isatty()
        self._received: dict[str, int] = {}
        self._files = self._done = self._total = 0
        self._shown = 0.0

    def plan(self, hits: list[Hit]) -> None:
        self._files = len(hits)
        self._total = sum(h.filesize for h in hits)
        if hits:
            print(f"{self._files} files, {self._total / 1e9:.2f} GB to download", file=self._stream)

    def progress(self, hit: Hit, received: int, _total: int) -> None:
        self._received[hit.filename] = received
        if self._live and self._clock() - self._shown >= 0.5:
            self._shown = self._clock()
            self._line()

    def file(self, hit: Hit, paths: list[Path]) -> None:
        self._done += 1
        self._received[hit.filename] = hit.filesize
        if self._live:
            self._line()
        else:
            names = ", ".join(p.name for p in paths) or "absent"
            print(f"[{self._done}/{self._files}] {hit.filename}: {names}", file=self._stream)

    def close(self) -> None:
        if self._live and self._files:
            self._line()
            print(file=self._stream)

    def _line(self) -> None:
        got = sum(self._received.values())
        share = got / self._total if self._total else 1.0
        text = f"{self._done}/{self._files} files, {got / 1e9:.2f}/{self._total / 1e9:.2f} GB"
        print(f"\r{text} ({share:.0%})", end="", file=self._stream, flush=True)


def _convert(args: argparse.Namespace) -> int:
    from egms_client.tables import csv_to_geoparquet

    for name in args.csv:
        path = csv_to_geoparquet(Path(name), series=not args.no_series)
        print(path, file=sys.stderr)
    return 0


def _query(args: argparse.Namespace, release: str) -> Query:
    bbox: Any = None
    if args.bbox:
        parts = [float(v) for v in args.bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("--bbox is west,south,east,north in degrees")
        bbox = tuple(parts)
    return Query(
        levels=tuple(cast("list[Level]", getattr(args, "level", None) or ["L3"])),
        release=release,
        bbox=bbox,
        tile=parse_tile_id(args.tile) if args.tile else None,
        relative_orbit=args.orbit,
        burst_cycle=args.burst_cycle,
        swath=args.swath,
        direction=args.direction,
        product_type=PRODUCT_TYPES[args.component] if args.component else None,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="egms", description="The EGMS archive (Copernicus).")
    parser.add_argument("--key-file", help="CLMS service key JSON (default: from environment)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("releases", help="list the published releases")
    commands.add_parser("levels", help="list the product levels")
    for name, text in (
        ("search", "list the files a query matches"),
        ("download", "fetch them"),
        ("mosaic", "L3 over a box in degrees, as a Cloud-Optimized GeoTIFF (extra raster)"),
    ):
        sub = commands.add_parser(name, help=text)
        if name != "mosaic":
            sub.add_argument(
                "--level", action="append", choices=LEVELS, help="repeatable; L3 if none"
            )
        sub.add_argument("--release", help="e.g. 2020-2025 (default: the latest)")
        sub.add_argument("--bbox", help="west,south,east,north in degrees")
        sub.add_argument("--tile", help="L3 tile, e.g. E47N19")
        sub.add_argument(
            "--component",
            choices=sorted(PRODUCT_TYPES),
            default="U" if name == "mosaic" else None,
            help="L3: U (vertical) or E (east-west)",
        )
        sub.add_argument("--orbit", help="L2: relative orbit, e.g. 117")
        sub.add_argument("--burst-cycle", help="L2: burst cycle, e.g. 0222")
        sub.add_argument("--swath", choices=["IW1", "IW2", "IW3"], help="L2: sub-swath")
        sub.add_argument("--direction", choices=["ascending", "descending"])
        if name == "download":
            sub.add_argument("--out", help="directory (default: EGMS_DATA_DIR or user cache)")
            sub.add_argument(
                "--keep",
                action="append",
                choices=["zip", "tiff", "csv", "xml", "parquet"],
                help="repeatable; zip if none",
            )
        if name == "mosaic":
            sub.add_argument(
                "--out", help="the .tif to write (default: egms-<component>-<release>.tif)"
            )
            sub.add_argument("--data-dir", help="tile cache (default: EGMS_DATA_DIR or user cache)")
        if name != "search":
            sub.add_argument("--concurrency", type=int, default=4)
            sub.add_argument("--max-gb", type=float, default=10.0, help="0: no limit")
    convert = commands.add_parser("convert", help="CSV of the archive to GeoParquet (extra tables)")
    convert.add_argument("csv", nargs="+", help="CSV files; each .parquet is written next to it")
    convert.add_argument("--no-series", action="store_true", help="attributes only, no dates")
    return parser


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
