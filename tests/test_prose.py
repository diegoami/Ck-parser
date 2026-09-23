import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ck3wiki.build import main as build_main
from ck3wiki.model import build_wiki
from ck3wiki.prose import (
    OpenAICompatible,
    Prose,
    TemplateBackend,
    check,
    facts_digest,
    generate,
    load_prose,
    main as prose_main,
    page_facts,
    prose_path,
    read_prose,
    rulers,
    write_prose,
)
from helpers import SUCCESSION_EDITS, make_save
from test_wiki import views


def wiki_of(*saves):
    return build_wiki(views(*saves), "k_testland")


def test_the_fact_sheet_is_what_the_page_shows(tmp_path):
    wiki = wiki_of(make_save(tmp_path / "a.ck3"))
    facts = page_facts(wiki, "characters", "200")
    assert facts["name"] == "Test" and facts["house"]
    reign = next(r for r in facts["titles_held"] if r["title"] == wiki.titles["k_testland"].name)
    assert reign["from"] == "1090.2.1" and reign["still_holds"] and reign["to"] is None
    assert reign["predecessor"] == wiki.named(wiki.titles["k_testland"].tenures[-2].holder)
    assert [c["name"] for c in facts["children"]] == ["Child", "Sibling"]

    title = page_facts(wiki, "titles", "k_testland")
    assert [s["ruler"] for s in title["succession"]][-1] == "Test"
    assert page_facts(wiki, "characters", "999999") is None


def test_the_digest_moves_only_when_the_facts_do(tmp_path):
    early = make_save(tmp_path / "a_1100.ck3", date="1100.6.1", seed=7, random_count=100)
    late = make_save(
        tmp_path / "b_1120.ck3", date="1120.1.1", seed=7, random_count=200, edits=SUCCESSION_EDITS
    )
    once = facts_digest(page_facts(wiki_of(early), "characters", "200"))
    again = facts_digest(page_facts(wiki_of(early), "characters", "200"))
    later = facts_digest(page_facts(wiki_of(early, late), "characters", "200"))
    assert once == again
    # 200 lost the kingdom in the later save: the old paragraph would now be wrong
    assert later != once


def test_rulers_are_the_subject_title_and_its_holders_in_order(tmp_path):
    wiki = wiki_of(make_save(tmp_path / "a.ck3"))
    pages = rulers(wiki)
    assert pages[0] == ("titles", "k_testland")
    holders = [str(t.holder) for t in wiki.titles["k_testland"].tenures if t.holder in wiki.characters]
    assert [ident for kind, ident in pages[1:]] == list(dict.fromkeys(holders))


def test_a_number_the_facts_do_not_hold_is_caught(tmp_path):
    facts = page_facts(wiki_of(make_save(tmp_path / "a.ck3")), "characters", "200")
    assert check("Test took the throne on 1090.2.1.", facts) == []
    assert check("Test took the throne in 1091 and had 7 children.", facts) == [
        "numbers not in the facts: 7, 1091"
    ]
    assert check("   ", facts) == ["empty"]


class Inventing:
    name = "inventing"

    def write(self, facts, system, user):
        return f"{facts['name']} won a great battle in 1234."


def test_generate_writes_keeps_and_rejects(tmp_path):
    wiki = wiki_of(make_save(tmp_path / "a.ck3"))
    out = tmp_path / "prose"
    pages = rulers(wiki)
    first = generate(wiki, "run", pages, TemplateBackend(), out, log=open("/dev/null", "w"))
    assert first["written"] == len(pages) and first["rejected"] == 0
    saved = read_prose(prose_path(out, "run", "characters", "200"))
    assert saved.backend == "template" and "Test" in saved.text

    again = generate(wiki, "run", pages, TemplateBackend(), out, log=open("/dev/null", "w"))
    assert again["kept"] == len(pages) and again["written"] == 0

    bad = tmp_path / "bad"
    counts = generate(wiki, "run", pages, Inventing(), bad, log=open("/dev/null", "w"))
    # never saved: a page without prose beats one saying what the save does not
    assert counts["rejected"] == len(pages) and not bad.exists()


