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
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .model import Gap, Wiki, WikiTitle
from .render import TIER_WORD

#: Bump when the prompt or the fact sheet changes: existing prose is then
#: regenerated, not reused.
PROMPT_VERSION = "ck3-prose/3"
SCHEMA = "ck3-prose/1"
KINDS = ("characters", "titles")

SYSTEM = """You write short encyclopedia entries for a chronicle of a Crusader Kings III \
playthrough. You are given a JSON fact sheet. Write one to three paragraphs of plain, \
neutral prose in the style of an encyclopedia.

Rules:
- Use only the facts given. Do not invent events, motives, wars, personalities, \
relationships or geography. Do not judge a reign. If the facts are thin, write less.
- Copy dates exactly as written. Where a fact says a change happened "between" two \
dates, say so; never pick a date inside it.
- "how_gained" says how a title was gained, never how it was lost. "passed_to" says \
who held a title next, not how or why: never say a title was granted or given.
- "next_holder_recorded_from" means nobody is recorded holding the title between \
"until" and that date. Say so; never name a successor for those years.
- A "no_holder_recorded" entry in a succession is such a stretch. Say nobody is \
recorded then; never bridge it.
- "held_when_title_last_seen" gives the last save that shows the title, and the person \
still held it then. It says nothing about later, and nothing about a death.
- "other_titles_this_person_held" are titles this same person held outside this \
chronicle.
- A de jure liege is only a legal claim; whether a realm was independent is what \
"lieges" says, and nothing else.
- Use each person's "sex" for pronouns and for words such as son or daughter. \
Use the counts given; do not count for yourself.
- Names are given as they should appear. Do not translate, correct or respell them.
- No headings, no lists, no markdown. Output only the entry."""

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


# ---------------------------------------------------------------- facts


def _date(value: str | None) -> str | None:
    """``"1284.3.6"`` -> ``"6 March 1284"``, written here so a model never converts one.

    The numbers stay the same, so the number check still holds a paragraph to
    them. Anything that is not a date is passed through untouched.
    """
    if not value:
        return None
    try:
        year, month, day = (int(x) for x in str(value).split("."))
        return f"{day} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return str(value)


def _age(birth: str | None, death: str | None) -> int | None:
    """Whole years between two save dates, as a fact rather than a sum left to the writer."""
    if not birth or not death:
        return None
    try:
        by, bm, bd = (int(x) for x in birth.split("."))
        dy, dm, dd = (int(x) for x in death.split("."))
    except ValueError:
        return None
    return dy - by - ((dm, dd) < (bm, bd))


def _tidy(reason: str | None) -> str | None:
    return reason.replace("death_", "").replace("_", " ") if reason else None


