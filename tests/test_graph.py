import pytest

from ck3graph.loader import DryRunSession, Neo4jConfig, apply_schema, clean_title_name, holder_intervals, load_snapshot, load_title, schema_statements
from ck3parser.fingerprint import fingerprint
from ck3parser.parser import Block, parse_text
from helpers import fixture_text, make_save


def test_config_from_env():
    cfg = Neo4jConfig.from_env({"NEO4J_URI": "bolt://x:7687", "NEO4J_USER": "u", "NEO4J_PASSWORD": "p"})
    assert cfg.uri == "bolt://x:7687" and cfg.database is None
    with pytest.raises(RuntimeError):
        Neo4jConfig.from_env({})


def test_schema_has_constraints():
    stmts = schema_statements()
    assert len(stmts) == 6 and all(s.startswith("CREATE CONSTRAINT") for s in stmts)
    s = DryRunSession(echo=False)
    apply_schema(s)
    assert len(s.statements) == 6


def test_holder_intervals_from_fixture_history():
    top = parse_text(fixture_text())
    hist = top["landed_titles"]["landed_titles"]["0"]["history"]
    ivs = holder_intervals(hist, end_date="1100.6.1")
    assert ivs == [
        {"holder": 100, "from": "867.1.1", "to": "880.5.5", "open": False},
        {"holder": 101, "from": "880.5.5", "to": "900.1.1", "open": False},
        {"holder": 102, "from": "950.3.3", "to": "1090.2.1", "open": False},
        {"holder": 200, "from": "1090.2.1", "to": "1100.6.1", "open": True},
    ]
    assert holder_intervals(None, "1100.6.1", current_holder=5) == [{"holder": 5, "from": None, "to": "1100.6.1", "open": True}]


def test_clean_title_name():
    assert clean_title_name("e_germania") == "Germania"
    assert clean_title_name("k_papal_state") == "Papal State"


def test_load_writes_merges_only(tmp_path):
    p = make_save(tmp_path / "a.ck3")
    fp = fingerprint(p, with_sha256=False)
    top = parse_text(fixture_text())
    title = top["landed_titles"]["landed_titles"]["0"]
    chars = {200: top["living"]["200"], 100: top["dead_unprunable"]["100"]}
    s = DryRunSession(echo=False)
    load_snapshot(s, fp)
    load_title(s, fp, title, holder_intervals(title["history"], fp.date), chars)
    queries = [q for q, _ in s.statements]
    assert all("MERGE" in q and "DELETE" not in q for q in queries)
    held = [params for q, params in s.statements if "HELD_BY" in q]
    assert [h["holder"] for h in held] == [100, 101, 102, 200]
    char_writes = [params for q, params in s.statements if "MERGE (c:Character {id: $id})" in q]
    assert {c["props"]["death"] for c in char_writes} == {None, "880.5.5"}
