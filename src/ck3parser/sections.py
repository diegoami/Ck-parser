"""The top-level layout of a ``gamestate``, and a whole-file parse check.

Two things live here, both streaming:

:func:`section_index` walks the file once by line and records where each
top-level key starts and ends. Top-level keys are the only identifiers at
column 0: the numbered entries inside ``landed_titles`` also sit at column 0 but
start with a digit, and everything else is indented. The index is what tells you
which sections a save actually has and how big they are, without parsing them.

:func:`verify_parse` pushes the whole file through the tokenizer and checks that
the braces balance and that it reaches the end. It is the standing proof that
the parser copes with a real 280 MB save rather than only the sections the
pipeline happens to read.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Iterator

from .container import open_gamestate_text
from .parser import CLOSE, OPEN, FormatError, tokenize_lines

#: A top-level key: an identifier at column 0 followed by ``=``.
TOP_LEVEL = re.compile(r"^([A-Za-z_][A-Za-z_0-9]*)=(\{?)")


@dataclass
class Section:
    name: str
    start_line: int
    end_line: int
    block: bool  #: False for a bare ``key=value`` scalar such as ``date=``

    @property
    def lines(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class SectionSummary:
    name: str
    occurrences: int
    first_line: int
    lines: int
    block: bool


@dataclass
class ParseReport:
    tokens: int
    max_depth: int
    final_depth: int
    reached_end: bool

    @property
    def balanced(self) -> bool:
        return self.final_depth == 0

    @property
    def ok(self) -> bool:
        return self.balanced and self.reached_end

    def __str__(self) -> str:
        verdict = "ok" if self.ok else ("unbalanced" if not self.balanced else "truncated")
        return (
            f"{verdict}: {self.tokens:,} tokens, max depth {self.max_depth},"
            f" final depth {self.final_depth}"
        )


def iter_sections(lines: Iterable[str]) -> Iterator[Section]:
    """Yield one :class:`Section` per top-level key, in file order."""
    current: Section | None = None
    line_number = 0
    for line_number, line in enumerate(lines, start=1):
        match = TOP_LEVEL.match(line)
        if match is None:
            continue
        if current is not None:
            current.end_line = line_number - 1
            yield current
        current = Section(
            name=match.group(1), start_line=line_number, end_line=line_number, block=bool(match.group(2))
        )
    if current is not None:
        current.end_line = line_number
        yield current


def section_index(save_path: str) -> list[Section]:
    with open_gamestate_text(save_path) as lines:
        return list(iter_sections(lines))


def summarize(sections: Iterable[Section]) -> list[SectionSummary]:
    """Collapse repeated keys (``triggered_event`` appears thousands of times)."""
    counts: Counter[str] = Counter()
    total: Counter[str] = Counter()
    first: dict[str, int] = {}
    block: dict[str, bool] = {}
    for section in sections:
        counts[section.name] += 1
        total[section.name] += section.lines
        first.setdefault(section.name, section.start_line)
        block.setdefault(section.name, section.block)
    return sorted(
        (
            SectionSummary(name, counts[name], first[name], total[name], block[name])
            for name in counts
        ),
        key=lambda s: s.first_line,
    )


def verify_parse(save_path: str) -> ParseReport:
    """Tokenize the whole file and report whether the braces balance."""
    depth = 0
    deepest = 0
    tokens = 0
    with open_gamestate_text(save_path) as lines:
        for token in tokenize_lines(lines):
            tokens += 1
            if token is OPEN:
                depth += 1
                deepest = max(deepest, depth)
            elif token is CLOSE:
                depth -= 1
    return ParseReport(tokens=tokens, max_depth=deepest, final_depth=depth, reached_end=True)


def format_index(summaries: Iterable[SectionSummary], total_lines: int | None = None) -> str:
    rows = list(summaries)
    total = total_lines or sum(r.lines for r in rows)
    width = max((len(r.name) for r in rows), default=4)
    out = [f"{'section'.ljust(width)}  {'count':>6}  {'first line':>11}  {'lines':>12}  {'share':>6}"]
    for row in rows:
        share = 100 * row.lines / total if total else 0
        kind = row.name if row.block else f"{row.name} (scalar)"
        out.append(f"{kind.ljust(width)}  {row.occurrences:>6}  {row.first_line:>11,}  {row.lines:>12,}  {share:>5.1f}%")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m ck3parser.sections", description=__doc__.split("\n\n")[0])
    ap.add_argument("save")
    ap.add_argument("--verify", action="store_true", help="also tokenize the whole file and check the braces")
    args = ap.parse_args(argv)

    sections = section_index(args.save)
    total = sections[-1].end_line if sections else 0
    print(format_index(summarize(sections), total))
    print(f"\n{len(sections)} top-level entries, {len(summarize(sections))} distinct keys, {total:,} lines")
    if args.verify:
        try:
            report = verify_parse(args.save)
        except FormatError as exc:
            print(f"parse failed: {exc}", file=sys.stderr)
            return 1
        print(f"whole-file parse: {report}")
        return 0 if report.ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
