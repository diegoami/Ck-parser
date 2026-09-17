#!/bin/bash
# Download the three sample saves (one CK3 run, three dates) from GitHub Releases.
# Usage: scripts/fetch_saves.sh [DEST_DIR]   (default: ./saves, git-ignored)
set -euo pipefail
dest="${1:-saves}"
mkdir -p "$dest"
base="https://github.com/diegoami/Ck-parser/releases/download"
while read -r tag name sha; do
  out="$dest/$name"
  if [ -f "$out" ] && echo "$sha  $out" | sha256sum -c --quiet 2>/dev/null; then
    echo "ok       $name"
    continue
  fi
  echo "fetching $name"
  curl -L --retry 3 -o "$out" "$base/$tag/$name"
  echo "$sha  $out" | sha256sum -c --quiet
done <<'LIST'
0.0.4 Fylkir_Asa_of_Immasonian_Fylkirate_1358_09_13.ck3 69b78aaefc04833079c61d7ac5e7faef18fb46906b82e6e71041661996558b57
0.0.3 Fylkir_Ludwig_of_Immasonian_Fylkirate_1361_01_17.ck3 a2b12bbb44e164537c8db7fe52c01b966665b2dc77a1634362c69191b892a37b
0.0.2 Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3 919ad2c7e541cf2f178d71250fefb37ca7f11a917f5df5e671f319322dba946a
LIST
echo "saves in $dest/"
