// Unique ids per node type. Apply once per database (idempotent).
CREATE CONSTRAINT character_id IF NOT EXISTS FOR (c:Character) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT title_key   IF NOT EXISTS FOR (t:Title)     REQUIRE t.key IS UNIQUE;
CREATE CONSTRAINT dynasty_id  IF NOT EXISTS FOR (d:Dynasty)   REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT house_id    IF NOT EXISTS FOR (h:House)     REQUIRE h.id IS UNIQUE;
CREATE CONSTRAINT run_id      IF NOT EXISTS FOR (r:Run)       REQUIRE r.run_id IS UNIQUE;
CREATE CONSTRAINT snapshot_id IF NOT EXISTS FOR (s:Snapshot)  REQUIRE (s.run_id, s.date) IS UNIQUE;
