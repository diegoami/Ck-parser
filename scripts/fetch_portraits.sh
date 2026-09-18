#!/bin/bash
# Download every harvested image attached to this repository's Releases.
#
# This is the delivery channel for `diegoami/ck_portrait_generator`: it
# harvests the images the wiki asks for in portraits.json and attaches them to a
# Release, either loose as .png or bundled in a .zip, and the next Pages build
# folds them in. Names are the ones both projects derive (src/ck3parser/
# portraits.py) and are never rewritten here.
#
# Missing images are not an error: the wiki links them either way, and a slot
# with no file renders as "awaiting harvest".
#
# Usage: scripts/fetch_portraits.sh [DEST_DIR]   (default: ./portraits)
set -euo pipefail

dest="${1:-portraits}"
repo="${GITHUB_REPOSITORY:-diegoami/Ck-parser}"
mkdir -p "$dest"

auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")

# name<TAB>url for every image or image bundle, deduplicated by name.
assets=$(
  curl -sS --retry 3 "${auth[@]}" \
    "https://api.github.com/repos/$repo/releases?per_page=100" |
  python3 -c '
import json, sys
seen = set()
for release in json.load(sys.stdin):
    if release.get("draft"):
        continue
    for asset in release.get("assets", []):
        name = asset["name"]
        if not name.endswith((".png", ".zip")) or name in seen:
            continue
        seen.add(name)
        print(name, asset["browser_download_url"], sep="\t")
'
)

if [ -z "$assets" ]; then
  echo "no harvested images on any release of $repo yet" >&2
  exit 0
fi

count=0
while IFS=$'\t' read -r name url; do
  [ -z "$name" ] && continue
  case "$name" in
    *.zip)
      tmp=$(mktemp)
      curl -L --retry 3 --fail -o "$tmp" "$url"
      # -j: the manifest names files, never directories, so any structure the
      # bundle happens to have is flattened away.
      unzip -j -o -q "$tmp" '*.png' -d "$dest"
      rm -f "$tmp"
      ;;
    *)
      [ -f "$dest/$name" ] || curl -L --retry 3 --fail -o "$dest/$name" "$url"
      ;;
  esac
  count=$((count + 1))
done <<< "$assets"

echo "$count asset(s) fetched; $(find "$dest" -name '*.png' | wc -l) image(s) in $dest/"
