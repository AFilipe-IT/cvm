#!/usr/bin/env bash
#
# scripts/regen_canonical.sh — regenerate the canonical knowledge base from the
# working ccss.db.
#
# Run this after ANY build that writes rules (`caspar build`, `plugin add`,
# curated builds). The working DB is not what ships: Docker seeds its image and
# `caspar init` seeds a pip install from data/ccss_canonical.sql, so a rule that
# never reaches the dump reaches no user at all — the plugin code travels, its
# rules do not, and the target reports "0 rules · NOT ASSESSED" while the
# repository scores it normally. That divergence also changes the `kb sha256`,
# which is the line CVM prints to claim two results are comparable.
#
# Doing this by hand is what went wrong before: a plain `sqlite3 ccss.db .dump`
# also ships this machine's scan history and its runtime tables, and forgetting
# the caspar_meta stamp breaks the reseed path. Hence a script.
#
#   ./scripts/regen_canonical.sh [--version N]
#
set -euo pipefail

cd "$(dirname "$0")/.."

DB="${CASPAR_DB:-ccss.db}"
OUT="data/ccss_canonical.sql"
GZ="config_assessment/core/db/ccss_canonical.sql.gz"

# The version stamp drives the reseed of existing Docker volumes: bump it
# whenever the knowledge base changes in a way that must reach a volume that
# already exists. It has to match BASE_DB_VERSION in
# config_assessment/core/db/reseed.py — tests/test_reseed.py asserts exactly
# that, so a mismatch fails the suite rather than shipping quietly.
VERSION=""
if [ "${1:-}" = "--version" ]; then VERSION="${2:?--version needs a number}"; fi
if [ -z "$VERSION" ]; then
    VERSION=$(grep -oP '^BASE_DB_VERSION\s*=\s*\K\d+' \
              config_assessment/core/db/reseed.py)
fi

[ -f "$DB" ] || { echo "❌ $DB not found (set CASPAR_DB)" >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp "$DB" "$TMP/canon.db"

sqlite3 "$TMP/canon.db" <<SQL
-- Runtime state, created on demand by schema.sql on the first connection.
-- It is this machine's, not knowledge, and must not travel.
DROP TABLE IF EXISTS hosts;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS job_logs;
DROP TABLE IF EXISTS watch_heartbeats;
DROP TABLE IF EXISTS aegis_meta;
-- The schema travels, the rows do not: a fresh install must start with an
-- empty history, or the console shows scores to someone who never ran a scan.
DELETE FROM scan_results;
DELETE FROM sqlite_sequence WHERE name='scan_results';
CREATE TABLE IF NOT EXISTS caspar_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR REPLACE INTO caspar_meta VALUES('base_db_version','$VERSION');
VACUUM;
SQL

sqlite3 "$TMP/canon.db" .dump > "$OUT"
# The pip install has no repository, so it carries its own compressed copy.
# Regenerating one without the other is the drift tests/test_init_cmds.py
# checks for.
gzip -9 -c "$OUT" > "$GZ"

echo "✅ $OUT + $GZ regenerated (base_db_version=$VERSION)"
sqlite3 "$TMP/canon.db" \
  "SELECT '   ' || COUNT(*) || ' rules · ' ||
          (SELECT COUNT(*) FROM targets) || ' targets · ' ||
          (SELECT COUNT(*) FROM attack_chains) || ' chains'
   FROM misconfigurations;"
echo
echo "Now run:  pytest tests/test_reseed.py tests/test_init_cmds.py tests/test_doctor.py"
echo "and rebuild the images (caspar:latest first, then caspar:full)."
