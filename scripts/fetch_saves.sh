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

# name<TAB>sha256<TAB>url<TAB>release tag, one per save, deduplicated by checksum.
# The release a save was published in is recorded because it is the batch the
# owner grouped it into, and because it is where the harvested images for that
# save belong. It is NOT how runs are grouped -- runs are decided by the save's
# own fingerprint, and one run already spans three releases.
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
        print(asset["name"], digest, asset["browser_download_url"],
              release.get("tag_name") or "", sep="\t")
'
)

if [ -z "$assets" ]; then
  echo "no .ck3 assets found on any release of $repo" >&2
  exit 1
fi

count=0
tags=""
while IFS=$'\t' read -r name digest url tag; do
  [ -z "$name" ] && continue
  out="$dest/$name"
  if [ -f "$out" ] && [ -n "$digest" ] && echo "$digest  $out" | sha256sum -c --quiet 2>/dev/null; then
    echo "ok       $name  [$tag]"
  else
    echo "fetching $name  [$tag]"
    curl -L --retry 3 --fail -o "$out" "$url"
    [ -n "$digest" ] && echo "$digest  $out" | sha256sum -c --quiet
  fi
  tags="$tags$name\t$tag\n"
  count=$((count + 1))
done <<< "$assets"

# Which release each save came from, for the manifest to pass on. Written even
# when empty, so a build can tell "no release information" from "not fetched".
printf '%b' "$tags" | python3 -c '
import json, sys
mapping = {}
for line in sys.stdin:
    name, _, tag = line.rstrip("\n").partition("\t")
    if name:
        mapping[name] = tag
print(json.dumps(mapping, indent=2, sort_keys=True))
' > "$dest/releases.json"

echo "$count save(s) in $dest/, release tags in $dest/releases.json"
