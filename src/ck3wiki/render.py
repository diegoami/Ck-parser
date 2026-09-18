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

from ck3parser.parser import date_key
from ck3parser.portraits import IMAGE_DIR

from .model import Image, Vassalage, Wiki, WikiCharacter, WikiHouse, WikiTitle

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
.infobox td code { font-size: .8rem; overflow-wrap: anywhere; }
.content > h2:first-child { margin-top: 1rem; }
.infobox img { width: 100%; border-radius: 3px; display: block; margin-bottom: .6rem; }
.tag { display: inline-block; font-size: .75rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); border: 1px solid var(--rule);
  border-radius: 2px; padding: .05rem .4rem; }
/* Every portrait slot is rendered, harvested or not, and points at the name
   both projects derive. A slot whose file is not here yet keeps the link, so
   the page starts working the moment the companion uploads it. */
.gallery { display: flex; flex-wrap: wrap; gap: .9rem; padding: 0; margin: .5rem 0 1rem; }
figure.shot { margin: 0; width: 9rem; }
figure.shot img { width: 100%; aspect-ratio: 3 / 4; object-fit: cover; display: block;
  border-radius: 3px; border: 1px solid var(--rule); background: var(--panel); }
figure.shot figcaption { font-size: .8rem; color: var(--muted); margin-top: .3rem;
  font-variant-numeric: tabular-nums; }
figure.shot.awaited img { border-style: dashed; }
figure.shot.awaited figcaption::after { content: " · awaiting harvest"; }
.infobox figure.shot { width: 100%; }
/* a real portrait keeps its own proportions; an empty slot has none of its
   own, so it holds the shape a portrait will have */
.infobox figure.shot img { aspect-ratio: auto; }
.infobox figure.shot.awaited img { aspect-ratio: 3 / 4; }
figure.shot.arms.awaited img { aspect-ratio: 1 / 1; }
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


def page(title: str, body: str, depth: int = 0, subtitle: str = "", top: bool = False) -> str:
    up = "../" * depth
    crumb = f'<a class="home" href="{up}../index.html">All chronicles</a> · ' if top else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head><body>
<header><div class="inner">{crumb}<a class="home" href="{up}index.html">CK3 Chronicle</a>
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


def person_link(wiki: Wiki, cid: int, depth: int) -> str:
    """A relative as a link if they have a page, as a name if they only have a record.

    Family reaches outside the lineage, so most of these people have no page.
    Naming them is still worth more than an id, and a name that is not a link
    says plainly that the wiki knows of them but not about them.
    """
    up = "../" * depth
    if cid in wiki.characters:
        return f'<a href="{up}characters/{cid}.html">{e(wiki.named(cid))}</a>'
    known = wiki.relatives.get(cid)
    if known is None or not known.name:
        return f"<code>{cid}</code>"
    span = f" <span class=\"sub\">({e(known.lifespan)})</span>" if known.lifespan else ""
    return f"{e(known.name)}{span}"


def people_row(wiki: Wiki, label: str, ids: list[int], depth: int) -> str:
    if not ids:
        return ""
    links = ", ".join(person_link(wiki, cid, depth) for cid in ids)
    return f"<tr><th>{e(label)}</th><td>{links}</td></tr>"


def house_link(wiki: Wiki, house_id: int | None, depth: int) -> str:
    if house_id is None:
        return ""
    up = "../" * depth
    known = wiki.houses.get(house_id)
    if known is None:
        return f'<code>{house_id}</code> <span class="tag">not in this wiki</span>'
    return f'<a href="{up}houses/{house_id}.html">{e(known.name)}</a>'


def image_slot(
    image: Image | None, depth: int, alt: str, caption: str, have: set[str], kind: str = "portrait"
) -> str:
    """One image the companion is expected to harvest, linked whether it is here.

    The `src` always points at the derived name, so nothing has to be rebuilt
    once the file lands: only the class changes, and that is cosmetic.
    """
    if image is None:
        return ""
    up = "../" * depth
    here = image.file in have
    # an empty slot is decorative: alt text on an image that is not there yet
    # only renders as a broken-image label, and the caption already says so
    state = "" if here else " awaited"
    return (
        f'<figure class="shot {kind}{state}" data-image="{e(image.file)}">'
        f'<img src="{up}{IMAGE_DIR}/{e(image.file)}" alt="{e(alt) if here else ""}" loading="lazy">'
        f"<figcaption>{e(caption)}</figcaption></figure>"
    )


