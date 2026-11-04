"""MkDocs hook: ``llms.txt``, ``llms-full.txt`` and the agent skill on the site.

``llms.txt`` (https://llmstxt.org) is the site's index for language models:
one link per page, with what it holds. ``llms-full.txt`` is the whole
documentation as plain Markdown, with the API reference rendered from the
docstrings (the same source as the HTML reference), so an assistant reads
everything in one request. The agent skill, ``skills/egms-client/SKILL.md``,
is published as is.

All three are built from the sources on every build, so they never go stale.
A page in the nav without a description here fails the build.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SKILL = Path("skills/egms-client/SKILL.md")

SUMMARY = (
    "A small, typed, async Python client for the archive of EGMS, the Copernicus "
    "European Ground Motion Service: ground velocity across Europe from Sentinel-1 "
    "InSAR, in mm/year. It handles the CLMS service-key login, searches and downloads "
    "Ortho L3 tiles and L2A/L2B measurement points, and turns them into mosaics "
    "(Cloud-Optimized GeoTIFF), pandas/GeoParquet tables, xarray arrays and "
    "vertical/east-west maps."
)

NOTES = """\
- Install: `pip install egms-client` (extras: `raster`, `tables`, `xarray`). Python 3.12+.
- Credentials: a CLMS service key, read from `EGMS_SERVICE_KEY_FILE` or `EGMS_SERVICE_KEY`.
  Never put the key in code.
- The archive API is undocumented and fails quietly. Use `EgmsArchive.find` / `fetch` /
  `fetch_tile` instead of building URLs or file names: see "The traps we already fell into"
  in the guide and the rules in the agent skill.