def test_stale_prose_is_left_out_of_the_page(tmp_path):
    wiki = wiki_of(make_save(tmp_path / "a.ck3"))
    out = tmp_path / "prose"
    generate(wiki, "run", rulers(wiki), TemplateBackend(), out, log=open("/dev/null", "w"))
    write_prose(prose_path(out, "run", "titles", "k_testland"),
                Prose(text="Written from other facts.", facts="0" * 16, backend="template"))
    found, stale = load_prose(out, "run", wiki)
    assert ("characters", "200") in found
    assert ("titles", "k_testland") not in found and stale == 1


def test_the_build_folds_prose_in_and_says_where_it_came_from(tmp_path):
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3")
    prose, site, cache = tmp_path / "prose", tmp_path / "site", tmp_path / "cache"
    assert prose_main([str(saves), "--title", "k_testland", "--out", str(prose),
                       "--cache", str(cache)]) == 0
    assert build_main([str(saves), "--title", "k_testland", "--out", str(site),
                       "--cache", str(cache), "--prose", str(prose)]) == 0
    slug = next(p.name for p in prose.iterdir())
    page = (site / slug / "characters" / "200.html").read_text()
    assert '<section class="prose">' in page and "Written by <code>template</code>" in page
    # a page nobody wrote prose for is built exactly as before
    assert '<section class="prose">' not in (site / slug / "characters" / "202.html").read_text()


def test_the_openai_backend_speaks_plain_http_and_drops_the_thinking(tmp_path):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {"choices": [{"message": {"content": "<think>scratch</think>\nThe entry."}}]}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = OpenAICompatible(f"http://127.0.0.1:{server.server_port}/v1", "some-model")
        text = backend.write({}, "system words", "user words")
    finally:
        server.shutdown()
    assert text == "The entry."
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["model"] == "some-model"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert backend.name == "openai:some-model"


def test_the_openai_backend_needs_a_model(tmp_path, capsys):
    assert prose_main([str(tmp_path), "--backend", "openai"]) == 2
    assert "--model is required" in capsys.readouterr().err


def _serve(status, reply):
    """A one-route stand-in for an OpenAI-compatible server, on a free port."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_openai_backend_adds_up_the_tokens_it_was_billed():
    server = _serve(200, {"choices": [{"message": {"content": "An entry."}}],
                          "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
    try:
        backend = OpenAICompatible(f"http://127.0.0.1:{server.server_port}/v1", "m")
        backend.write({}, "s", "u")
        backend.write({}, "s", "u")
    finally:
        server.shutdown()
    assert backend.usage == {"prompt_tokens": 240, "completion_tokens": 60}


def test_a_refused_key_stops_the_run_with_the_servers_reason(tmp_path, monkeypatch, capsys):
    server = _serve(401, {"error": {"message": "invalid api key"}})
    saves = tmp_path / "saves"
    saves.mkdir()
    make_save(saves / "a.ck3")
    # the settings come from the environment, as `uv run --env-file .env` gives them
    monkeypatch.setenv("CK3_PROSE_BACKEND", "openai")
    monkeypatch.setenv("CK3_PROSE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("CK3_PROSE_MODEL", "m")
    monkeypatch.setenv("CK3_PROSE_API_KEY", "not-a-real-key")
    try:
        status = prose_main([str(saves), "--title", "k_testland", "--out", str(tmp_path / "prose"),
                             "--cache", str(tmp_path / "cache")])
    finally:
        server.shutdown()
    err = capsys.readouterr().err
    assert status == 2
    assert "HTTP 401" in err and "invalid api key" in err
    assert "not-a-real-key" not in err  # the key is never echoed
    assert not (tmp_path / "prose").exists()
