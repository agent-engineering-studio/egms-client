"""The agent skill names only things that exist, and its frontmatter is valid."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import egms_client
from egms_client import EgmsArchive, Hit

SKILL = Path(__file__).resolve().parent.parent / "skills" / "egms-client" / "SKILL.md"


def _skill() -> tuple[dict[str, str], str]:
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, "SKILL.md starts with a --- frontmatter block"
    fields = dict(line.split(": ", 1) for line in match[1].splitlines())
    return fields, match[2]


def test_frontmatter() -> None:
    fields, _ = _skill()
    assert fields["name"] == "egms-client"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    assert 0 < len(fields["description"]) <= 1024
    assert "<" not in fields["description"] and ">" not in fields["description"]


def test_imports_exist() -> None:
    _, body = _skill()
    imports = re.findall(r"from (egms_client[\w.]*) import ([\w, ]+)", body)
    assert imports
    for module_name, names in imports:
        module = importlib.import_module(module_name)
        for name in names.split(","):
            assert hasattr(module, name.strip()), f"{module_name}.{name.strip()}"


def test_qualified_names_exist() -> None:
    _, body = _skill()
    for dotted in re.findall(r"egms_client\.(\w+)\.(\w+)", body):
        module = importlib.import_module(f"egms_client.{dotted[0]}")
        assert hasattr(module, dotted[1]), ".".join(dotted)


def test_methods_exist() -> None:
    _, body = _skill()
    for name in set(re.findall(r"archive\.(\w+)\(", body)):
        assert hasattr(EgmsArchive, name), f"EgmsArchive.{name}"
    for name in set(re.findall(r"hit\.(\w+)", body)):
        assert name in Hit.__dataclass_fields__ or hasattr(Hit, name), f"Hit.{name}"


def test_constants_match() -> None:
    _, body = _skill()
    assert f"At most {egms_client.MAX_DOWNLOADS} downloads" in body
    side = f"{egms_client.MAX_BBOX_DEG:g}°"
    assert f"{side} \N{MULTIPLICATION SIGN} {side}" in body
    for level in egms_client.LEVELS:
        assert f'"{level}"' in body
