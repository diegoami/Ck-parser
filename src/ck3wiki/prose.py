"""Narrative prose for chronicle pages, written from each page's own facts.

    python -m ck3wiki.prose saves --out prose                        # template, no model
    python -m ck3wiki.prose saves --out prose --backend openai \\
        --url http://localhost:11434/v1 --model qwen3:14b              # any local server

The wiki is factual; this adds a paragraph on top of the record, never in place
of it. Three rules keep the paragraph honest:

* A model sees a **fact sheet**, the same facts the page shows and nothing
  else, and is told to use nothing else. A save has no motives, battles or
  personalities in it, so neither may the prose.
* Prose is stored with a **digest of the facts it was written from**. The build
  shows it only while the page still has exactly those facts: a new save that
  changes a ruler's page makes the old paragraph stale, and a stale paragraph is
  left out rather than allowed to contradict the table under it.
* Every number the prose uses must be in the fact sheet. A year the save never
  mentioned is the commonest invention, and the cheapest one to catch.

The model is not chosen yet (docs/PLAN.md Phase 7), so backends are pluggable:
``template`` writes deterministic sentences with no model at all, and
``openai`` speaks the OpenAI-compatible chat protocol over plain HTTP, which
Ollama, llama.cpp's server, LM Studio and vLLM all serve. No SDK is imported.

Prose is laid out like the portraits: one file per page under
``<out>/<chronicle>/<characters|titles>/<id>.json``, generated where a model
runs, folded in by ``ck3wiki.build --prose <out>``. Its published home is meant
to be ck_wiki, beside ``images/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .model import Wiki, WikiTitle
from .render import TIER_WORD

#: Bump when the prompt changes: existing prose is then regenerated, not reused.
PROMPT_VERSION = "ck3-prose/1"
SCHEMA = "ck3-prose/1"
KINDS = ("characters", "titles")

SYSTEM = """You write short encyclopedia entries for a chronicle of a Crusader Kings III \
playthrough. You are given a JSON fact sheet. Write one to three paragraphs of plain, \
neutral prose in the style of an encyclopedia.

