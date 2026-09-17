"""ck3parser: read Crusader Kings 3 save files.

Modules
-------
container   .ck3 container: plaintext header + zipped ``gamestate``.
parser      streaming Clausewitz-script tokenizer/parser.
filter      referenced-vs-filler character heuristic.
fingerprint cheap per-file run fingerprint (header + first KB of gamestate).
runs        group snapshots into runs, order and verify them, manifest + CLI.
pipeline    traced extract -> parse -> filter -> load run for one title.
"""
