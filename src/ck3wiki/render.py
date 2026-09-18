"""Static HTML for a :class:`~ck3wiki.model.Wiki`.

Plain stdlib string building rather than a template engine: the site is a few
page shapes, and the project keeps its dependency list to what it actually
needs. Everything is relative-linked and self-contained, so the output works
from a file:// path, from GitHub Pages, or from any static host.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

from .model import Wiki, WikiCharacter, WikiTitle

STYLE = """\
:root {
  color-scheme: light dark;
  --bg: #fbfaf7; --panel: #fff; --ink: #1b1a17; --muted: #6a675f;
  --rule: #e2ded4; --link: #7a4b1e; --accent: #8c6d3f;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14130f; --panel: #1c1b16; --ink: #ece8df; --muted: #a09a8c;
          --rule: #2e2c25; --link: #d6a865; --accent: #c8a46d; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.6 Georgia, 'Iowan Old Style', serif; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
header { border-bottom: 1px solid var(--rule); background: var(--panel); }
header .inner, main { max-width: 52rem; margin: 0 auto; padding: 1rem 1.25rem; }
header a.home { font-size: .85rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); }
h1 { font-size: 1.9rem; margin: .4rem 0 .2rem; line-height: 1.2; }
h2 { font-size: 1.2rem; margin: 2rem 0 .6rem; padding-bottom: .3rem;
  border-bottom: 1px solid var(--rule); font-weight: normal; letter-spacing: .02em; }
.sub { color: var(--muted); font-size: .95rem; margin: 0 0 1rem; }
table { width: 100%; border-collapse: collapse; margin: .5rem 0 1rem; font-size: .95rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule);
  vertical-align: top; }
th { color: var(--muted); font-weight: normal; font-size: .8rem;
  text-transform: uppercase; letter-spacing: .06em; }
td.num, th.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.card { background: var(--panel); border: 1px solid var(--rule); border-radius: 4px;
  padding: .9rem 1.1rem; margin: 1rem 0; }
/* Two columns rather than a float: a table cannot wrap around a float, so a
   floated infobox leaves a dead gap beside every succession table. */
.page { display: grid; grid-template-columns: minmax(0, 1fr) 17rem; gap: 0 1.6rem;
  align-items: start; }
.page > .content { grid-column: 1; grid-row: 1; min-width: 0; }
.page > .infobox { grid-column: 2; grid-row: 1; margin-top: 1rem; }
.infobox table { margin: 0; font-size: .9rem; }
.content > h2:first-child { margin-top: 1rem; }
.infobox img { width: 100%; border-radius: 3px; display: block; margin-bottom: .6rem; }
.tag { display: inline-block; font-size: .75rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); border: 1px solid var(--rule);
  border-radius: 2px; padding: .05rem .4rem; }
.current { color: var(--accent); font-weight: bold; }
ul.plain { list-style: none; padding: 0; }
ul.plain li { padding: .2rem 0; border-bottom: 1px solid var(--rule); }
footer { max-width: 52rem; margin: 2rem auto 3rem; padding: 0 1.25rem;
  color: var(--muted); font-size: .85rem; }
@media (max-width: 46rem) {
  .page { grid-template-columns: minmax(0, 1fr); }
  .page > .infobox, .page > .content { grid-column: 1; grid-row: auto; }
}
"""

TIER_WORD = {
    "empire": "Empire",
    "kingdom": "Kingdom",
    "duchy": "Duchy",
    "county": "County",
    "barony": "Barony",
}


def e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def page(title: str, body: str, depth: int = 0, subtitle: str = "") -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head><body>
<header><div class="inner"><a class="home" href="{up}index.html">CK3 Chronicle</a>
<h1>{e(title)}</h1>{f'<p class="sub">{e(subtitle)}</p>' if subtitle else ''}</div></header>
<main>
{body}
</main>
<footer>Generated from Crusader Kings III save files by
<a href="https://github.com/diegoami/Ck-parser">Ck-parser</a>. Dates are in-game.
Names are transcribed from save keys and drop diacritics.</footer>
</body></html>
"""


def rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(f"<tr><th>{e(k)}</th><td>{v}</td></tr>" for k, v in pairs if v)