- Units: mm/year; `U < 0` is the ground going down. L3 grids are in EPSG:3035."""

#: What each page of the nav holds, for llms.txt. API pages use their module docstring.
DESCRIPTIONS = {
    "index.md": "the guide: what EGMS is, quick start, recipes, the traps, API at a glance",
    "notebooks.md": "three worked examples on real data (Campi Flegrei, Ancona, Bologna)",
    "roadmap.md": "planned work: foundations, time-series analysis, AI features",
    "changelog.md": "what changed in each release",
    "contributing.md": "how to contribute",
    "api/errors.md": "EgmsError: the archive answered, but refused",
}

_INCLUDE = re.compile(r'^--8<-- "(?P<path>[^"]+)"\s*$', re.MULTILINE)
_API = re.compile(r"^::: (?P<module>[\w.]+)\s*$", re.MULTILINE)
_HTML_BLOCK = re.compile(r'^<p align="center">.*?^</p>\n', re.MULTILINE | re.DOTALL)
_ROLE = re.compile(r":(?:mod|func|class|meth|data|attr|exc):`~?([^`]+)`")


def on_post_build(config: Any, **_: Any) -> None:
    site = Path(config["site_dir"])
    url = config["site_url"].rstrip("/") + "/"
    pages = list(_pages(config["nav"]))
    (site / "llms.txt").write_text(llms_txt(config, url, pages), encoding="utf-8")
    (site / "llms-full.txt").write_text(llms_full(config, url, pages), encoding="utf-8")
    target = site / SKILL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / SKILL, target)


def llms_txt(config: Any, url: str, pages: list[tuple[str, str, str]]) -> str:
    sections: dict[str, list[str]] = {}
    for group, title, file in pages:
        link = f"- [{title}]({url}{_page_url(file)}): {_describe(config, file)}"
        sections.setdefault(group or "Docs", []).append(link)
    lines = [f"# {config['site_name']}", "", f"> {SUMMARY}", "", NOTES]
    for heading, links in sections.items():
        lines += ["", f"## {heading}", "", *links]
    lines += [
        "",
        "## For agents",
        "",
        f"- [Full documentation as text]({url}llms-full.txt): every page above, "
        "with the API reference rendered from the docstrings",
        f"- [Agent skill]({url}{SKILL.as_posix()}): how to use the library and the rules "
        "the archive enforces, for coding agents",
        "",
        "## Optional",
        "",
        f"- [Source code]({config['repo_url']}): the repository",
        "- [EGMS](https://egms.land.copernicus.eu/): the service and its Explorer",
        "",
    ]
    return "\n".join(lines)


def llms_full(config: Any, url: str, pages: list[tuple[str, str, str]]) -> str:
    parts = [f"# {config['site_name']}\n\n> {SUMMARY}\n\nSource: {url}\n"]
    for group, title, file in pages:
        if file == "changelog.md":
            continue  # long, and linked from llms.txt
        label = f"{group} / {title}" if group else title
        parts.append(f"\n\n<!-- page: {label} · {url}{_page_url(file)} -->\n\n")
        parts.append(_markdown(config, file))
    parts.append(f"\n\n<!-- agent skill · {url}{SKILL.as_posix()} -->\n\n")
    parts.append((ROOT / SKILL).read_text(encoding="utf-8"))
    return "".join(parts)


def _pages(nav: list[Any], group: str = "") -> Any:
    for item in nav:
        ((title, value),) = item.items()
        if isinstance(value, list):
            yield from _pages(value, title)
        else:
            yield group, title, value


def _page_url(file: str) -> str:
    return "" if file == "index.md" else file.removesuffix(".md") + "/"


def _source(config: Any, file: str) -> str:
    return (Path(config["docs_dir"]) / file).read_text(encoding="utf-8")


def _describe(config: Any, file: str) -> str:
    if file in DESCRIPTIONS:
        return DESCRIPTIONS[file]
    api = _API.search(_source(config, file))
    if api is None:
        raise ValueError(f"hooks/llms.py: no description for {file}, add it to DESCRIPTIONS")
    doc = _module(api["module"]).docstring
    if doc is None:
        raise ValueError(f"hooks/llms.py: {api['module']} has no docstring, describe {file}")
    return _plain(doc.value.split("\n", 1)[0].rstrip("."))


def _markdown(config: Any, file: str) -> str:
    text = _source(config, file)
    text = _INCLUDE.sub(lambda m: (ROOT / m["path"]).read_text(encoding="utf-8"), text)
    text = _API.sub(lambda m: api_markdown(m["module"]), text)
    return _HTML_BLOCK.sub("", text).strip() + "\n"


# The API reference, from the same docstrings mkdocstrings renders.


def _module(name: str) -> Any:
    import griffe

    return griffe.load(name, search_paths=[str(ROOT / "src")])


def api_markdown(name: str) -> str:
    module = _module(name)
    out = [f"## `{name}`", ""]
    if module.docstring:
        out += [_plain(module.docstring.value), ""]
    for member in _public(module):
        out += _member(member, level=3)
    return "\n".join(out)


def _plain(text: str) -> str:
    """Docstring markup as Markdown: Sphinx roles and ``double`` backticks as code."""
    return _ROLE.sub(r"`\1`", text).replace("``", "`")


def _public(obj: Any) -> list[Any]:
    return [
        m
        for n, m in obj.members.items()
        if not n.startswith("_") and not m.is_alias and (m.is_function or m.is_class or m.docstring)
    ]


def _member(member: Any, *, level: int, owner: str = "") -> list[str]:
    hashes = "#" * level
    name = f"{owner}.{member.name}" if owner else member.name
    if member.is_class:
        head = f"class {name}({_params(member)})"
    elif member.is_function:
        prefix = "async " if "async" in member.labels else ""
        returns = f" -> {member.returns}" if member.returns else ""
        head = f"{prefix}{name}({_params(member)}){returns}"
    else:
        annotation = f": {member.annotation}" if member.annotation else ""
        head = f"{name}{annotation}" + (f" = {member.value}" if member.value else "")
    out = [f"{hashes} `{head}`", ""]
    if member.docstring:
        out += [_plain(member.docstring.value), ""]
    if member.is_class:
        for sub in _public(member):
            if sub.is_function or sub.docstring:
                out += _member(sub, level=level + 1, owner=member.name)
    return out


def _params(obj: Any) -> str:
    import griffe

    params = [p for p in obj.parameters if p.name not in ("self", "cls")]
    text: list[str] = []
    star = False
    for p in params:
        if p.kind is griffe.ParameterKind.keyword_only and not star:
            text.append("*")
            star = True
        if p.kind is griffe.ParameterKind.var_positional:
            star = True
        item = {"var_positional": "*", "var_keyword": "**"}.get(p.kind.name, "") + p.name
        if p.annotation is not None:
            item += f": {p.annotation}"
        if p.default is not None:
            item += f" = {p.default}"
        text.append(item)
    return ", ".join(text)
