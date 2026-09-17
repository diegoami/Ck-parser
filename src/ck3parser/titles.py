"""Title records and the liege/vassal structure of a save.

Two liege fields exist on a `landed_titles` entry and they mean different
things (verified on the real saves, see docs/PLAN.md §5):

``de_facto_liege``
    the title this one is **actually** held under at save time. This is the
    vassal structure the player sees, and the one this module follows.
``de_jure_liege``
    the map's nominal hierarchy, independent of who holds what.

Both are the *numeric index* of another entry in the same section, not a title
key, so they are only resolvable with the whole section indexed.

The index is built by streaming the section one entry at a time and keeping a
compact record per title, never the section text. On the 280 MB sample save
that is 12 915 records with about 107 000 history entries between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from .container import open_gamestate_text
from .parser import (
    CLOSE,
    EOF,
    EQ,
    OPEN,
    Block,
    PushbackLines,
    TokenStream,
    date_key,
    iter_pairs,
    parse_block,
    seek_top_level,
    skip_block,
    tokenize_lines,
)

TIER_BY_PREFIX = {"e": "empire", "k": "kingdom", "d": "duchy", "c": "county", "b": "barony"}
#: history entry types that end a tenure instead of starting one. Such an entry
#: repeats the *outgoing* holder, so it must not open an interval.
TERMINAL_TYPES = frozenset({"destroyed"})


@dataclass
class TitleRecord:
    idx: int
    key: str
    name: str | None = None
    adj: str | None = None
    tier: str | None = None
    holder: int | None = None
    de_facto_liege: int | None = None
    de_jure_liege: int | None = None
    capital: int | None = None
    date: str | None = None
    history: list[tuple[str, int | None, str | None]] = field(default_factory=list)
    #: ``(date, holder, reason)``; reason is the entry's ``type`` or None for a
    #: plain ``date=holder``. A terminal entry has ``holder=None``.

    @property
    def display_name(self) -> str:
        return self.name or clean_title_name(self.key)

    def holder_ids(self) -> set[int]:
        ids = {h for _, h, _ in self.history if h is not None}
        if self.holder is not None:
            ids.add(self.holder)
        return ids


def clean_title_name(key: str) -> str:
    """``e_germania`` -> ``Germania``; only used when the save gives no name."""
    prefix, _, rest = key.partition("_")
    if prefix in TIER_BY_PREFIX or prefix == "x":
        key = rest or key
    return key.replace("_", " ").title()


def tier_of(key: str, templates: dict[str, str] | None = None) -> str | None:
    """Tier from the key prefix, or from the dynamic template for an ``x_`` key."""
    prefix = key.split("_", 1)[0]
    if prefix in TIER_BY_PREFIX:
        return TIER_BY_PREFIX[prefix]
    if templates:
        return templates.get(key)
    return None


def normalize_history(history: Any) -> list[tuple[str, int | None, str | None]]:
    """Normalise a ``history`` block into ``(date, holder, reason)`` tuples.

    ``date=holder``            -> holder, no reason
    ``date={type=T holder=H}`` -> H with reason T, except for a terminal type
                                  (``destroyed``), where the holder names the
                                  outgoing ruler and the tenure ends.
    """
    if not isinstance(history, Block):
        return []
    out: list[tuple[str, int | None, str | None]] = []
    for date, value in history:
        date = str(date)
        if isinstance(value, int):
            out.append((date, value, None))
        elif isinstance(value, Block):
            reason = value.get("type")
            reason = str(reason) if reason is not None else None
            holder = value.get("holder")
            if reason in TERMINAL_TYPES or not isinstance(holder, int):
                out.append((date, None, reason))
            else:
                out.append((date, holder, reason))
    out.sort(key=lambda e: date_key(e[0]))
    return out


def _record(idx: int, block: Block, templates: dict[str, str], keep_history: bool) -> TitleRecord | None:
    key = block.get("key")
    if key is None:
        return None
    key = str(key)
    return TitleRecord(
        idx=idx,
        key=key,
        name=str(block["name"]) if block.get("name") is not None else None,
        adj=str(block["adj"]) if block.get("adj") is not None else None,
        tier=tier_of(key, templates),
        holder=block.get("holder") if isinstance(block.get("holder"), int) else None,
        de_facto_liege=block.get("de_facto_liege") if isinstance(block.get("de_facto_liege"), int) else None,
        de_jure_liege=block.get("de_jure_liege") if isinstance(block.get("de_jure_liege"), int) else None,
        capital=block.get("capital") if isinstance(block.get("capital"), int) else None,
        date=str(block["date"]) if block.get("date") is not None else None,
        history=normalize_history(block.get("history")) if keep_history else [],
    )


def iter_title_section(lines: Iterable[str]) -> Iterator[tuple[str, Any]]:
    """Stream the ``landed_titles`` section.

    Yields ``("templates", {key: tier})`` once, if the save has dynamic
    templates, then ``("title", (index, Block))`` per entry. Entries are built
    one at a time; the section is never held whole.
    """
    pb = lines if isinstance(lines, PushbackLines) else PushbackLines(lines)
    if not seek_top_level(pb, "landed_titles"):
        return
    ts = TokenStream(tokenize_lines(pb))
    if str(ts.next()) != "landed_titles" or ts.next() is not EQ or ts.next() is not OPEN:
        raise ValueError("expected landed_titles={ at seek position")
    while True:
        tok = ts.next()
        if tok is CLOSE or tok is EOF:
            return
        if tok is OPEN:
            skip_block(ts)
            continue
        if ts.peek() is not EQ:
            continue
        ts.next()
        key = str(tok)
        val_tok = ts.next()
        if key == "dynamic_templates" and val_tok is OPEN:
            templates = {}
            for entry in parse_block(ts):
                if isinstance(entry, Block) and entry.get("key") is not None:
                    templates[str(entry["key"])] = str(entry.get("tier")) if entry.get("tier") else None
            yield "templates", templates
        elif key == "landed_titles" and val_tok is OPEN:
            for idx, block in iter_pairs(ts):
                if isinstance(block, Block):
                    yield "title", (idx, block)
        elif val_tok is OPEN:
            skip_block(ts)


class TitleIndex:
    """All titles of one save, keyed by index and by title key."""

    def __init__(self) -> None:
        self.by_idx: dict[int, TitleRecord] = {}
        self.by_key: dict[str, TitleRecord] = {}
        self.templates: dict[str, str] = {}
        self._vassals: dict[int, list[int]] | None = None

    def add(self, record: TitleRecord) -> None:
        self.by_idx[record.idx] = record
        self.by_key.setdefault(record.key, record)
        self._vassals = None

    def get(self, key: str) -> TitleRecord | None:
        return self.by_key.get(key)

    def resolve(self, idx: int | None) -> TitleRecord | None:
        return self.by_idx.get(idx) if idx is not None else None

    @property
    def vassals(self) -> dict[int, list[int]]:
        """liege index -> indices of titles held under it (de facto)."""
        if self._vassals is None:
            out: dict[int, list[int]] = {}
            for record in self.by_idx.values():
                if record.de_facto_liege is not None:
                    out.setdefault(record.de_facto_liege, []).append(record.idx)
            for indices in out.values():
                indices.sort()
            self._vassals = out
        return self._vassals

    def immediate_vassals(self, title: TitleRecord | str) -> list[TitleRecord]:
        """Titles whose *current* liege is this one, ordered by tier then name."""
        record = self.get(title) if isinstance(title, str) else title
        if record is None:
            return []
        order = {"empire": 0, "kingdom": 1, "duchy": 2, "county": 3, "barony": 4}
        found = [self.by_idx[i] for i in self.vassals.get(record.idx, [])]
        found.sort(key=lambda r: (order.get(r.tier or "", 9), r.display_name))
        return found

    def liege_chain(self, title: TitleRecord | str, limit: int = 12) -> list[TitleRecord]:
        """This title, then its de facto liege, up to the independent top."""
        record = self.get(title) if isinstance(title, str) else title
        chain: list[TitleRecord] = []
        seen: set[int] = set()
        while record is not None and record.idx not in seen and len(chain) < limit:
            chain.append(record)
            seen.add(record.idx)
            record = self.resolve(record.de_facto_liege)
        return chain


def build_index(
    save_path: str,
    keep_history: bool | Callable[[str], bool] = True,
) -> TitleIndex:
    """Stream a save's ``landed_titles`` into a :class:`TitleIndex`.

    ``keep_history`` may be a predicate on the title key, to keep histories for
    only the titles that need them.
    """
    predicate = keep_history if callable(keep_history) else (lambda _key: bool(keep_history))
    index = TitleIndex()
    pending: list[tuple[int, Block]] = []
    with open_gamestate_text(save_path) as lines:
        for kind, payload in iter_title_section(lines):
            if kind == "templates":
                index.templates = {k: v for k, v in payload.items() if v}
                continue
            idx, block = payload
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            if not index.templates and str(block.get("key", "")).startswith("x_"):
                pending.append((idx, block))  # tier needs templates we have not seen
                continue
            record = _record(idx, block, index.templates, predicate(str(block.get("key", ""))))
            if record is not None:
                index.add(record)
    for idx, block in pending:
        record = _record(idx, block, index.templates, predicate(str(block.get("key", ""))))
        if record is not None:
            index.add(record)
    return index