def title_link(wiki: Wiki, key: str, depth: int) -> str:
    up = "../" * depth
    known = wiki.titles.get(key)
    label = known.name if known else key
    if known is None:
        return f"{e(label)} <span class=\"tag\">not in this wiki</span>"
    return f'<a href="{up}titles/{e(key)}.html">{e(label)}</a>'


def character_link(wiki: Wiki, cid: int, depth: int) -> str:
    up = "../" * depth
    return f'<a href="{up}characters/{cid}.html">{e(wiki.named(cid))}</a>'


def tenure_rows(wiki: Wiki, title: WikiTitle, depth: int) -> str:
    out = []
    for tenure in title.tenures:
        span = f'{e(tenure.start or "?")} – {e(tenure.end or "?")}'
        if tenure.open:
            span += ' <span class="tag">current</span>'
        reason = e(tenure.reason.replace("_", " ")) if tenure.reason else ""
        out.append(
            f'<tr><td class="num">{span}</td>'
            f"<td>{character_link(wiki, tenure.holder, depth)}</td>"
            f"<td>{reason}</td></tr>"
        )
    return "".join(out)


def render_title(wiki: Wiki, title: WikiTitle) -> str:
    heading = f'{TIER_WORD.get(title.tier or "", "Title")} of {title.name}'
    info = rows(
        [
            ("Tier", e(TIER_WORD.get(title.tier or "", title.tier))),
            ("Key", f"<code>{e(title.key)}</code>"),
            ("Current holder", character_link(wiki, title.holder, 1) if title.holder else ""),
            ("Liege", title_link(wiki, title.liege, 1) if title.liege else ""),
            ("De jure liege", title_link(wiki, title.de_jure_liege, 1) if title.de_jure_liege else ""),
            ("Rulers recorded", str(len(title.tenures))),
            ("Seen in saves", f"{e(title.first_seen)} – {e(title.last_seen)}"),
        ]
    )
    body = [f'<div class="page"><aside class="infobox card"><table>{info}</table></aside>',
            '<div class="content">']
    body.append("<h2>Succession</h2>")
    if title.tenures:
        body.append(
            "<table><thead><tr><th>Held</th><th>Ruler</th><th>How</th></tr></thead>"
            f"<tbody>{tenure_rows(wiki, title, 1)}</tbody></table>"
        )
    else:
        body.append("<p>No holders are recorded for this title.</p>")

    if title.vassals:
        body.append("<h2>Vassals</h2>")
        for date in sorted(title.vassals):
            keys = title.vassals[date]
            links = ", ".join(title_link(wiki, key, 1) for key in keys) or "none"
            body.append(f'<p><strong>{e(date)}</strong> — {len(keys)} held under it: {links}</p>')
    body.append("</div></div>")
    return page(heading, "\n".join(body), depth=1, subtitle=f"{len(title.tenures)} recorded rulers")


def render_character(wiki: Wiki, character: WikiCharacter, portrait: str | None) -> str:
    held = wiki.held_by(character.id)
    info = rows(
        [
            ("Born", e(character.birth)),
            ("Died", e(character.death) if character.death else '<span class="tag">alive</span>'),
            ("Cause", e(character.death_reason.replace("death_", "").replace("_", " ")) if character.death_reason else ""),
            ("Sex", "female" if character.female else "male"),
            ("House", f"<code>{character.house}</code>" if character.house else ""),
            ("Id", f"<code>{character.id}</code>"),
            ("In saves", ", ".join(e(d) for d in character.seen)),
        ]
    )
    image = f'<img src="../portraits/{e(portrait)}" alt="Portrait of {e(character.name)}">' if portrait else ""
    body = [f'<div class="page"><aside class="infobox card">{image}<table>{info}</table></aside>',
            '<div class="content">']
    body.append("<h2>Titles held</h2>")
    if held:
        lines = []
        for title, tenure in held:
            span = f'{e(tenure.start or "?")} – {e(tenure.end or "?")}'
            mark = ' <span class="tag">current</span>' if tenure.open else ""
            # two titles can share a display name (a duchy and a kingdom of
            # Pomerania), so the tier is what tells them apart
            tier = e(TIER_WORD.get(title.tier or "", title.tier or ""))
            lines.append(
                f'<tr><td class="num">{span}{mark}</td>'
                f"<td>{title_link(wiki, title.key, 1)}</td><td>{tier}</td></tr>"
            )
        body.append(
            "<table><thead><tr><th>Held</th><th>Title</th><th>Tier</th></tr></thead>"
            f"<tbody>{''.join(lines)}</tbody></table>"
        )
    else:
        body.append("<p>This character holds none of the titles in this wiki.</p>")
    body.append("</div></div>")
    return page(character.name or f"Character {character.id}", "\n".join(body), depth=1, subtitle=character.lifespan)


