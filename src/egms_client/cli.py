"""``egms``: the archive from the command line.

    egms releases
    egms search   --bbox 14.4,40.0,15.7,41.0 --level L2B
    egms download --tile E47N19 --component U --keep tiff --out egms
    egms convert  egms/EGMS_L2b_124_0835_IW3_VV_2020_2025_1.csv

The key comes from ``--key-file``, else from ``EGMS_SERVICE_KEY`` or
``EGMS_SERVICE_KEY_FILE``. Downloads go to ``--out``, else to
``EGMS_DATA_DIR``, else to the user cache. A download larger than
``--max-gb`` (10 by default) stops before the first byte.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

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
        print(f"egms: {exc} (pip install 'egms-client[tables]')", file=sys.stderr)
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
        out = Path(args.out) if args.out else default_directory()

        def done(hit: Hit, paths: list[Path]) -> None:
            print(
                f"{hit.filename}: {', '.join(p.name for p in paths) or 'absent'}", file=sys.stderr
            )

        paths = await archive.fetch(
            query,
            out,
            keep=cast("list[Keep]", args.keep or ["zip"]),
            concurrency=args.concurrency,
            max_bytes=None if args.max_gb <= 0 else int(args.max_gb * 1e9),
            on_file=done,
        )
        print(f"{len(paths)} files in {out}", file=sys.stderr)
        return 0


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
        levels=tuple(cast("list[Level]", args.level or ["L3"])),
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
    for name, text in (("search", "list the files a query matches"), ("download", "fetch them")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--level", action="append", choices=LEVELS, help="repeatable; L3 if none")
        sub.add_argument("--release", help="e.g. 2020-2025 (default: the latest)")
        sub.add_argument("--bbox", help="west,south,east,north in degrees")
        sub.add_argument("--tile", help="L3 tile, e.g. E47N19")
        sub.add_argument("--component", choices=sorted(PRODUCT_TYPES), help="L3: U or E")
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
            sub.add_argument("--concurrency", type=int, default=4)
            sub.add_argument("--max-gb", type=float, default=10.0, help="0: no limit")
    convert = commands.add_parser("convert", help="CSV of the archive to GeoParquet (extra tables)")
    convert.add_argument("csv", nargs="+", help="CSV files; each .parquet is written next to it")
    convert.add_argument("--no-series", action="store_true", help="attributes only, no dates")
    return parser


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
