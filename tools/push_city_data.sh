#!/bin/sh
# Push the built city (data/, git-ignored on main) to the orphan branch `city-data` on GitHub, in batches so no
# single push is too large. Uses a temporary index, so main's index and working tree are untouched.
# The new city-data commit chain starts from the current remote city-data tip (history kept).
# usage: sh tools/push_city_data.sh [batch_size]
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
B="${1:-6000}"
export GIT_INDEX_FILE="$(mktemp -u /tmp/citydata_index.XXXX)"
git fetch -q origin city-data || true
PARENT="$(git rev-parse -q --verify origin/city-data || true)"
[ -n "$PARENT" ] && git read-tree "$PARENT" || git read-tree --empty
# drop files that no longer exist in data/
git ls-files data | while read f; do [ -e "$f" ] || echo "$f"; done | git update-index --force-remove --stdin
find data -path data/aerial -prune -o -type f -print | sort > /tmp/citydata_files.txt
N=$(wc -l < /tmp/citydata_files.txt); i=0
MSG_TAIL="Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011Bwej3HJhEZdbminfnQFYa"
while [ $i -lt $N ]; do
  sed -n "$((i + 1)),$((i + B))p" /tmp/citydata_files.txt | git update-index --add --stdin
  TREE=$(git write-tree)
  if [ -n "$PARENT" ] && [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ]; then i=$((i + B)); continue; fi
  C=$(printf "City data rebuild: files %d-%d of %d\n\n%s\n" $((i + 1)) $((i + B)) $N "$MSG_TAIL" | \
      git -c commit.gpgsign=false commit-tree "$TREE" ${PARENT:+-p "$PARENT"})
  git push -q origin "$C:refs/heads/city-data"
  PARENT=$C; i=$((i + B))
  echo "pushed $i / $N"
done
rm -f "$GIT_INDEX_FILE"
echo "city-data at $(git rev-parse --short "$PARENT")"