def render_index(wiki: Wiki) -> str:
    root = wiki.root
    body = []
    if root:
        body.append(
            f'<div class="card"><p>This chronicle follows <strong>{title_link(wiki, root.key, 0)}</strong>'
            f" and the titles held under it, across {len(wiki.snapshots)} save"
            f'{"s" if len(wiki.snapshots) != 1 else ""} of one playthrough:'
            f' {", ".join(e(d) for d in wiki.snapshots)}.</p>'
            f"<p>{len(wiki.titles)} titles and {len(wiki.characters)} characters are recorded,"
            f" with {sum(len(t.tenures) for t in wiki.titles.values())} reigns between them.</p></div>"
        )
    body.append("<h2>Titles</h2><table><thead><tr><th>Title</th><th>Tier</th>"
                "<th class='num'>Rulers</th><th>Current holder</th></tr></thead><tbody>")
    order = {"empire": 0, "kingdom": 1, "duchy": 2, "county": 3, "barony": 4}
    for title in sorted(wiki.titles.values(), key=lambda t: (order.get(t.tier or "", 9), t.name)):
        holder = character_link(wiki, title.holder, 0) if title.holder else "—"
        body.append(
            f"<tr><td>{title_link(wiki, title.key, 0)}</td>"
            f'<td>{e(TIER_WORD.get(title.tier or "", title.tier or ""))}</td>'
            f'<td class="num">{len(title.tenures)}</td><td>{holder}</td></tr>'
        )
    body.append("</tbody></table>")

    body.append("<h2>Characters</h2><table><thead><tr><th>Name</th><th class='num'>Lived</th>"
                "<th class='num'>Reigns</th></tr></thead><tbody>")
    for character in sorted(wiki.characters.values(), key=lambda c: (c.name or "", c.id)):
        body.append(
            f"<tr><td>{character_link(wiki, character.id, 0)}</td>"
            f'<td class="num">{e(character.lifespan)}</td>'
            f'<td class="num">{len(wiki.held_by(character.id))}</td></tr>'
        )
    body.append("</tbody></table>")
    return page("CK3 Chronicle", "\n".join(body), depth=0,
                subtitle=f"run {wiki.run_id}" if wiki.run_id else "")


def find_portraits(directory: Path | None, ids: list[int]) -> dict[int, str]:
    """Match harvested ``<id>_<date>.png`` files to characters, newest first."""
    if directory is None or not directory.is_dir():
        return {}
    found: dict[int, str] = {}
    for cid in ids:
        matches = sorted(directory.glob(f"{cid}*.png"))
        if matches:
            found[cid] = matches[-1].name
    return found


def write_site(wiki: Wiki, out: Path, portraits: Path | None = None) -> int:
    """Write the whole site. Returns the number of pages written."""
    (out / "titles").mkdir(parents=True, exist_ok=True)
    (out / "characters").mkdir(parents=True, exist_ok=True)
    (out / "style.css").write_text(STYLE, encoding="utf-8")

    images = find_portraits(portraits, list(wiki.characters))
    if images and portraits is not None:
        shutil.copytree(portraits, out / "portraits", dirs_exist_ok=True)

    pages = 1
    (out / "index.html").write_text(render_index(wiki), encoding="utf-8")
    for title in wiki.titles.values():
        (out / "titles" / f"{title.key}.html").write_text(render_title(wiki, title), encoding="utf-8")
        pages += 1
    for character in wiki.characters.values():
        (out / "characters" / f"{character.id}.html").write_text(
            render_character(wiki, character, images.get(character.id)), encoding="utf-8"
        )
        pages += 1
    return pages
