"""Build tiny synthetic saves that share the real container layout."""

from __future__ import annotations

import re
from pathlib import Path

from ck3parser.container import write_save

FIXTURE = Path(__file__).with_name("fixtures") / "gamestate_sample.txt"


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def split_meta(gamestate_text: str) -> tuple[str, str]:
    """The header of a real save is the same ``meta_data`` block the gamestate starts with."""
    end = gamestate_text.index("\n}\n") + 3
    return gamestate_text[:end], gamestate_text


def set_scalar(text: str, key: str, value: str, indent: str = "") -> str:
    pattern = re.compile(rf"^{re.escape(indent)}{re.escape(key)}=.*$", re.M)
    assert pattern.search(text), f"{key} not in text"
    return pattern.sub(f"{indent}{key}={value}", text, count=1)


def make_save(
    path: Path,
    *,
    date: str = "1100.6.1",
    real_date: str = "126.3.6",
    seed: int = 424242,
    random_count: int = 1000,
    legacy_trim: int = 0,
    player_account: str = "tester",
    version: str = '"1.6.1.2"',
) -> Path:
    text = fixture_text()
    text = set_scalar(text, "meta_date", date, "\t")
    text = set_scalar(text, "meta_real_date", real_date, "\t")
    text = set_scalar(text, "version", version, "\t")
    text = set_scalar(text, "date", date)
    text = set_scalar(text, "random_seed", str(seed))
    text = set_scalar(text, "random_count", str(random_count))
    text = text.replace('name="tester"', f'name="{player_account}"')
    if legacy_trim:
        # drop the last N legacy entries
        start = text.index("legacy={")
        end = text.index("\n }\n", start) + 4
        block = text[start:end]
        entries = re.findall(r"\{\n(?:\t\t\t.*\n)+\t\t\}", block)
        kept = entries[: len(entries) - legacy_trim]
        text = text[:start] + "legacy={ " + "\n ".join(kept) + "\n }\n" + text[end:]
    meta, gamestate = split_meta(text)
    return write_save(path, meta, gamestate)
