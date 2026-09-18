#!/bin/bash
# Download every .ck3 save attached to this repository's Releases.
#
# The saves are not in git (they are tens of megabytes each), so this is how a
# checkout gets them. Every release is read, not a fixed list, so attaching a
# save from a new playthrough is all it takes to add a chronicle to the wiki.
# Files that appear in more than one release are fetched once, and every
# download is checked against the sha256 the API reports.
#
# Usage: scripts/fetch_saves.sh [DEST_DIR]   (default: ./saves, git-ignored)
set -euo pipefail

dest="${1:-saves}"
# Never inferred from GITHUB_REPOSITORY: the wiki is built from another
# repository's workflow, where that variable names *that* repository and the
# saves are not there. Override with SAVES_REPO if they ever move.
repo="${SAVES_REPO:-diegoami/Ck-parser}"
mkdir -p "$dest"

auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")

# name<TAB>sha256<TAB>url, one per save, deduplicated by checksum.
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
        if not asset["name"].endswith(".ck3"):
            continue
        digest = (asset.get("digest") or "").removeprefix("sha256:")
        key = digest or asset["name"]
        if key in seen:
            continue
        seen.add(key)
        print(asset["name"], digest, asset["browser_download_url"], sep="\t")
'
)

if [ -z "$assets" ]; then
  echo "no .ck3 assets found on any release of $repo" >&2
  exit 1
fi

count=0
while IFS=$'\t' read -r name digest url; do
  [ -z "$name" ] && continue
  out="$dest/$name"
  if [ -f "$out" ] && [ -n "$digest" ] && echo "$digest  $out" | sha256sum -c --quiet 2>/dev/null; then
    echo "ok       $name"
  else
    echo "fetching $name"
    curl -L --retry 3 --fail -o "$out" "$url"
    [ -n "$digest" ] && echo "$digest  $out" | sha256sum -c --quiet
  fi
  count=$((count + 1))
done <<< "$assets"

echo "$count save(s) in $dest/"
