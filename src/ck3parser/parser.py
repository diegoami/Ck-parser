"""Streaming Clausewitz-script parser.

The format is ``key=value`` pairs and ``{ ... }`` blocks. What the real saves
throw at it (all seen in the sample files):

* keys that are identifiers, integers (``50544311=``) or dates (``867.1.1=``);
* values that are quoted strings, bare tokens, ints, floats, dates, ``yes``/``no``;
* bare lists ``{ 5 7 4 4 2 9 }`` and lists of anonymous blocks ``{ { ... } { ... } }``;
* blocks that mix ``date=holder`` with ``date={ type=destroyed }``;
* repeated keys (``perk="a" perk="b"``);
* entries at column 0 inside a nested block, so indentation means nothing.

Only braces matter. The tokenizer is line based (tokens never span lines in a
save), which keeps memory flat for a 280 MB ``gamestate``.

Representation
--------------
A block with at least one ``key=value`` pair becomes a :class:`Block`, an
ordered list of ``(key, value)`` pairs with dict-like helpers that preserve
repeated keys. A block with only bare values becomes a plain ``list``. An
empty block becomes an empty :class:`Block`.

Assumptions still to check against more saves: no ``#`` comments inside
``gamestate``; no quoted string containing a newline.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Iterable, Iterator, TextIO

_TOKEN = re.compile(r'\s*(?:(\{)|(\})|(=)|"((?:[^"\\]|\\.)*)"|([^\s{}="]+))')
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")
_DATE = re.compile(r"^\d+\.\d+\.\d+$")


class Quoted(str):
    """A string that was quoted in the source (kept distinct from bare tokens)."""

    __slots__ = ()


class Block(list):
    """Ordered ``(key, value)`` pairs with dict-like access. Repeated keys are kept."""

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self:
            if k == key:
                return v
        return default

    def getall(self, key: str) -> list:
        return [v for k, v in self if k == key]

    def keys(self) -> list:
        return [k for k, _ in self]

    def items(self) -> Iterator[tuple]:
        return iter(self)

    def __contains__(self, key) -> bool:  # type: ignore[override]
        return any(k == key for k, _ in self)

    def as_dict(self) -> dict:
        """Lossy: repeated keys collapse to the last value."""
        return {k: v for k, v in self}

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, (int, slice)):
            return list.__getitem__(self, key)
        for k, v in self:
            if k == key:
                return v
        raise KeyError(key)


def convert(atom: str) -> Any:
    """Turn a bare token into a Python value. Dates stay strings."""
    if atom == "yes":
        return True
    if atom == "no":
        return False
    if _INT.match(atom):
        return int(atom)
    if _DATE.match(atom):
        return atom
    if _FLOAT.match(atom):
        return float(atom)
    return atom


class FormatError(ValueError):
    """The text breaks an assumption the parser makes about the save format.

    Raised rather than parsed around: guessing past a construct the saves have
    never contained produces a wrong wiki with no sign of it (PLAN.md §5).
    """


def _format_error(what: str, number: int, line: str) -> FormatError:
    shown = line.strip()
    shown = shown if len(shown) <= 80 else shown[:77] + "..."
    return FormatError(
        f"{what}, line {number:,} of the text read: {shown!r}. The parser assumes the save"
        " has none (docs/PLAN.md §5); if a new game version writes them, teach it to."
    )


#: the rest of a quoted string that opened on an earlier line: text up to the
#: first unescaped quote
_CLOSING = re.compile(r'((?:[^"\\]|\\.)*)"')


def tokenize_lines(lines: Iterable[str]) -> Iterator[Any]:
    """Yield tokens: the strings ``{`` ``}`` ``=`` (as :class:`_Sym`), :class:`Quoted`, or bare ``str``.

    A quoted string may run over several lines, newlines included: the Germania
    saves write a truce's description that way (PLAN.md §5), which an earlier
    version of this tokenizer cut into stray words without a sign. A string
    never closed, and a ``#`` comment, which no save has contained and which
    would otherwise arrive as words parsed as keys, raise :class:`FormatError`.
    """
    number = 0
    pending: list[str] | None = None  # the parts of a string still open
    opened_at = 0
    for number, line in enumerate(lines, 1):
        pos = 0
        n = len(line)
        if pending is not None:
            closing = _CLOSING.match(line)
            if closing is None:
                pending.append(line)
                continue
            pending.append(closing.group(1))
            yield Quoted("".join(pending))
            pending = None
            pos = closing.end()
        while pos < n:
            m = _TOKEN.match(line, pos)
            if not m or m.end() == pos:
                # only whitespace is left, unless a quote opened and did not
                # close on this line: every other character matches a pattern
                rest = line[pos:].lstrip()
                if rest:
                    pending, opened_at = [rest[1:]], number
                break
            pos = m.end()
            if m.group(5) is not None and m.group(5).startswith("#"):
                raise _format_error("a '#' comment", number, line)
            if m.group(1):
                yield OPEN
            elif m.group(2):
                yield CLOSE
            elif m.group(3):
                yield EQ
            elif m.group(4) is not None:
                yield Quoted(m.group(4))
            else:
                yield m.group(5)
    if pending is not None:
        raise _format_error("a quoted string is never closed", opened_at, '"' + pending[0])


class _Sym:
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name


OPEN, CLOSE, EQ = _Sym("{"), _Sym("}"), _Sym("=")


class TokenStream:
    def __init__(self, tokens: Iterable[Any]):
        self._it = iter(tokens)
        self._peeked: list = []

    def peek(self):
        if not self._peeked:
            try:
                self._peeked.append(next(self._it))
            except StopIteration:
                self._peeked.append(EOF)
        return self._peeked[-1]

    def next(self):
        if self._peeked:
            return self._peeked.pop()
        try:
            return next(self._it)
        except StopIteration:
            return EOF


EOF_ = _Sym("EOF")
EOF = EOF_


def _value_of(tok, ts: TokenStream):
    if tok is OPEN:
        return parse_block(ts)
    if isinstance(tok, Quoted):
        return tok
    return convert(tok)


def parse_block(ts: TokenStream) -> Block | list:
    """Parse the inside of a block; the opening ``{`` has already been consumed."""
    items: list = []
    keyed = False
    while True:
        tok = ts.next()
        if tok is CLOSE or tok is EOF:
            break
        if tok is OPEN:
            items.append((None, parse_block(ts)))
            continue
        if tok is EQ:
            continue  # stray '=' (seen as '={' after a list in some PDX files); ignore
        if ts.peek() is EQ:
            ts.next()
            val_tok = ts.next()
            items.append((str(tok), _value_of(val_tok, ts)))
            keyed = True
        else:
            items.append((None, _value_of(tok, ts)))
    if keyed or not items:
        return Block(items)
    return [v for _, v in items]


def skip_block(ts: TokenStream) -> None:
    """Consume tokens up to and including the matching ``}`` without building anything."""
    depth = 1
    while depth:
        tok = ts.next()
        if tok is EOF:
            return
        if tok is OPEN:
            depth += 1
        elif tok is CLOSE:
            depth -= 1


def parse_text(text: str) -> Block | list:
    """Parse a complete Clausewitz document held in memory (fixtures, headers)."""
    ts = TokenStream(tokenize_lines(text.splitlines()))
    return parse_block(ts)


def iter_pairs(ts: TokenStream, only: set[str] | None = None) -> Iterator[tuple[str, Any]]:
    """Yield ``(key, value)`` pairs at the current depth until the matching ``}`` or EOF.

    With ``only``, values of other keys are skipped without being built, which is
    what makes iterating a 280 MB file affordable.
    """
    while True:
        tok = ts.next()
        if tok is CLOSE or tok is EOF:
            return
        if tok is OPEN:
            skip_block(ts)
            continue
        if tok is EQ:
            continue
        if ts.peek() is not EQ:
            continue  # bare value at this level; ignore
        ts.next()
        key = str(tok)
        val_tok = ts.next()
        if only is not None and key not in only:
            if val_tok is OPEN:
                skip_block(ts)
            continue
        yield key, _value_of(val_tok, ts)


def iter_top_level(lines: Iterable[str], only: set[str] | None = None) -> Iterator[tuple[str, Any]]:
    """Stream the top-level ``key=value`` pairs of a gamestate."""
    return iter_pairs(TokenStream(tokenize_lines(lines)), only)


def seek_top_level(lines: Iterator[str], name: str) -> bool:
    """Advance a line iterator to the line ``name={`` (or ``name=``) at column 0.

    Top-level keys sit at column 0 and their children are indented, except for
    numbered entries inside nested blocks, which never collide with an
    identifier name. This is a fast path for jumping to sections deep in the
    file (``played_character`` is ~14 M lines in) without tokenizing everything.
    Returns False at EOF. On success the next tokens come from that line.
    """
    prefix = name + "="
    for line in lines:
        if line.startswith(prefix):
            _pushback(lines, line)
            return True
    return False


class PushbackLines:
    """A line iterator that supports pushing one line back."""

    def __init__(self, lines: Iterable[str]):
        self._it = iter(lines)
        self._back: list[str] = []

    def __iter__(self):
        return self

    def __next__(self):
        if self._back:
            return self._back.pop()
        return next(self._it)

    def push(self, line: str):
        self._back.append(line)


def _pushback(lines, line):
    if isinstance(lines, PushbackLines):
        lines.push(line)
    else:
        raise TypeError("seek_top_level needs a PushbackLines iterator")


def iter_children(lines: Iterable[str], path: tuple[str, ...], only: set[str] | None = None) -> Iterator[tuple[str, Any]]:
    """Stream the direct children of the block at ``path``.

    ``path`` is a tuple of keys from the top level, e.g. ``("living",)`` or
    ``("landed_titles", "landed_titles")``. The first key is found with a
    column-0 line scan; the rest by tokenizing. Each child is built fully, one
    at a time, so memory stays bounded by the largest single child.
    """
    pb = lines if isinstance(lines, PushbackLines) else PushbackLines(lines)
    if not seek_top_level(pb, path[0]):
        return
    ts = TokenStream(tokenize_lines(pb))
    # consume "name" "=" "{"
    tok = ts.next()
    if str(tok) != path[0] or ts.next() is not EQ or ts.next() is not OPEN:
        raise ValueError(f"expected {path[0]}={{ at seek position")
    for key in path[1:]:
        found = False
        while True:
            tok = ts.next()
            if tok is CLOSE or tok is EOF:
                break
            if tok is OPEN:
                skip_block(ts)
                continue
            if ts.peek() is EQ:
                ts.next()
                val_tok = ts.next()
                if str(tok) == key and val_tok is OPEN:
                    found = True
                    break
                if val_tok is OPEN:
                    skip_block(ts)
        if not found:
            return
    yield from iter_pairs(ts, only)


def read_top_level(lines: Iterable[str], name: str) -> Any:
    """Seek to a top-level key and return its fully built value (or None)."""
    pb = lines if isinstance(lines, PushbackLines) else PushbackLines(lines)
    if not seek_top_level(pb, name):
        return None
    ts = TokenStream(tokenize_lines(pb))
    tok = ts.next()
    if str(tok) != name or ts.next() is not EQ:
        raise ValueError(f"expected {name}= at seek position")
    return _value_of(ts.next(), ts)


def date_key(date: str) -> tuple[int, int, int]:
    """``"867.1.1"`` -> ``(867, 1, 1)`` for ordering."""
    y, m, d = (int(x) for x in str(date).split("."))
    return y, m, d


def to_date(value: Any) -> datetime.date | None:
    """``"867.1.1"`` -> ``date(867, 1, 1)``; None or an unparseable value -> None.

    Save dates run from year 3 to the 9999 "never" sentinel and every one of the
    64 876 distinct dates in the sample saves is a real calendar date, so this
    conversion is lossless (docs/PLAN.md §5).
    """
    if value is None:
        return None
    try:
        return datetime.date(*date_key(value))
    except (TypeError, ValueError):
        return None