Rules:
- Use only the facts given. Do not invent events, motives, wars, personalities or \
relationships. If the facts are thin, write less.
- Keep every date exactly as it appears; game dates are written year.month.day.
- A value written as "A – B" or "by A" is a window, not a date: say the change \
happened between A and B, or by A. Never pick a date inside it.
- Names are given as they should appear. Do not translate or correct them.
- No headings, no lists, no markdown. Output only the entry."""


# ---------------------------------------------------------------- facts


def _tidy(reason: str | None) -> str | None:
    return reason.replace("death_", "").replace("_", " ") if reason else None


def _person(wiki: Wiki, cid: int) -> dict:
    person = wiki.person(cid)
    return {
        "name": wiki.named(cid),
        "born": getattr(person, "birth", None),
        "died": getattr(person, "death", None),
    }


def _liege_name(wiki: Wiki, key: str | None) -> str:
    if key is None:
        return "independent"
    title = wiki.titles.get(key)
    return title.name if title else key


def _tier(tier: str | None) -> str | None:
    return TIER_WORD.get(tier or "", tier)


def _neighbours(title: WikiTitle, index: int, wiki: Wiki) -> tuple[str | None, str | None]:
    before = title.tenures[index - 1].holder if index > 0 else None
    after = title.tenures[index + 1].holder if index + 1 < len(title.tenures) else None
    return (
        wiki.named(before) if before is not None else None,
        wiki.named(after) if after is not None else None,
    )


def character_facts(wiki: Wiki, cid: int) -> dict:
    """Everything a character page states, as data. The prose may use this and no more."""
    character = wiki.characters[cid]
    house = wiki.houses.get(character.house) if character.house is not None else None
    culture = wiki.cultures.get(character.culture) if character.culture is not None else None
    faith = wiki.faiths.get(character.faith) if character.faith is not None else None
    reigns = []
    for title, tenure in wiki.held_by(cid):
        # by identity: two tenures can be equal field for field (PLAN.md §5)
        at = next(i for i, t in enumerate(title.tenures) if t is tenure)
        predecessor, successor = _neighbours(title, at, wiki)
        reigns.append({
            "title": title.name,
            "tier": _tier(title.tier),
            "from": tenure.start,
            "to": None if tenure.open else tenure.end,
            "still_holds": tenure.open,
            "how": _tidy(tenure.reason),
            "predecessor": predecessor,
            "successor": None if tenure.open else successor,
        })
    return {
        "page": "character",
        "id": cid,
        "name": character.name or f"Character {cid}",
        "sex": "female" if character.female else "male",
        "born": character.birth,
        "died": character.death,
        "cause_of_death": _tidy(character.death_reason),
        "house": house.name if house else None,
        "dynasty": house.dynasty.display_name if house and house.dynasty else None,
        "culture": culture.display_name if culture else None,
        "faith": faith.display_name if faith else None,
        "titles_held": reigns,
        "titles_held_elsewhere": [
            {"title": h.name, "tier": _tier(h.tier), "in_saves": h.seen}
            for h in wiki.held_elsewhere(cid)
        ],
        "parents": [_person(wiki, p) for p in character.parents],
        "spouses": [_person(wiki, p) for p in character.spouses],
        "former_spouses": [_person(wiki, p) for p in character.former_spouses],
        "children": [_person(wiki, p) for p in character.children],
        "siblings": [_person(wiki, p) for p in character.siblings],
        # counts are facts too: stated here, a paragraph may use them and the
        # number check accepts them, rather than either counting for itself
        "number_of_children": len(character.children),
        "number_of_siblings": len(character.siblings),
        "chronicle_saves": list(wiki.snapshots),
    }


def title_facts(wiki: Wiki, key: str) -> dict:
    """Everything a title page states, as data: its succession and its lieges."""
    title = wiki.titles[key]
    return {
        "page": "title",
        "key": key,
        "name": title.name,
        "tier": _tier(title.tier),
        "de_jure_liege": _liege_name(wiki, title.de_jure_liege) if title.de_jure_liege else None,
        "rulers_recorded": len(title.tenures),
        "succession": [
            {
                "ruler": wiki.named(t.holder),
                "from": t.start,
                "to": None if t.open else t.end,
                "current": t.open,
                "how": _tidy(t.reason),
            }
            for t in title.tenures
        ],
        # a save has no vassalage history: these are windows, never dates
        "lieges": [
            {"liege": _liege_name(wiki, s.liege), "began": s.began, "ended": s.ended or None}
            for s in title.vassalage(wiki.snapshots)
        ],
        "chronicle_saves": list(wiki.snapshots),
    }


def page_facts(wiki: Wiki, kind: str, ident: str) -> dict | None:
    """The fact sheet for one page, or None when this wiki has no such page."""
    if kind == "characters":
        cid = int(ident)
        return character_facts(wiki, cid) if cid in wiki.characters else None
    if kind == "titles":
        return title_facts(wiki, ident) if ident in wiki.titles else None
    raise ValueError(f"no such kind of page: {kind!r}")


def facts_digest(facts: dict) -> str:
    """Stable across runs and machines: canonical JSON, then sha256."""
    canonical = json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def rulers(wiki: Wiki) -> list[tuple[str, str]]:
    """The subject title's page and each of its rulers', in order of reign."""
    root = wiki.root
    if root is None:
        return []
    pages = [("titles", root.key)]
    for tenure in root.tenures:
        page = ("characters", str(tenure.holder))
        if tenure.holder in wiki.characters and page not in pages:
            pages.append(page)
    return pages


# ---------------------------------------------------------------- checks

_NUMBER = re.compile(r"\d+")


def check(text: str, facts: dict) -> list[str]:
    """What is wrong with this prose, as far as can be told without a reader.

    Only numbers are checked: every one in the text must occur somewhere in the
    fact sheet, as a whole number or as part of a date. That catches the
    invented year and the miscounted children, not the invented battle, which
    is why the prompt forbids events and the page says where the prose came from.
    """
    problems = []
    if not text.strip():
        problems.append("empty")
    known = set(_NUMBER.findall(json.dumps(facts, ensure_ascii=False)))
    invented = sorted({n for n in _NUMBER.findall(text) if n not in known}, key=int)
    if invented:
        problems.append("numbers not in the facts: " + ", ".join(invented))
    return problems


# ---------------------------------------------------------------- backends


class Backend(Protocol):
    name: str

    def write(self, facts: dict, system: str, user: str) -> str: ...


class TemplateBackend:
    """No model: fixed sentences from the facts. For tests, and for the pipeline itself."""

    name = "template"

    def write(self, facts: dict, system: str, user: str) -> str:
        if facts["page"] == "title":
            return _template_title(facts)
        return _template_character(facts)


def _template_character(f: dict) -> str:
    name = f["name"]
    life = f"born {f['born']}" if f["born"] else ""
    if f["died"]:
        life += f"{', ' if life else ''}died {f['died']}"
        if f["cause_of_death"]:
            life += f" of {f['cause_of_death']}"
    first = name + (f" ({life})" if life else "")
    house = f" of the house of {f['house']}" if f["house"] else ""
    sentences = [f"{first} was a member{house}." if house else f"{first} appears in this chronicle."]
    for reign in f["titles_held"]:
        span = f"from {reign['from'] or 'an unrecorded date'}"
        span += " and still held it when last seen" if reign["still_holds"] else f" to {reign['to'] or 'an unrecorded date'}"
        after = f", succeeding {reign['predecessor']}" if reign["predecessor"] else ""
        sentences.append(f"{name} held the {(reign['tier'] or 'title').lower()} of {reign['title']} {span}{after}.")
    n = f["number_of_children"]
    if n:
        sentences.append(f"{name} had {n} recorded child{'ren' if n != 1 else ''}.")
    return " ".join(sentences)


def _template_title(f: dict) -> str:
    rulers = [s["ruler"] for s in f["succession"]]
    n = f["rulers_recorded"]
    text = f"The {(f['tier'] or 'title').lower()} of {f['name']} records {n} holder{'s' if n != 1 else ''}."
    if rulers:
        text += f" The first recorded was {rulers[0]}, the last {rulers[-1]}."
    return text


class OpenAICompatible:
    """Any server speaking ``POST {url}/chat/completions``, over plain HTTP.

    Ollama serves it at ``http://localhost:11434/v1``, llama.cpp's server and LM
    Studio at their own ports. A reasoning model's ``<think>`` block is dropped:
    it is the model's scratch work, not the entry.
    """

    def __init__(self, url: str, model: str, api_key: str | None = None, timeout: float = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.name = f"openai:{model}"

    def write(self, facts: dict, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.3,
            "stream": False,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.url}/chat/completions", body, headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            reply = json.load(response)
        text = reply["choices"][0]["message"]["content"] or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def prompt(facts: dict) -> tuple[str, str]:
    user = "Fact sheet:\n" + json.dumps(facts, ensure_ascii=False, indent=1)
    return SYSTEM, user


# ---------------------------------------------------------------- storage


@dataclass
class Prose:
    text: str
    facts: str  #: digest of the fact sheet it was written from
    backend: str
    prompt: str = PROMPT_VERSION


def prose_path(root: Path, slug: str, kind: str, ident: str) -> Path:
    """Derived, never assigned: the chronicle, the page's folder, the page's id."""
    return root / slug / kind / f"{ident}.json"


def read_prose(path: Path) -> Prose | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            return None
        return Prose(text=data["text"], facts=data["facts"], backend=data["backend"], prompt=data["prompt"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_prose(path: Path, prose: Prose) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": SCHEMA, "facts": prose.facts, "backend": prose.backend,
            "prompt": prose.prompt, "text": prose.text}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_prose(root: Path | None, slug: str, wiki: Wiki) -> tuple[dict[tuple[str, str], Prose], int]:
    """The prose still true of this wiki's pages, and how many files were stale.

    Stale means written from facts the page no longer has; it is left out, not
    shown with a warning, because the table under it would contradict it.
    """
    found: dict[tuple[str, str], Prose] = {}
    stale = 0
    if root is None:
        return found, stale
    for kind in KINDS:
        folder = root / slug / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            prose = read_prose(path)
            facts = page_facts(wiki, kind, path.stem) if prose else None
            if prose is None or facts is None or prose.facts != facts_digest(facts):
                stale += 1
                continue
            found[(kind, path.stem)] = prose
    return found, stale


# ---------------------------------------------------------------- generation


def generate(
    wiki: Wiki, slug: str, pages: list[tuple[str, str]], backend: Backend, root: Path,
    force: bool = False, log=None,
) -> dict[str, int]:
    """Write prose for these pages. Current prose is kept unless `force`."""
    log = sys.stderr if log is None else log
    counts = {"written": 0, "kept": 0, "rejected": 0, "missing": 0}
    for kind, ident in pages:
        facts = page_facts(wiki, kind, ident)
        if facts is None:
            counts["missing"] += 1
            continue
        digest = facts_digest(facts)
        path = prose_path(root, slug, kind, ident)
        existing = read_prose(path)
        if (not force and existing and existing.facts == digest
                and existing.prompt == PROMPT_VERSION and existing.backend == backend.name):
            counts["kept"] += 1
            continue
        system, user = prompt(facts)
        text = backend.write(facts, system, user)
        problems = check(text, facts)
        if problems:
            # reported, never saved: a page without prose is better than one
            # whose prose says what the save does not
            print(f"  rejected {kind}/{ident}: {'; '.join(problems)}", file=log)
            counts["rejected"] += 1
            continue
        write_prose(path, Prose(text=text, facts=digest, backend=backend.name))
        counts["written"] += 1
    return counts


def make_backend(name: str, url: str, model: str | None, api_key: str | None) -> Backend:
    if name == "template":
        return TemplateBackend()
    if not model:
        raise ValueError("--model is required with --backend openai")
    return OpenAICompatible(url, model, api_key)


def main(argv: list[str] | None = None) -> int:
    import os

    from .build import discover, load_run, subject_of

    ap = argparse.ArgumentParser(prog="python -m ck3wiki.prose", description=__doc__.splitlines()[0])
    ap.add_argument("save", help="a .ck3 file, or a directory of saves")
    ap.add_argument("--out", default="prose", help="prose directory (default: ./prose)")
    ap.add_argument("--run", dest="run_id", help="only this run (its id or slug)")
    ap.add_argument("--title", help="subject title (default: each run's own, as the build does)")
    ap.add_argument("--character", action="append", default=[], metavar="ID",
                    help="write this character's page instead of the rulers'; repeatable")
    ap.add_argument("--backend", choices=("template", "openai"), default="template")
    ap.add_argument("--url", default="http://localhost:11434/v1",
                    help="OpenAI-compatible base URL (default: Ollama's)")
    ap.add_argument("--model", help="model name, as the server knows it")
    ap.add_argument("--force", action="store_true", help="rewrite prose that is still current")
    ap.add_argument("--cache", default=".ck3cache", help="character digests, as for the build")
    args = ap.parse_args(argv)

    try:
        backend = make_backend(args.backend, args.url, args.model, os.environ.get("CK3_PROSE_API_KEY"))
        runs = discover(args.save, args.run_id)
    except (ValueError, FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2
    log = sys.stderr
    status = 0
    for run in runs:
        subject = subject_of(run, args.title, log)
        if subject is None:
            continue
        wiki = load_run(run, subject, log=log, cache_dir=Path(args.cache))
        if wiki is None:
            continue
        pages = [("characters", c) for c in args.character] or rulers(wiki)
        counts = generate(wiki, run.slug, pages, backend, Path(args.out), args.force, log)
        print(f"  {run.slug}: " + ", ".join(f"{n} {k}" for k, n in counts.items()), file=log)
        if counts["rejected"] or counts["missing"]:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