def liege_label(wiki: Wiki, key: str | None, depth: int) -> str:
    """A liege as a link, or the honest word for having none.

    A liege outside the lineage has no page, so it is shown as the bare key
    rather than with the "not in this wiki" tag `title_link` uses: in this
    column that tag is wider than the name it explains, and the section's
    opening paragraph already accounts for it.
    """
    if key is None:
        return '<span class="tag">independent</span>'
    if key not in wiki.titles:
        return f'<code title="not in this wiki">{e(key)}</code>'
    return title_link(wiki, key, depth)


def vassalage_rows(wiki: Wiki, stretches: list[Vassalage], depth: int) -> str:
    """One row per stretch: who, which snapshots saw it, and how tight the bounds are."""
    out = []
    for stretch in stretches:
        seen = stretch.first if stretch.first == stretch.last else f"{stretch.first} – {stretch.last}"
        ended = f'<span class="tag">current</span>' if stretch.open else e(stretch.ended)
        out.append(
            f"<tr><td>{liege_label(wiki, stretch.liege, depth)}</td>"
            f'<td class="num">{e(seen)}</td>'
            f'<td class="num">{e(stretch.began)}</td><td class="num">{ended}</td></tr>'

        )
    return "".join(out)


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


def render_title(wiki: Wiki, title: WikiTitle, top: bool = False) -> str:
    heading = f'{TIER_WORD.get(title.tier or "", "Title")} of {title.name}'
    info = rows(
        [
            ("Tier", e(TIER_WORD.get(title.tier or "", title.tier))),
            ("Key", f"<code>{e(title.key)}</code>"),
            ("Current holder", character_link(wiki, title.holder, 1) if title.holder else ""),
            ("Liege", title_link(wiki, title.liege, 1) if title.liege else ""),
            ("De jure liege", title_link(wiki, title.de_jure_liege, 1) if title.de_jure_liege else ""),
            ("Rulers recorded", str(len(title.tenures))),
            # not "seen in saves": a title can be in a save without being in the
            # lineage, and the vassalage table below says so
            ("In the lineage", e(title.first_seen) if title.first_seen == title.last_seen
             else f"{e(title.first_seen)} – {e(title.last_seen)}"),
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

    stretches = title.vassalage(wiki.snapshots)
    if stretches:
        body.append("<h2>Vassalage</h2>")
        body.append(
            "<p>A save says who holds a title, but not who its liege has been over"
            " time. These are the saves' own answers, so a range under <em>Began</em>"
            " or <em>Ended</em> is a window the change happened somewhere inside —"
            " never a date, because no save carries one.</p>"
        )
        body.append(
            "<table><thead><tr><th>Under</th><th class='num'>Seen</th>"
            "<th>Began</th><th>Ended</th></tr></thead>"
            f"<tbody>{vassalage_rows(wiki, stretches, 1)}</tbody></table>"
        )
        missing = [d for d in wiki.snapshots if d not in title.lieges]
        if missing:
            body.append(
                f'<p class="sub">Not in the save of {", ".join(e(d) for d in missing)}'
                " — destroyed, or pruned; the save does not say which.</p>"
            )

    if title.vassals:
        body.append("<h2>Vassals</h2>")
        for date in sorted(title.vassals, key=date_key):
            keys = title.vassals[date]
            links = ", ".join(title_link(wiki, key, 1) for key in keys) or "none"
            body.append(f'<p><strong>{e(date)}</strong> — {len(keys)} held under it: {links}</p>')
        body.append(movement_note(wiki, title))
    body.append("</div></div>")
    return page(heading, "\n".join(body), depth=1, subtitle=f"{len(title.tenures)} recorded rulers", top=top)


def movement_note(wiki: Wiki, title: WikiTitle) -> str:
    """What joined and left between consecutive snapshots of the subject."""
    dates = sorted(title.vassals, key=date_key)
    if len(dates) < 2:
        return ""
    out = []
    for earlier, later in zip(dates, dates[1:]):
        was, now = set(title.vassals[earlier]), set(title.vassals[later])
        joined, left = sorted(now - was), sorted(was - now)
        if not joined and not left:
            continue
        parts = []
        if joined:
            parts.append(f"{len(joined)} joined ({', '.join(title_link(wiki, k, 1) for k in joined[:6])}"
                         f"{', …' if len(joined) > 6 else ''})")
        if left:
            parts.append(f"{len(left)} left ({', '.join(title_link(wiki, k, 1) for k in left[:6])}"
                         f"{', …' if len(left) > 6 else ''})")
        out.append(f"<li>Between <strong>{e(earlier)}</strong> and <strong>{e(later)}</strong>: "
                   + "; ".join(parts) + "</li>")
    return f'<ul class="plain">{"".join(out)}</ul>' if out else ""


def render_character(wiki: Wiki, character: WikiCharacter, have: set[str], top: bool = False) -> str:
    held = wiki.held_by(character.id)
    house = wiki.houses.get(character.house) if character.house else None
    # newest first: the infobox wants the latest likeness, the gallery the run
    shots = sorted(character.portraits, key=lambda p: date_key(p.save_date), reverse=True)
    info = rows(
        [
            ("Born", e(character.birth)),
            ("Died", e(character.death) if character.death else '<span class="tag">alive</span>'),
            ("Cause", e(character.death_reason.replace("death_", "").replace("_", " ")) if character.death_reason else ""),
            ("Sex", "female" if character.female else "male"),
            ("House", house_link(wiki, character.house, 1)),
            ("Parents", ", ".join(person_link(wiki, p, 1) for p in character.parents)),
            ("Dynasty", e(house.dynasty.display_name) if house and house.dynasty else ""),
            ("Id", f"<code>{character.id}</code>"),
            ("In saves", ", ".join(e(d) for d in character.seen)),
        ]
    )
    portrait = image_slot(
        shots[0] if shots else None, 1,
        f"Portrait of {character.name or character.id} in {shots[0].save_date}" if shots else "",
        shots[0].save_date if shots else "", have,
    )
    body = [f'<div class="page"><aside class="infobox card">{portrait}<table>{info}</table></aside>',
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

    if character.has_family:
        body.append("<h2>Family</h2>")
        body.append(
            "<table>"
            + people_row(wiki, "Parents", character.parents, 1)
            + people_row(wiki, "Siblings", character.siblings, 1)
            + people_row(wiki, "Spouses", character.spouses, 1)
            + people_row(wiki, "Former spouses", character.former_spouses, 1)
            + people_row(wiki, "Children", character.children, 1)
            + (people_row(wiki, "Real father", [character.real_father], 1)
               if character.real_father is not None else "")
            + "</table>"
        )
        body.append(
            '<p class="sub">A save records children, never parents, so parents are'
            " found by inverting: someone claimed this person as theirs. A name"
            " without a link is someone the wiki knows of but has no page for.</p>"
        )

    if len(shots) > 1:
        body.append("<h2>Portraits</h2>")
        body.append(
            f"<p>One per save this character appears in — the same person at"
            f" {len(shots)} ages, {shots[-1].save_date} to {shots[0].save_date}.</p>"
        )
        body.append('<div class="gallery">')
        for shot in reversed(shots):
            body.append(image_slot(
                shot, 1, f"Portrait of {character.name or character.id} in {shot.save_date}",
                shot.save_date, have,
            ))
        body.append("</div>")
    body.append("</div></div>")
    return page(
        character.name or f"Character {character.id}", "\n".join(body), depth=1,
        subtitle=character.lifespan, top=top,
    )


def render_house(wiki: Wiki, house: WikiHouse, have: set[str], top: bool = False) -> str:
    members = wiki.members_of(house.id)
    dynasty = house.dynasty
    info = rows(
        [
            ("Dynasty", e(dynasty.display_name) if dynasty and dynasty.display_name else ""),
            ("Head", character_link(wiki, house.head, 1) if house.head in wiki.characters else ""),
            ("Founded", e(house.house.founded)),
            ("Motto", f"<code>{e(house.house.motto)}</code>" if house.house.motto else ""),
            ("House id", f"<code>{house.id}</code>"),
            ("Dynasty id", f"<code>{dynasty.id}</code>" if dynasty else ""),
            ("Arms id", f"<code>{house.arms.coat_of_arms_id}</code>" if house.arms else ""),
            ("Members here", str(len(members))),
        ]
    )
    arms = image_slot(house.arms, 1, f"Arms of {house.name}", "coat of arms", have, kind="arms")
    body = [f'<div class="page"><aside class="infobox card">{arms}<table>{info}</table></aside>',
            '<div class="content">']
    body.append("<h2>Members</h2>")
    if members:
        lines = []
        for member in members:
            head = ' <span class="tag">head of house</span>' if house.head == member.id else ""
            lines.append(
                f"<tr><td>{character_link(wiki, member.id, 1)}{head}</td>"
                f'<td class="num">{e(member.lifespan)}</td>'
                f'<td class="num">{len(wiki.held_by(member.id))}</td></tr>'
            )
        body.append(
            "<table><thead><tr><th>Name</th><th class='num'>Lived</th>"
            f"<th class='num'>Reigns</th></tr></thead><tbody>{''.join(lines)}</tbody></table>"
        )
    else:
        body.append("<p>No member of this house appears in this wiki.</p>")
    body.append("</div></div>")
    subtitle = f"{len(members)} member{'s' if len(members) != 1 else ''} in this chronicle"
    return page(house.name, "\n".join(body), depth=1, subtitle=subtitle, top=top)


def render_index(wiki: Wiki, have: set[str] | None = None, top: bool = False) -> str:
    root = wiki.root
    have = have or set()
    images = [*wiki.wanted_portraits, *wiki.wanted_arms]
    missing = sum(1 for image in images if image.file not in have)
    body = []
    if root:
        body.append(
            f'<div class="card"><p>This chronicle follows <strong>{title_link(wiki, root.key, 0)}</strong>'
            f" and the titles held under it, across {len(wiki.snapshots)} save"
            f'{"s" if len(wiki.snapshots) != 1 else ""} of one playthrough:'
            f' {", ".join(e(d) for d in wiki.snapshots)}.</p>'
            f"<p>{len(wiki.titles)} titles, {len(wiki.characters)} characters and"
            f" {len(wiki.houses)} houses are recorded, with"
            f" {sum(len(t.tenures) for t in wiki.titles.values())} reigns between them.</p>"
            f"<p>{len(images)} images are linked — a portrait per character per save, and"
            f" a coat of arms per house. {missing} are still to be harvested; they are listed"
            f' in <a href="portraits.json"><code>portraits.json</code></a>.</p></div>'
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

    body.append("<h2>Characters</h2><table><thead><tr><th>Name</th><th>House</th>"
                "<th class='num'>Lived</th><th class='num'>Reigns</th></tr></thead><tbody>")
    for character in sorted(wiki.characters.values(), key=lambda c: (c.name or "", c.id)):
        body.append(
            f"<tr><td>{character_link(wiki, character.id, 0)}</td>"
            f"<td>{house_link(wiki, character.house, 0) or '—'}</td>"
            f'<td class="num">{e(character.lifespan)}</td>'
            f'<td class="num">{len(wiki.held_by(character.id))}</td></tr>'
        )
    body.append("</tbody></table>")

    if wiki.houses:
        body.append("<h2>Houses</h2><table><thead><tr><th>House</th><th>Dynasty</th>"
                    "<th class='num'>Founded</th><th class='num'>Members</th>"
                    "</tr></thead><tbody>")
        for house in sorted(wiki.houses.values(), key=lambda h: (h.name, h.id)):
            dynasty = house.dynasty.display_name if house.dynasty else ""
            body.append(
                f"<tr><td>{house_link(wiki, house.id, 0)}</td><td>{e(dynasty)}</td>"
                f'<td class="num">{e(house.house.founded) or "—"}</td>'
                f'<td class="num">{len(wiki.members_of(house.id))}</td></tr>'
            )
        body.append("</tbody></table>")
    return page("CK3 Chronicle", "\n".join(body), depth=0,
                subtitle=f"run {wiki.run_id}" if wiki.run_id else "", top=top)


def harvested(directory: Path | None) -> set[str]:
    """The image file names the companion has already delivered.

    Only names matter: the wiki derives every name it links, so this is purely
    the question of whether the file is here yet.
    """
    if directory is None or not directory.is_dir():
        return set()
    return {path.name for path in directory.iterdir() if path.is_file()}


def write_site(wiki: Wiki, out: Path, portraits: Path | None = None, top: bool = False) -> int:
    """Write the whole site. Returns the number of pages written."""
    for folder in ("titles", "characters", "houses"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    (out / "style.css").write_text(STYLE, encoding="utf-8")

    wanted = {image.file for image in (*wiki.wanted_portraits, *wiki.wanted_arms)}
    # only what this chronicle links: one directory can hold every run's images,
    # and copying all of them into each site would multiply them by the runs
    have = harvested(portraits) & wanted
    if have and portraits is not None:
        (out / IMAGE_DIR).mkdir(parents=True, exist_ok=True)
        for name in have:
            shutil.copyfile(portraits / name, out / IMAGE_DIR / name)

    pages = 1
    (out / "index.html").write_text(render_index(wiki, have, top), encoding="utf-8")
    for title in wiki.titles.values():
        (out / "titles" / f"{title.key}.html").write_text(render_title(wiki, title, top), encoding="utf-8")
        pages += 1
    for character in wiki.characters.values():
        (out / "characters" / f"{character.id}.html").write_text(
            render_character(wiki, character, have, top), encoding="utf-8"
        )
        pages += 1
    for house in wiki.houses.values():
        (out / "houses" / f"{house.id}.html").write_text(
            render_house(wiki, house, have, top), encoding="utf-8"
        )
        pages += 1
    return pages


def render_landing(entries: list[dict]) -> str:
    """The page above the wikis: one row per run.

    Runs are told apart by seed and game version, so that is what identifies a
    chronicle here, not the title it happens to be about.
    """
    body = [
        '<div class="card"><p>Each chronicle below is one playthrough, identified by'
        " its random seed and the game version it was started on. A run's saves are"
        " grouped automatically, so adding more saves to the Releases adds more"
        " chronicles here.</p></div>"
    ]
    body.append(
        "<h2>Chronicles</h2><table><thead><tr><th>Chronicle</th><th>Seed</th>"
        "<th>Version</th><th class='num'>Saves</th><th class='num'>Titles</th>"
        "<th class='num'>Characters</th><th class='num'>Houses</th>"
        "<th class='num'>Images</th></tr></thead><tbody>"
    )
    for entry in entries:
        images = entry.get("images") or {}
        wanted = images.get("wanted", 0)
        missing = images.get("missing", 0)
        tally = f'{wanted - missing} / {wanted}' if wanted else "—"
        body.append(
            f'<tr><td><a href="{e(entry["slug"])}/index.html">{e(entry["name"])}</a></td>'
            f'<td class="num"><code>{e(entry["seed"])}</code></td>'
            f'<td class="num">{e(entry["version"])}</td>'
            f'<td class="num">{entry["snapshots"]}</td>'
            f'<td class="num">{entry["titles"]}</td>'
            f'<td class="num">{entry["characters"]}</td>'
            f'<td class="num">{entry.get("houses", 0)}</td>'
            f'<td class="num">{tally}</td></tr>'
        )
    body.append("</tbody></table>")
    body.append(
        '<p class="sub">Images counts what has been harvested of what the wiki asks'
        " for. Portraits and coats of arms are captured from the running game by"
        ' <a href="https://github.com/diegoami/ck_portrait_generator">'
        "ck_portrait_generator</a>; every image wanted, the missing ones included, is"
        ' listed in <a href="portraits.json"><code>portraits.json</code></a> and in'
        " each chronicle's own copy.</p>"
    )
    return page("CK3 Chronicles", "\n".join(body), depth=0,
                subtitle=f"{len(entries)} playthrough{'s' if len(entries) != 1 else ''}")


def write_landing(out: Path, entries: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "style.css").write_text(STYLE, encoding="utf-8")
    (out / "index.html").write_text(render_landing(entries), encoding="utf-8")