def _person(wiki: Wiki, cid: int) -> dict:
    person = wiki.person(cid)
    return {
        "name": wiki.named(cid),
        "sex": "female" if getattr(person, "female", False) else "male",
        "born": _date(getattr(person, "birth", None)),
        "died": _date(getattr(person, "death", None)),
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


def _liege_stretch(wiki: Wiki, stretch) -> dict:
    """A vassalage stretch in words, so a window cannot be mistaken for a date (§9)."""
    began = (f"between {_date(stretch.after)} and {_date(stretch.first)}" if stretch.after
             else f"already so at the first save, {_date(stretch.first)}")
    ended = (f"between {_date(stretch.last)} and {_date(stretch.before)}" if stretch.before
             else f"still so at the last save, {_date(stretch.last)}")
    return {"liege": _liege_name(wiki, stretch.liege), "began": began, "ended": ended}


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
        previous, following = _neighbours(title, at, wiki)
        reigns.append({
            "title": title.name,
            "tier": _tier(title.tier),
            "from": _date(tenure.start),
            "until": None if tenure.open else _date(tenure.end),
            # not "at the last save": a title can leave the lineage, and then
            # the last word on it is older than the chronicle's end
            "held_when_title_last_seen": _date(title.last_recorded) if tenure.open else None,
            "how_gained": _tidy(tenure.reason),
            "previous_holder": previous,
            "passed_to": None if tenure.open else following,
        })
        gap = wiki.gap_after(title, tenure)
        if gap is not None:
            reigns[-1]["next_holder_recorded_from"] = _date(gap.end)
    return {
        "page": "character",
        "id": cid,
        "name": character.name or f"Character {cid}",
        "sex": "female" if character.female else "male",
        "born": _date(character.birth),
        "died": _date(character.death),
        "died_aged": _age(character.birth, character.death),
        "cause_of_death": character.death_text or _tidy(character.death_reason),
        "house": house.name if house else None,
        "dynasty": house.dynasty.display_name if house and house.dynasty else None,
        "culture": culture.display_name if culture else None,
        "faith": faith.display_name if faith else None,
        "titles_held_in_this_chronicle": reigns,
        "other_titles_this_person_held": [
            {"title": h.name, "tier": _tier(h.tier), "held_in_saves": [_date(d) for d in h.seen]}
            for h in wiki.held_elsewhere(cid)
        ],
        "parents": [_person(wiki, p) for p in character.parents],
        "spouses": [_person(wiki, p) for p in character.spouses],
        "former_spouses": [_person(wiki, p) for p in character.former_spouses],
        "children": [_person(wiki, p) for p in character.children],
        "siblings": [_person(wiki, p) for p in character.siblings],
        # counts are facts too: stated here, a paragraph may use them and the
        # number check accepts them, rather than either counting for itself
        "number_of_marriages": len(character.spouses) + len(character.former_spouses),
        "number_of_children": len(character.children),
        "number_of_siblings": len(character.siblings),
        "chronicle_saves": [_date(d) for d in wiki.snapshots],
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
        # gaps included: a stretch nobody is recorded holding is a fact too,
        # and leaving it out invites a model to bridge it
        "succession": [
            {"no_holder_recorded": {"from": _date(t.start), "until": _date(t.end)}}
            if isinstance(t, Gap) else
            {
                "ruler": wiki.named(t.holder),
                "from": _date(t.start),
                "until": None if t.open else _date(t.end),
                "held_when_title_last_seen": _date(title.last_recorded) if t.open else None,
                "how_gained": _tidy(t.reason),
            }
            for t in wiki.succession(title)
        ],
        # a save has no vassalage history: these are windows, never dates
        "lieges": [_liege_stretch(wiki, s) for s in title.vassalage(wiki.snapshots)],
        "chronicle_saves": [_date(d) for d in wiki.snapshots],
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
    for reign in f["titles_held_in_this_chronicle"]:
        span = f"from {reign['from'] or 'an unrecorded date'}"
        span += (f" and still held it on {reign['held_when_title_last_seen']}"
                 if reign["held_when_title_last_seen"]
                 else f" until {reign['until'] or 'an unrecorded date'}")
        after = f", after {reign['previous_holder']}" if reign["previous_holder"] else ""
        sentences.append(f"{name} held the {(reign['tier'] or 'title').lower()} of {reign['title']} {span}{after}.")
    n = f["number_of_children"]
    if n:
        sentences.append(f"{name} had {n} recorded child{'ren' if n != 1 else ''}.")
    return " ".join(sentences)


def _template_title(f: dict) -> str:
    rulers = [s["ruler"] for s in f["succession"] if "ruler" in s]
    n = f["rulers_recorded"]
    text = f"The {(f['tier'] or 'title').lower()} of {f['name']} records {n} holder{'s' if n != 1 else ''}."
    if rulers:
        text += f" The first recorded was {rulers[0]}, the last {rulers[-1]}."
    return text


USER_AGENT = "ck3-history-extractor (+https://github.com/diegoami/Ck-parser)"


class BackendError(RuntimeError):
    """The model could not be asked at all: a bad key, no credit, no server.

    Stops the run rather than skipping the page, because the next page would
    fail the same way.
    """


class OpenAICompatible:
    """Any server speaking ``POST {url}/chat/completions``, over plain HTTP.

    Ollama serves it at ``http://localhost:11434/v1``, llama.cpp's server and LM
    Studio at their own ports, OpenCode Zen at ``https://opencode.ai/zen/v1``
    for its DeepSeek, GLM, Kimi and MiniMax models. A reasoning model's
    ``<think>`` block is dropped: it is the model's scratch work, not the entry.

    `usage` adds up the tokens the server says it billed, so a run can report
    what it cost rather than leave it to an estimate.
    """

    def __init__(self, url: str, model: str, api_key: str | None = None, timeout: float = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.name = f"openai:{model}"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def write(self, facts: dict, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.3,
            "stream": False,
        }).encode("utf-8")
        # a named client: opencode.ai sits behind Cloudflare, which answers
        # urllib's default `Python-urllib/3.x` with 403 "error code: 1010"
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.url}/chat/completions", body, headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise BackendError(f"{self.url} answered HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BackendError(f"cannot reach {self.url}: {exc}") from None
        for key in self.usage:
            self.usage[key] += int((reply.get("usage") or {}).get(key) or 0)
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
    counts = {"written": 0, "kept": 0, "rejected": 0, "missing": 0, "failed": 0}
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
        try:
            text = backend.write(facts, system, user)
        except BackendError as exc:
            print(f"  stopped at {kind}/{ident}: {exc}", file=log)
            counts["failed"] = 1
            break
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

    from .build import discover, load_localization, load_run, subject_of

    ap = argparse.ArgumentParser(prog="python -m ck3wiki.prose", description=__doc__.splitlines()[0])
    ap.add_argument("save", help="a .ck3 file, or a directory of saves")
    ap.add_argument("--out", default="prose", help="prose directory (default: ./prose)")
    ap.add_argument("--run", dest="run_id", help="only this run (its id or slug)")
    ap.add_argument("--title", help="subject title (default: each run's own, as the build does)")
    ap.add_argument("--character", action="append", default=[], metavar="ID",
                    help="write this character's page instead of the rulers'; repeatable")
    # each also read from the environment, so `uv run --env-file .env` is all
    # a local run needs; the key is only ever read from there
    env = os.environ
    ap.add_argument("--backend", choices=("template", "openai"),
                    default=env.get("CK3_PROSE_BACKEND") or "template")
    ap.add_argument("--url", default=env.get("CK3_PROSE_URL") or "http://localhost:11434/v1",
                    help="OpenAI-compatible base URL (default: $CK3_PROSE_URL, else Ollama's)")
    ap.add_argument("--model", default=env.get("CK3_PROSE_MODEL") or None,
                    help="model name, as the server knows it (default: $CK3_PROSE_MODEL)")
    ap.add_argument("--force", action="store_true", help="rewrite prose that is still current")
    ap.add_argument("--cache", default=".ck3cache", help="character digests, as for the build")
    # the same text the build will use, or the facts differ and every paragraph
    # is stale by the time it is folded in (#54)
    ap.add_argument("--game", help="the game's `game` directory, as for the build")
    ap.add_argument("--localization", help="a localization extract, as for the build")
    args = ap.parse_args(argv)

    try:
        backend = make_backend(args.backend, args.url, args.model, os.environ.get("CK3_PROSE_API_KEY"))
        runs = discover(args.save, args.run_id)
        source = load_localization(args.game, args.localization)
    except (ValueError, OSError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2
    log = sys.stderr
    status = 0
    for run in runs:
        subject = subject_of(run, args.title, log)
        if subject is None:
            continue
        loc = source.for_run(run.version)[0] if source is not None else None
        wiki = load_run(run, subject, log=log, cache_dir=Path(args.cache), loc=loc)
        if wiki is None:
            continue
        pages = [("characters", c) for c in args.character] or rulers(wiki)
        counts = generate(wiki, run.slug, pages, backend, Path(args.out), args.force, log)
        print(f"  {run.slug}: " + ", ".join(f"{n} {k}" for k, n in counts.items()), file=log)
        if counts["failed"]:
            return 2
        if counts["rejected"] or counts["missing"]:
            status = 1
    usage = getattr(backend, "usage", None)
    if usage:
        print(f"tokens billed: {usage['prompt_tokens']} in, {usage['completion_tokens']} out", file=log)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
