"""Check a text against the facts it was written from: no number invented, swapped, or flipped.

The facts (:mod:`egms_client.facts`) hold every number of an answer. A text
for people, written by a template (:func:`words`) or by a language model,
should quote them and nothing else. Three checks, from the loosest:

* :func:`check_text`: every number of the text is a figure of the facts, to
  the decimals written (``145`` and ``145.2`` match 145.24; ``146`` does
  not). A percentage is read as a share (``76%`` matches 0.762).
* :func:`check_signs`: a number said to go down (*sinks by 4.0*, *scende di
  4,0*, ``-4.0``) is a negative figure of the facts, and one said to go up a
  positive one. The worst fault in ground motion is the sign: a model that
  reads -4.0 mm/year as "rises 4 mm a year" quotes a number that exists.
* :func:`check_claims`: in the sentences of :func:`words`, each number is the
  one of *its* fact. "The vertical velocity is -4.5" where the facts give
  -4.5 to the regional median is a swap that the first check cannot see.

Texts can be in English (``lang="en"``: ``1,234.5``) or Italian
(``lang="it"``: ``1.234,5``). Digits inside a word (``E47N19``, ``L3``) are
not numbers. Pure: no network, no model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

Lang = Literal["en", "it"]

_EN = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:st|nd|rd|th)?(?!\w)")
_IT = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?:°|ª|º)?(?!\w)")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")
#: A hyphen, a minus sign (U+2212) and an en dash, written before a number.
_MINUS = "-\u2212\u2013"


@dataclass(frozen=True, slots=True)
class Number:
    """A number as written: its text, its value, decimals, sign and percent."""

    text: str
    value: float
    decimals: int
    sign: int  # -1, +1 when written; 0 when not
    percent: bool
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Misquote:
    """A number of the text said of a fact that holds another value.

    ``said`` is the piece of text, ``key`` the fact (a dotted path into the
    facts, ``""`` when the sentence names none), ``fact`` what it holds there.
    """

    said: str
    key: str
    fact: Any

    def __str__(self) -> str:
        where = f"{self.key} is {self.fact}" if self.key else "no fact has that sign"
        return f"«{self.said}»: {where}"


def numbers(text: str, lang: Lang = "en") -> list[Number]:
    """The numbers of a text, in order (see the module for how they are read)."""
    plain = text.replace("**", "")
    pattern = _IT if lang == "it" else _EN
    out = []
    for m in pattern.finditer(plain):
        raw = m.group(1)
        digits = raw.replace(".", "").replace(",", ".") if lang == "it" else raw.replace(",", "")
        sign = 0
        start = m.start()
        if start and plain[start - 1] in _MINUS + "+":
            before = plain[start - 2] if start >= 2 else " "
            if not (before.isalnum() or before in "._/"):
                sign = 1 if plain[start - 1] == "+" else -1
                start -= 1
        after = plain[m.end() : m.end() + 2].lstrip(" ")
        out.append(
            Number(
                text=plain[start : m.end()],
                value=float(digits),
                decimals=len(digits.partition(".")[2]),
                sign=sign,
                percent=after.startswith("%"),
                start=start,
                end=m.end(),
            )
        )
    return out


def figures(facts: Any) -> Iterator[float]:
    """Every number of a tree of facts, with its sign: values, and the digits in strings."""
    if isinstance(facts, bool) or facts is None:
        return
    if isinstance(facts, int | float):
        if not math.isnan(facts):
            yield float(facts)
    elif isinstance(facts, str):
        yield from (float(d) for d in _DIGITS.findall(facts))
    elif isinstance(facts, dict):
        for key, item in facts.items():
            yield from figures(key)
            yield from figures(item)
    elif isinstance(facts, list | tuple):
        for item in facts:
            yield from figures(item)


def same(n: Number, fact: Any) -> bool:
    """Is ``fact`` the number ``n``, to the decimals written (sign aside)?"""
    if isinstance(fact, bool) or not isinstance(fact, int | float) or math.isnan(fact):
        return False
    value = abs(float(fact)) * (100 if n.percent else 1)
    return round(value, n.decimals) == n.value


def check_text(text: str, facts: Any, *, lang: Lang = "en", question: str = "") -> list[str]:
    """The numbers of ``text`` that no figure of ``facts`` gives (empty: all found).

    Numbers written in ``question`` are allowed: an answer may repeat them.
    """
    known = list(figures(facts))
    asked = {n.value for n in numbers(question, lang)}
    return [
        n.text
        for n in numbers(text, lang)
        if n.value not in asked and not any(same(n, f) for f in known)
    ]


_DOWN = {
    "en": r"(?:sinks?|sinking|sank|subsides?|subsiding|goes down|going down|went down|"
    r"lowers?|lowering|drops?|dropping|falls?|falling|moves? down|down by|west|westwards?)",
    "it": r"(?:scende|scendono|sprofonda|sprofondano|si abbassa|si abbassano|abbassamento|"
    r"cala|calano|subsidenza|in discesa|verso ovest)",
}
_UP = {
    "en": r"(?:rises?|rising|rose|goes up|going up|went up|uplift|lifts?|lifting|"
    r"moves? up|up by|heaves?|east|eastwards?)",
    "it": r"(?:sale|salgono|si solleva|si sollevano|sollevamento|si alza|si alzano|in salita|"
    r"verso est)",
}
_LINK = {
    "en": r"(?:\s+(?:by|of|at|about|around|some|nearly|almost))*\s+",
    "it": r"(?:\s+(?:di|a|circa|quasi|sui|intorno a|oltre))*\s+",
}


def directions(text: str, lang: Lang = "en") -> list[int]:
    """For each number of :func:`numbers`, the direction the text gives it.

    -1 when a minus sign is written before it or a word of descent comes
    right before it (*sinks by*, *goes down*, *scende di*, *si abbassa di*);
    +1 with ``+`` or a word of rise; 0 otherwise, and for percentages.
    """
    plain = text.replace("**", "")
    claims: dict[int, int] = {}
    for verbs, sign in ((_DOWN[lang], -1), (_UP[lang], 1)):
        for m in re.finditer(rf"\b{verbs}{_LINK[lang]}(?=\d)", plain, re.I):
            claims[m.end()] = sign
    return [0 if n.percent else n.sign or claims.get(n.start, 0) for n in numbers(text, lang)]


def check_signs(text: str, facts: Any, *, lang: Lang = "en") -> list[Misquote]:
    """Numbers said to go down that the facts hold only as rising, and the reverse.

    The direction of a number is :func:`directions`. It is a misquote when
    the facts hold that value (to the decimals written) only with the other
    sign. Numbers with no direction are not read.
    """
    plain = text.replace("**", "")
    signed = list(figures(_signed_only(facts)))
    out = []
    for n, claimed in zip(numbers(text, lang), directions(text, lang), strict=True):
        if not claimed:
            continue
        matching = [f for f in signed if same(n, f)]
        if matching and not any(f == 0 or (f > 0) == (claimed > 0) for f in matching):
            start = max(0, plain.rfind(" ", 0, max(0, n.start - 12)))
            out.append(Misquote(plain[start : n.end].strip(), "", matching[0]))
    return out


def _signed_only(facts: Any) -> Any:
    """The numeric values of the facts, with their signs: strings left out (dates, names)."""
    if isinstance(facts, dict):
        return [_signed_only(v) for v in facts.values()]
    if isinstance(facts, list | tuple):
        return [_signed_only(v) for v in facts]
    if isinstance(facts, int | float) and not isinstance(facts, bool):
        return facts
    return None


# The template: sentences that name their fact.


@dataclass(frozen=True, slots=True)
class Sentence:
    """A sentence of :func:`words`: its text in each language, with ``{key|fmt}`` holes."""

    en: str
    it: str
    when: Callable[[dict[str, Any]], bool] = lambda _: True


_HOLE = re.compile(r"\{(?P<key>[\w.]+)\|(?P<fmt>\w+)\}")

_VELOCITY = (
    Sentence(
        "At {lon|five}° E, {lat|five}° N the {component_words} velocity of the cell is "
        "{velocity_mm_per_year|signed} mm/year ({direction_words}).",
        "A {lon|five}° E, {lat|five}° N la velocità {component_words} della cella è "
        "{velocity_mm_per_year|signed} mm/anno ({direction_words}).",
        lambda f: f.get("measured") is True,
    ),
    Sentence(
        "At {lon|five}° E, {lat|five}° N there is no measurement: not measured, which is not zero.",
        "A {lon|five}° E, {lat|five}° N non c'è una misura: non misurato, che non vuol dire fermo.",
        lambda f: f.get("measured") is False,
    ),
    Sentence(
        "The median within {regional.radius_m|int} m is {regional.median_mm_per_year|signed} "
        "mm/year: against its surroundings the cell moves {regional.relative_mm_per_year|signed}"
        " mm/year.",
        "La mediana entro {regional.radius_m|int} m è {regional.median_mm_per_year|signed} "
        "mm/anno: rispetto ai dintorni la cella si muove di "
        "{regional.relative_mm_per_year|signed} mm/anno.",
        lambda f: f.get("measured") is True and f["regional"]["relative_mm_per_year"] is not None,
    ),
    Sentence(
        "How far to trust it: score {reliability.score|two}, reliable from "
        "{reliability.reliable_from|two} ({reliable_words}); "
        "{reliability.coverage|pct} of the cells within {reliability.radius_m|int} m have a "
        "value.",
        "Quanto fidarsi: punteggio {reliability.score|two}, affidabile da "
        "{reliability.reliable_from|two} ({reliable_words}); ha un valore il "
        "{reliability.coverage|pct} delle celle entro {reliability.radius_m|int} m.",
        lambda f: f.get("measured") is True,
    ),
)

_AREA = (
    Sentence(
        "In the box, {cells_with_data|int} cells have a value ({coverage|pct} of the box). "
        "The median {component_words} velocity is {median|signed} mm/year; from the 5th to "
        "the 95th percentile the cells go from {p5|signed} to {p95|signed} mm/year.",
        "Nel riquadro hanno un valore {cells_with_data|int} celle (il {coverage|pct} del "
        "riquadro). La velocità {component_words} mediana è {median|signed} mm/anno; dal 5° al "
        "95° percentile le celle vanno da {p5|signed} a {p95|signed} mm/anno.",
        lambda f: f.get("measured") is True,
    ),
    Sentence(
        "{share_below|pct} of the cells go down faster than {stable_band_mm_per_year|one} "
        "mm/year, {share_above|pct} go up faster than {stable_band_mm_per_year|one}.",
        "Vanno giù più di {stable_band_mm_per_year|one} mm/anno: {share_below|pct} delle "
        "celle; su più di {stable_band_mm_per_year|one}: {share_above|pct}.",
        lambda f: f.get("measured") is True,
    ),
    Sentence(
        "In the box there is no measurement: not measured, which is not zero.",
        "Nel riquadro non c'è nessuna misura: non misurato, che non vuol dire fermo.",
        lambda f: f.get("measured") is False,
    ),
)

_MOVING = (
    Sentence(
        "Against the median of the box ({reference_median_mm_per_year|signed} mm/year), "
        "{moving|int} cells move by {threshold_mm_per_year|one} mm/year or more; "
        "{moving_reliable|int} of them are in a well measured neighbourhood.",
        "Rispetto alla mediana del riquadro ({reference_median_mm_per_year|signed} mm/anno), "
        "{moving|int} celle si muovono di {threshold_mm_per_year|one} mm/anno o più; "
        "{moving_reliable|int} sono in un intorno ben misurato.",
        lambda f: f.get("measured") is True,
    ),
    Sentence(
        "The fastest is at {cells.0.lon|five}° E, {cells.0.lat|five}° N: "
        "{cells.0.velocity_mm_per_year|signed} mm/year.",
        "La più veloce è a {cells.0.lon|five}° E, {cells.0.lat|five}° N: "
        "{cells.0.velocity_mm_per_year|signed} mm/anno.",
        lambda f: bool(f.get("cells")),
    ),
    Sentence(
        "In the box there is no measurement: not measured, which is not zero.",
        "Nel riquadro non c'è nessuna misura: non misurato, che non vuol dire fermo.",
        lambda f: f.get("measured") is False,
    ),
)

_CLOSING = Sentence(
    "Data: EGMS release {release_words}, measured from {window.first|date} to "
    "{window.last|date}: they stop there, and do not describe the ground of today. A velocity "
    "is a measurement, not an alert.",
    "Dati: EGMS, release {release_words}, misurati dal {window.first|date} al "
    "{window.last|date}: si fermano lì e non descrivono il terreno di oggi. Una velocità è una "
    "misura, non un'allerta.",
    lambda f: f["window"]["exact"],
)
_CLOSING_YEARS = Sentence(
    "Data: EGMS release {release_words}; the exact dates of the window are not known. A "
    "velocity is a measurement, not an alert.",
    "Dati: EGMS, release {release_words}; le date esatte della finestra non sono note. Una "
    "velocità è una misura, non un'allerta.",
    lambda f: not f["window"]["exact"],
)

TEMPLATES: dict[str, tuple[Sentence, ...]] = {
    "velocity": (*_VELOCITY, _CLOSING, _CLOSING_YEARS),
    "area": (*_AREA, _CLOSING, _CLOSING_YEARS),
    "moving_points": (*_MOVING, _CLOSING, _CLOSING_YEARS),
}

_WORDS = {
    "component_words": {
        ("U", "en"): "vertical",
        ("E", "en"): "east-west",
        ("U", "it"): "verticale",
        ("E", "it"): "est-ovest",
    },
}


def at(facts: Any, key: str) -> Any:
    """The fact at a dotted path (list positions as numbers); ``None`` when there is none."""
    for part in key.split("."):
        if isinstance(facts, dict) and part in facts:
            facts = facts[part]
        elif isinstance(facts, list) and part.isdigit() and int(part) < len(facts):
            facts = facts[int(part)]
        else:
            return None
    return facts


def _format(value: Any, fmt: str, lang: Lang) -> str:
    if fmt == "date":
        return str(value)
    number = float(value)
    text = {
        "signed": f"{number:+.1f}" if round(number, 1) else "0.0",
        "one": f"{number:.1f}",
        "two": f"{number:.2f}",
        "five": f"{number:.5f}",
        "pct": f"{number * 100:.0f}%",
        "int": f"{number:,.0f}",
    }[fmt]
    if lang == "it":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
        text = text.replace("%", " %")
    return text


def _plain_words(facts: dict[str, Any], lang: Lang) -> dict[str, str]:
    component = facts.get("component", "U")
    v = facts.get("velocity_mm_per_year")
    if component == "U":
        direction = {1: ("up", "verso l'alto"), -1: ("down", "verso il basso")}
    else:
        direction = {1: ("east", "verso est"), -1: ("west", "verso ovest")}
    direction[0] = ("no motion at this precision", "nessun movimento a questa precisione")
    pick = 0 if lang == "en" else 1
    reliable = facts.get("reliability", {}).get("reliable")
    return {
        "component_words": _WORDS["component_words"][(component, lang)],
        "direction_words": "" if v is None else direction[(v > 0) - (v < 0)][pick],
        "reliable_words": ("reliable", "affidabile")[pick]
        if reliable
        else ("not reliable", "non affidabile")[pick],
        "release_words": str(facts.get("release", "")),
    }


def words(facts: dict[str, Any], lang: Lang = "en") -> str:
    """The answer in words, from a template: every number is one of the facts.

    :class:`ValueError` if the text would quote a number the facts do not
    hold (a bug of the template, never shipped): it is checked before it is
    returned.
    """
    plain = _plain_words(facts, lang)
    out = []
    for sentence in TEMPLATES[facts["answer"]]:
        if not sentence.when(facts):
            continue
        template = getattr(sentence, lang)
        text = _HOLE.sub(lambda m: _format(at(facts, m["key"]), m["fmt"], lang), template)
        out.append(re.sub(r"\{(\w+)\}", lambda m: plain[m[1]], text))
    text = " ".join(out)
    strangers = check_text(text, facts, lang=lang)
    if strangers:
        raise ValueError(f"the template quotes numbers not in the facts: {strangers}")
    return text


def check_claims(text: str, facts: dict[str, Any], *, lang: Lang = "en") -> list[Misquote]:
    """In the sentences of :func:`words`, the numbers that are not the one of their fact.

    A sentence written in other words is not read: a model that rephrases
    goes through :func:`check_text` and :func:`check_signs` only.
    """
    out = []
    for sentence in TEMPLATES.get(facts.get("answer", ""), ()):
        template = re.sub(r"\{(\w+)\}", lambda m: "\0" + m[1], getattr(sentence, lang))
        holes = list(_HOLE.finditer(template))
        pattern, last = "", 0
        for hole in holes:
            value = r"(\d{4}-\d\d-\d\d)" if hole["fmt"] == "date" else _VALUE
            pattern += _loose(template[last : hole.start()]) + value
            last = hole.end()
        pattern += _loose(template[last:].rstrip("."))
        for found in re.finditer(pattern, text.replace("**", "")):
            for token, hole in zip(found.groups(), holes, strict=True):
                fact = at(facts, hole["key"])
                if hole["fmt"] == "date":
                    if token.strip() != str(fact):
                        out.append(Misquote(found.group().strip(), hole["key"], fact))
                    continue
                if not _equal(token, fact, lang):
                    out.append(Misquote(found.group().strip(), hole["key"], fact))
    return out


_VALUE = r"([\u2212+\-]?[\d.,]*\d\s?%?)"


def _loose(piece: str) -> str:
    """A piece of template as a pattern: the words of a ``{name}`` match any words."""
    parts = re.split(r"\0\w+", piece)
    return r"[^.;:]*?".join(re.escape(p) for p in parts)


def _equal(token: str, fact: Any, lang: Lang) -> bool:
    if fact is None or isinstance(fact, bool):
        return False
    found = numbers(token.replace("\u2212", "-"), lang)
    if len(found) != 1:
        return False
    n = found[0]
    value = float(fact)
    if not same(n, value):
        return False
    return not (n.sign and value and (n.sign > 0) != (value > 0))


__all__ = [
    "TEMPLATES",
    "Misquote",
    "Number",
    "Sentence",
    "at",
    "check_claims",
    "check_signs",
    "check_text",
    "directions",
    "figures",
    "numbers",
    "same",
    "words",
]
