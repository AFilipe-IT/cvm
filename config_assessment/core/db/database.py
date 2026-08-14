"""
core/db/database.py
-------------------
Database access layer.

Wraps SQLite (development) with a thin abstraction that makes migration
to PostgreSQL straightforward in production.

Public surface area is intentionally minimal:
  - Database(path)               — open/create database
  - db.upsert_target(meta)       — register a target
  - db.upsert_misconfiguration(m)— write one finding (upsert)
  - db.upsert_attack_chain(c)    — write one chain (upsert)
  - db.get_misconfigurations(…)  — O(1) lookup by (target, directive, value)
  - db.get_attack_chains(…)      — get all chains for a target
  - db.save_scan_result(result)  — persist a completed ScanResult
  - db.close()                   — close connection

All reads return fully-typed Pydantic models (Misconfiguration, AttackChain,
ScanResult).  The caller never touches raw SQL rows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from config_assessment.core.models import (
    AttackChain,
    Misconfiguration,
    ScanResult,
    TargetMetadata,
)

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """
    Thin typed wrapper around a SQLite connection.

    Usage::

        db = Database("ccss.db")
        misconfigs = db.get_misconfigurations("apache-httpd", "ServerTokens", "Full")
        db.close()

    Or as a context manager::

        with Database("ccss.db") as db:
            ...
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        # check_same_thread=False: o FastAPI resolve as dependências (get_db, que
        # abre esta ligação) e corre os handlers síncronos em threads distintas
        # do mesmo pool do anyio. Com a verificação ligada, o handler recebia
        # "SQLite objects created in a thread can only be used in that same
        # thread" — e de forma intermitente, porque o pool às vezes reutiliza a
        # mesma thread e o pedido passa. O `watch` tem o mesmo padrão: o loop
        # corre numa thread própria.
        #
        # O que a flag desliga é só a verificação de thread. NÃO torna uma
        # ligação partilhável por threads a correr em paralelo: fazê-lo dá
        # "InterfaceError: bad parameter or other API misuse" (verificado em
        # tests/test_api.py::TestDatabaseIsUsableAcrossThreads). É seguro aqui
        # porque cada ligação tem um só dono de cada vez — get_db abre uma por
        # pedido e fecha-a no fim, e o job_runner/watch_runner abrem a sua
        # dentro de cada thread. Ao mudar este ficheiro, mantenha essa
        # propriedade: uma Database por pedido/por thread, nunca uma global.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Enable WAL for better concurrent read performance
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Enforce FK constraints
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._migrate()

    @property
    def path(self) -> str:
        """Filesystem path of this database (":memory:" when in-memory)."""
        return self._path

    @property
    def conn(self) -> sqlite3.Connection:
        """The underlying connection (e.g. for manifest.build_manifest)."""
        return self._conn

    # ------------------------------------------------------------------ #
    # Context manager support                                              #
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "Database":
        self._migrate()
        return self


    def update_narrative(
        self,
        directive: str,
        bad_value: str,
        target_name: str,
        narrative: dict,
    ) -> None:
        """Update the narrative JSON for a misconfiguration (Stage 3)."""
        import json as _json
        self._conn.execute(
            """UPDATE misconfigurations
               SET narrative = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE target_name = ? AND directive = ? AND bad_value = ?""",
            (_json.dumps(narrative, ensure_ascii=False), target_name, directive, bad_value),
        )
        self._conn.commit()

    def get_narrative(self, target_name: str, directive: str, bad_value: str) -> dict:
        """Retrieve narrative JSON for a misconfiguration."""
        import json as _json
        cur = self._conn.execute(
            "SELECT narrative FROM misconfigurations "
            "WHERE target_name = ? AND directive = ? AND bad_value = ?",
            (target_name, directive, bad_value),
        )
        row = cur.fetchone()
        if row and row[0]:
            try:
                return _json.loads(row[0])
            except Exception:
                pass
        return {}

    def _migrate(self) -> None:
        """Apply schema migrations to existing databases (idempotent)."""
        import logging
        _log = logging.getLogger(__name__)

        # Simple ADD COLUMN migrations (idempotent: SQLite raises on duplicate column)
        simple_migrations = [
            ("narrative",
             "ALTER TABLE misconfigurations ADD COLUMN narrative TEXT NOT NULL DEFAULT '{}'"),
            ("rule_type",
             "ALTER TABLE misconfigurations ADD COLUMN rule_type TEXT NOT NULL DEFAULT 'value'"),
            ("required_when",
             "ALTER TABLE misconfigurations ADD COLUMN required_when TEXT NOT NULL DEFAULT 'always'"),
            ("confidence",
             "ALTER TABLE misconfigurations ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"),
            ("host_id",
             "ALTER TABLE scan_results ADD COLUMN host_id INTEGER REFERENCES hosts(id)"),
            ("watch_session",
             "ALTER TABLE scan_results ADD COLUMN watch_session TEXT"),
            ("watch_interval",
             "ALTER TABLE scan_results ADD COLUMN watch_interval REAL"),
            # As bases já existentes têm scans gravados sem manifesto: ficam com
            # '{}' e é o valor honesto — foram produzidos por código que não o
            # gravava, e não há como reconstruir a posteriori o sha256 da base
            # nessa altura. Os scans novos passam a trazê-lo.
            ("manifest_json",
             "ALTER TABLE scan_results ADD COLUMN manifest_json TEXT NOT NULL DEFAULT '{}'"),
            # Cadeias já gravadas vieram todas do pipeline de build, por isso
            # 'generated' é o valor honesto para o histórico: nesta altura não
            # havia forma de escrever uma cadeia à mão.
            ("provenance",
             "ALTER TABLE attack_chains ADD COLUMN provenance TEXT NOT NULL DEFAULT 'generated'"),
            ("author",
             "ALTER TABLE attack_chains ADD COLUMN author TEXT NOT NULL DEFAULT ''"),
        ]
        for col_name, sql in simple_migrations:
            try:
                self._conn.execute(sql)
                self._conn.commit()
                _log.info("Migration applied: added column '%s'", col_name)
            except Exception:
                pass  # Column already exists — safe to ignore

        self._migrate_host_identity()

        # Table-recreation migration: add expected_value_prefix + widen UNIQUE constraint.
        # Cannot use ALTER TABLE ADD COLUMN because the UNIQUE constraint must change.
        existing_cols = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(misconfigurations)"
        ).fetchall()}
        if "expected_value_prefix" in existing_cols:
            return  # Already migrated — idempotent

        _log.info("Migration: adding expected_value_prefix (table recreation)")
        before = self._conn.execute(
            "SELECT COUNT(*) FROM misconfigurations"
        ).fetchone()[0]

        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute("""
                CREATE TABLE misconfigurations_new (
                    id               TEXT    PRIMARY KEY,
                    target_id        INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                    target_name      TEXT    NOT NULL,
                    directive        TEXT    NOT NULL,
                    bad_value        TEXT    NOT NULL,
                    good_value       TEXT    NOT NULL DEFAULT '',
                    av               TEXT    NOT NULL DEFAULT 'N',
                    au               TEXT    NOT NULL DEFAULT 'N',
                    ac               TEXT    NOT NULL,
                    c                TEXT    NOT NULL,
                    i                TEXT    NOT NULL,
                    a                TEXT    NOT NULL,
                    base_score       REAL    NOT NULL DEFAULT 0.0,
                    temporal_score   REAL    NOT NULL DEFAULT 0.0,
                    gel              TEXT    NOT NULL DEFAULT 'ND',
                    grl              TEXT    NOT NULL DEFAULT 'ND',
                    cves             TEXT    NOT NULL DEFAULT '[]',
                    cce_id           TEXT    NOT NULL DEFAULT '',
                    cis_section      TEXT    NOT NULL DEFAULT '',
                    justification    TEXT    NOT NULL DEFAULT '',
                    recommendation   TEXT    NOT NULL DEFAULT '',
                    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    narrative        TEXT    NOT NULL DEFAULT '{}',
                    rule_type        TEXT    NOT NULL DEFAULT 'value',
                    required_when    TEXT    NOT NULL DEFAULT 'always',
                    expected_value_prefix TEXT NOT NULL DEFAULT '',
                    confidence       REAL    NOT NULL DEFAULT 1.0,
                    UNIQUE (target_name, directive, bad_value, expected_value_prefix)
                )
            """)
            has_confidence = "confidence" in existing_cols
            confidence_select = "confidence" if has_confidence else "1.0"
            self._conn.execute(f"""
                INSERT INTO misconfigurations_new
                    SELECT id, target_id, target_name,
                           directive, bad_value, good_value,
                           av, au, ac, c, i, a,
                           base_score, temporal_score,
                           gel, grl, cves, cce_id, cis_section,
                           justification, recommendation,
                           created_at, updated_at,
                           narrative, rule_type, required_when,
                           '', {confidence_select}
                    FROM misconfigurations
            """)
            after = self._conn.execute(
                "SELECT COUNT(*) FROM misconfigurations_new"
            ).fetchone()[0]
            if before != after:
                self._conn.execute("DROP TABLE IF EXISTS misconfigurations_new")
                self._conn.rollback()
                raise RuntimeError(
                    f"Migration aborted: {before} rows before, {after} after — "
                    "original table unchanged."
                )
            self._conn.execute("DROP TABLE misconfigurations")
            self._conn.execute(
                "ALTER TABLE misconfigurations_new RENAME TO misconfigurations"
            )
            self._conn.execute(
                "CREATE INDEX idx_misconf_lookup "
                "ON misconfigurations (target_name, directive, bad_value)"
            )
            self._conn.execute(
                "CREATE INDEX idx_misconf_target ON misconfigurations (target_name)"
            )
            self._conn.commit()
            _log.info(
                "Migration applied: expected_value_prefix added (%d rows preserved)", after
            )
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    def _migrate_host_identity(self) -> None:
        """Give every host a stable UUID (v2 inventory).

        Until v2 a host was identified by its label, which is exactly the
        attribute that changes when a machine is renamed — the history would
        split in two without anything signalling it. The UUID is assigned once
        and never changes; label, hostname and ip_address become attributes.

        Rows that predate this migration get a UUID generated now. That is a
        new identity, not a recovered one: there is no way to reconstruct what
        a pre-v2 host's UUID "would have been". The scans already attached to
        it keep pointing at the same row id, so no history is lost.
        """
        import logging
        import uuid as _uuid
        _log = logging.getLogger(__name__)

        cols = {r[1] for r in
                self._conn.execute("PRAGMA table_info(hosts)").fetchall()}
        if not cols:
            return  # No hosts table yet — schema.sql creates it with uuid.

        # SQLite cannot ADD COLUMN with UNIQUE, so the column goes in plain and
        # the uniqueness comes from an index created after backfilling.
        new_cols = [
            ("uuid", "ALTER TABLE hosts ADD COLUMN uuid TEXT"),
            ("hostname", "ALTER TABLE hosts ADD COLUMN hostname TEXT"),
            ("ip_address", "ALTER TABLE hosts ADD COLUMN ip_address TEXT"),
            ("os_family", "ALTER TABLE hosts ADD COLUMN os_family TEXT"),
            ("os_version", "ALTER TABLE hosts ADD COLUMN os_version TEXT"),
            ("kernel", "ALTER TABLE hosts ADD COLUMN kernel TEXT"),
            ("last_seen_at", "ALTER TABLE hosts ADD COLUMN last_seen_at TEXT"),
        ]
        added = False
        for name, sql in new_cols:
            if name in cols:
                continue
            self._conn.execute(sql)
            added = True
        if added:
            self._conn.commit()
            _log.info("Migration applied: hosts gained v2 identity columns")

        missing = self._conn.execute(
            "SELECT id FROM hosts WHERE uuid IS NULL OR uuid = ''"
        ).fetchall()
        for row in missing:
            self._conn.execute(
                "UPDATE hosts SET uuid = ? WHERE id = ?",
                (str(_uuid.uuid4()), row["id"]),
            )
        if missing:
            self._conn.commit()
            _log.info("Migration: assigned a UUID to %d existing host(s)",
                      len(missing))

        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_hosts_uuid ON hosts (uuid)")
        self._conn.commit()

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ #
    # Schema init                                                          #
    # ------------------------------------------------------------------ #

    def _init_schema(self) -> None:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()
        logger.debug("Schema initialised at %s", self._path)

    # ------------------------------------------------------------------ #
    # targets                                                              #
    # ------------------------------------------------------------------ #

    def upsert_target(self, meta: TargetMetadata) -> int:
        """Insert or update a target row.  Returns the target's row id."""
        cur = self._conn.execute(
            """
            INSERT INTO targets (name, display_name, version, benchmark_source)
            VALUES (:name, :display_name, :version, :benchmark_source)
            ON CONFLICT(name) DO UPDATE SET
                display_name     = excluded.display_name,
                version          = excluded.version,
                benchmark_source = excluded.benchmark_source,
                updated_at       = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING id
            """,
            {
                "name": meta.name,
                "display_name": meta.display_name,
                "version": meta.version,
                "benchmark_source": meta.benchmark_source,
            },
        )
        row = cur.fetchone()
        self._conn.commit()
        return row["id"]

    def get_target_names(self) -> list[str]:
        """Names of every target with rules in this DB (sorted)."""
        rows = self._conn.execute("SELECT name FROM targets ORDER BY name")
        return [r["name"] for r in rows.fetchall()]

    def get_target_id(self, target_name: str) -> int | None:
        cur = self._conn.execute(
            "SELECT id FROM targets WHERE name = ?", (target_name,)
        )
        row = cur.fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------ #
    # hosts (Operating System instances)                                   #
    # ------------------------------------------------------------------ #

    def upsert_host(self, label: str) -> int:
        """Insert or fetch a host by label. Returns the host's row id.

        A first registration mints a UUID; a repeat call only bumps
        updated_at, so the identity assigned the first time survives every
        later scan under the same label.
        """
        import uuid as _uuid
        cur = self._conn.execute(
            """
            INSERT INTO hosts (label, uuid) VALUES (:label, :uuid)
            ON CONFLICT(label) DO UPDATE SET
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING id
            """,
            {"label": label, "uuid": str(_uuid.uuid4())},
        )
        row = cur.fetchone()
        self._conn.commit()
        return row["id"]

    def get_host(self, host_id: int) -> dict | None:
        """One host with every attribute, or None if the id is unknown."""
        cur = self._conn.execute("SELECT * FROM hosts WHERE id = ?", (host_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_host_by_uuid(self, host_uuid: str) -> dict | None:
        """Resolve a host by its stable identity rather than by any attribute.

        This is the lookup that survives a rename: a machine re-registering
        after its label changed is still found here.
        """
        cur = self._conn.execute(
            "SELECT * FROM hosts WHERE uuid = ?", (host_uuid,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update_host_attributes(self, host_id: int, **attrs: str | None) -> None:
        """Record what a host currently looks like.

        Only hostname, ip_address, os_family, os_version and kernel are
        writable — the UUID is identity and is never updated, and the label is
        the operator's handle, changed deliberately via `rename_host`.

        A None value CLEARS the attribute, and that is deliberate: `collect()`
        returns None for anything it could not observe, so a collection that
        stops being able to see a field must retract it rather than leave a
        stale value standing. Attributes not passed at all are left untouched,
        which is how a caller updates one field without disturbing the rest.
        """
        allowed = {"hostname", "ip_address", "os_family", "os_version", "kernel"}
        fields = {k: v for k, v in attrs.items() if k in allowed}
        if not fields:
            return

        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self._conn.execute(
            f"UPDATE hosts SET {sets}, "
            "last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE id = :host_id",
            {**fields, "host_id": host_id},
        )
        self._conn.commit()

    def rename_host(self, host_id: int, new_label: str) -> None:
        """Change a host's operator-facing label, keeping its identity.

        The scans already attributed to it stay attributed: they reference the
        row, not the name. That is the whole point of the UUID.
        """
        self._conn.execute(
            "UPDATE hosts SET label = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (new_label, host_id),
        )
        self._conn.commit()

    def get_host_id(self, label: str) -> int | None:
        cur = self._conn.execute("SELECT id FROM hosts WHERE label = ?", (label,))
        row = cur.fetchone()
        return row["id"] if row else None

    def get_host_label(self, host_id: int) -> str | None:
        cur = self._conn.execute("SELECT label FROM hosts WHERE id = ?", (host_id,))
        row = cur.fetchone()
        return row["label"] if row else None

    def list_hosts(self) -> list[dict]:
        """Every registered host (id, label, created_at, updated_at), sorted by label."""
        rows = self._conn.execute("SELECT * FROM hosts ORDER BY label")
        return [dict(r) for r in rows.fetchall()]

    def get_scans_for_host(self, host_id: int, limit: int = 500) -> list[dict]:
        """Scan summary rows (same shape as list_scans) for one host, newest first."""
        sql = (
            "SELECT id, target_name, input_path, global_base_score, "
            "global_temporal_score, severity, total_directives, "
            "total_issues, total_chains, host_id, timestamp FROM scan_results "
            "WHERE host_id = ? ORDER BY timestamp DESC LIMIT ?"
        )
        return [dict(r) for r in self._conn.execute(sql, (host_id, limit)).fetchall()]

    # ------------------------------------------------------------------ #
    # misconfigurations                                                    #
    # ------------------------------------------------------------------ #

    def upsert_misconfiguration(self, m: Misconfiguration) -> None:
        """Insert or update a single misconfiguration."""
        target_id = self.get_target_id(m.target_name)
        if target_id is None:
            raise ValueError(
                f"Target '{m.target_name}' not found in DB. "
                "Call upsert_target() first."
            )
        self._conn.execute(
            """
            INSERT INTO misconfigurations (
                id, target_id, target_name,
                directive, bad_value, good_value,
                av, au, ac, c, i, a,
                base_score, temporal_score,
                gel, grl, cves, cce_id, cis_section,
                justification, recommendation,
                rule_type, required_when, expected_value_prefix, confidence
            ) VALUES (
                :id, :target_id, :target_name,
                :directive, :bad_value, :good_value,
                :av, :au, :ac, :c, :i, :a,
                :base_score, :temporal_score,
                :gel, :grl, :cves, :cce_id, :cis_section,
                :justification, :recommendation,
                :rule_type, :required_when, :expected_value_prefix, :confidence
            )
            ON CONFLICT(target_name, directive, bad_value, expected_value_prefix) DO UPDATE SET
                good_value            = excluded.good_value,
                av                    = excluded.av,
                au                    = excluded.au,
                ac                    = excluded.ac,
                c                     = excluded.c,
                i                     = excluded.i,
                a                     = excluded.a,
                base_score            = excluded.base_score,
                temporal_score        = excluded.temporal_score,
                gel                   = excluded.gel,
                grl                   = excluded.grl,
                cves                  = excluded.cves,
                cce_id                = excluded.cce_id,
                cis_section           = excluded.cis_section,
                justification         = excluded.justification,
                recommendation        = excluded.recommendation,
                rule_type             = excluded.rule_type,
                required_when         = excluded.required_when,
                expected_value_prefix = excluded.expected_value_prefix,
                confidence            = excluded.confidence,
                updated_at            = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            {
                "id": m.id,
                "target_id": target_id,
                "target_name": m.target_name,
                "directive": m.directive,
                "bad_value": m.bad_value,
                "good_value": m.good_value,
                "av": m.av,
                "au": m.au,
                "ac": m.ac,
                "c": m.c,
                "i": m.i,
                "a": m.a,
                "base_score": m.base_score,
                "temporal_score": m.temporal_score,
                "gel": m.gel,
                "grl": m.grl,
                "cves": json.dumps(m.cves),
                "cce_id": m.cce_id,
                "cis_section": m.cis_section,
                "justification": m.justification,
                "recommendation": m.recommendation,
                "rule_type": m.rule_type,
                "required_when": m.required_when,
                "expected_value_prefix": m.expected_value_prefix,
                "confidence": m.confidence,
            },
        )
        self._conn.commit()

    def delete_misconfigurations_not_in(
        self,
        target_name: str,
        keep_pairs: list,
    ) -> int:
        """
        Delete misconfigurations for *target_name* whose identity key is NOT
        in *keep_pairs*.

        Each element of *keep_pairs* must be a 3-tuple:
            (directive, bad_value, expected_value_prefix)

        This matches the 4-column UNIQUE constraint
        (target_name, directive, bad_value, expected_value_prefix).
        Using only (directive, bad_value) would incorrectly collapse multiple
        absence rules for the same directive (e.g. several add_header rules
        that share bad_value='' but differ in expected_value_prefix).

        Makes the build idempotent: rebuilding with a smaller ENTRIES list
        removes orphaned entries without touching the narrative column.

        Returns the number of rows deleted.
        """
        existing = self.get_all_misconfigurations(target_name)
        keep = {(d, v, p) for d, v, p in keep_pairs}
        to_delete = [
            (m.directive, m.bad_value, m.expected_value_prefix)
            for m in existing
            if (m.directive, m.bad_value, m.expected_value_prefix) not in keep
        ]
        for directive, bad_value, prefix in to_delete:
            self._conn.execute(
                "DELETE FROM misconfigurations "
                "WHERE target_name = ? AND directive = ? AND bad_value = ? "
                "AND expected_value_prefix = ?",
                (target_name, directive, bad_value, prefix),
            )
        self._conn.commit()
        return len(to_delete)

    def get_misconfigurations(
        self,
        target_name: str,
        directive: str,
        bad_value: str,
    ) -> list[Misconfiguration]:
        """
        Lookup misconfigurations by (target_name, directive, bad_value).

        This is the hot path in runtime.  The indexed query is O(1).
        Returns an empty list when nothing matches (not an error).
        """
        cur = self._conn.execute(
            """
            SELECT * FROM misconfigurations
            WHERE target_name = ? AND directive = ? AND bad_value = ?
            """,
            (target_name, directive, bad_value),
        )
        rows = cur.fetchall()
        return [self._row_to_misconfiguration(r) for r in rows]

    def get_value_rules(
        self,
        target_name: str,
        directive: str,
    ) -> list[Misconfiguration]:
        """
        Return all value-rules for a (target, directive), regardless of bad_value.

        Used by the runtime to match list-valued directives (e.g.
        ``ssl_protocols SSLv3 TLSv1 TLSv1.1``) where a single config line carries
        several bad_value tokens stored as separate rules. The exact-match
        get_misconfigurations stays the O(1) hot path; this is the fallback the
        runtime uses to test token-subset membership.
        """
        cur = self._conn.execute(
            """
            SELECT * FROM misconfigurations
            WHERE target_name = ? AND directive = ? AND rule_type = 'value'
            """,
            (target_name, directive),
        )
        return [self._row_to_misconfiguration(r) for r in cur.fetchall()]

    def get_absence_rules(self, target_name: str) -> list[Misconfiguration]:
        """Return all absence rules for a target (rule_type = 'absence')."""
        cur = self._conn.execute(
            "SELECT * FROM misconfigurations WHERE target_name = ? AND rule_type = 'absence'",
            (target_name,),
        )
        return [self._row_to_misconfiguration(r) for r in cur.fetchall()]

    def get_all_misconfigurations(self, target_name: str) -> list[Misconfiguration]:
        """Return every misconfiguration for a target (used by the build validator)."""
        cur = self._conn.execute(
            "SELECT * FROM misconfigurations WHERE target_name = ?",
            (target_name,),
        )
        return [self._row_to_misconfiguration(r) for r in cur.fetchall()]

    @staticmethod
    def _row_to_misconfiguration(row: sqlite3.Row) -> Misconfiguration:
        return Misconfiguration(
            id=row["id"],
            target_name=row["target_name"],
            directive=row["directive"],
            bad_value=row["bad_value"],
            good_value=row["good_value"],
            av=row["av"],
            au=row["au"],
            ac=row["ac"],
            c=row["c"],
            i=row["i"],
            a=row["a"],
            base_score=row["base_score"],
            temporal_score=row["temporal_score"],
            gel=row["gel"],
            grl=row["grl"],
            cves=json.loads(row["cves"]),
            cce_id=row["cce_id"],
            cis_section=row["cis_section"],
            justification=row["justification"],
            recommendation=row["recommendation"],
            narrative=row["narrative"] if "narrative" in row.keys() else "{}",
            rule_type=row["rule_type"] if "rule_type" in row.keys() else "value",
            required_when=row["required_when"] if "required_when" in row.keys() else "always",
            expected_value_prefix=row["expected_value_prefix"] if "expected_value_prefix" in row.keys() else "",
            confidence=row["confidence"] if "confidence" in row.keys() else 1.0,
        )

    # ------------------------------------------------------------------ #
    # attack_chains                                                        #
    # ------------------------------------------------------------------ #

    def upsert_attack_chain(self, chain: AttackChain) -> None:
        target_id = self.get_target_id(chain.target_name)
        if target_id is None:
            raise ValueError(f"Target '{chain.target_name}' not found in DB.")
        self._conn.execute(
            """
            INSERT INTO attack_chains (
                target_id, target_name, chain_id,
                misconfig_directives, amplification,
                justification, cross_target, provenance, author
            ) VALUES (
                :target_id, :target_name, :chain_id,
                :misconfig_directives, :amplification,
                :justification, :cross_target, :provenance, :author
            )
            ON CONFLICT(target_name, chain_id) DO UPDATE SET
                misconfig_directives = excluded.misconfig_directives,
                amplification        = excluded.amplification,
                justification        = excluded.justification,
                cross_target         = excluded.cross_target,
                provenance           = excluded.provenance,
                author               = excluded.author
            """,
            {
                "target_id": target_id,
                "target_name": chain.target_name,
                "chain_id": chain.chain_id,
                "misconfig_directives": json.dumps(chain.misconfig_directives),
                "amplification": chain.amplification,
                "justification": chain.justification,
                "cross_target": int(chain.cross_target),
                "provenance": chain.provenance,
                "author": chain.author,
            },
        )
        self._conn.commit()

    def get_attack_chains(self, target_name: str) -> list[AttackChain]:
        cur = self._conn.execute(
            "SELECT * FROM attack_chains WHERE target_name = ?",
            (target_name,),
        )
        return [self._row_to_chain(r) for r in cur.fetchall()]

    def delete_attack_chain(self, target_name: str, chain_id: str) -> bool:
        """Remove one chain definition. True when a row was actually deleted.

        The counterpart to writing a chain by hand: a mistaken one must be
        retractable without editing the database directly. Scans already stored
        keep the chain they fired at the time — this removes the definition, not
        the history of it having matched.
        """
        cur = self._conn.execute(
            "DELETE FROM attack_chains WHERE target_name = ? AND chain_id = ?",
            (target_name, chain_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row_to_chain(row: sqlite3.Row) -> AttackChain:
        keys = row.keys()
        return AttackChain(
            chain_id=row["chain_id"],
            target_name=row["target_name"],
            misconfig_directives=json.loads(row["misconfig_directives"]),
            amplification=row["amplification"],
            justification=row["justification"],
            cross_target=bool(row["cross_target"]),
            # Read defensively: a database written before these columns existed
            # is migrated on open, but a row read through a connection that has
            # not been (a raw sqlite3 handle in a test, say) must still load.
            provenance=(
                row["provenance"] if "provenance" in keys else "generated"
            ),
            author=row["author"] if "author" in keys else "",
        )

    # ------------------------------------------------------------------ #
    # version_exploits — pre-fetched version exploitability (F1)            #
    # ------------------------------------------------------------------ #

    def upsert_version_exploits(
        self, product: str, version: str, *,
        cve_count: int, kev_count: int, max_cvss: float,
        cve_ids: list, exploits: list,
    ) -> None:
        """Insert or replace the pre-fetched exploitability for a version."""
        self._conn.execute(
            """
            INSERT INTO version_exploits
                (product, version, cve_count, kev_count, max_cvss,
                 cve_ids, exploits, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(product, version) DO UPDATE SET
                cve_count  = excluded.cve_count,
                kev_count  = excluded.kev_count,
                max_cvss   = excluded.max_cvss,
                cve_ids    = excluded.cve_ids,
                exploits   = excluded.exploits,
                fetched_at = excluded.fetched_at
            """,
            (product, version, cve_count, kev_count, max_cvss,
             json.dumps(cve_ids), json.dumps(exploits)),
        )
        self._conn.commit()

    def get_version_exploits(self, product: str, version: str) -> dict | None:
        """Return the pre-fetched exploitability for a version, or None."""
        cur = self._conn.execute(
            "SELECT * FROM version_exploits WHERE product = ? AND version = ?",
            (product, version),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "product": row["product"],
            "version": row["version"],
            "cve_count": row["cve_count"],
            "kev_count": row["kev_count"],
            "max_cvss": row["max_cvss"],
            "cve_ids": json.loads(row["cve_ids"]),
            "exploits": json.loads(row["exploits"]),
            "fetched_at": row["fetched_at"],
        }

    # ------------------------------------------------------------------ #
    # scan_results                                                         #
    # ------------------------------------------------------------------ #

    def save_scan_result(
        self,
        result: ScanResult,
        host_id: int | None = None,
        watch_session: str | None = None,
        watch_interval: float | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO scan_results (
                id, target_name, input_path, input_hash,
                profile_av, profile_au,
                global_base_score, global_temporal_score, severity,
                total_directives, total_issues, total_chains,
                issues_json, chains_json, manifest_json, host_id,
                watch_session, watch_interval
            ) VALUES (
                :id, :target_name, :input_path, :input_hash,
                :profile_av, :profile_au,
                :global_base_score, :global_temporal_score, :severity,
                :total_directives, :total_issues, :total_chains,
                :issues_json, :chains_json, :manifest_json, :host_id,
                :watch_session, :watch_interval
            )
            """,
            {
                "id": result.scan_id,
                "target_name": result.target_name,
                "input_path": result.input_path,
                "input_hash": result.input_hash,
                "profile_av": result.profile.av,
                "profile_au": result.profile.au,
                "global_base_score": result.global_base_score,
                "global_temporal_score": result.global_temporal_score,
                "severity": result.severity,
                "total_directives": result.total_directives_scanned,
                "total_issues": result.total_issues_found,
                "total_chains": result.total_chains_detected,
                "issues_json": json.dumps([i.model_dump() for i in result.issues], default=str),
                "chains_json": json.dumps([c.model_dump() for c in result.chains], default=str),
                "manifest_json": json.dumps(result.manifest, default=str),
                "host_id": host_id,
                "watch_session": watch_session,
                "watch_interval": watch_interval,
            },
        )
        self._conn.commit()

    @staticmethod
    def _manifest_of(row) -> dict:
        """O manifesto gravado, ou `{}` para os scans anteriores à coluna.

        Defensivo de propósito: uma base por migrar não tem a coluna, e um scan
        antigo tem-na vazia. Nos dois casos a resposta certa é "não há
        manifesto" — nunca inventar um, que é o que tornaria a auditoria
        impossível sem se dar por isso.
        """
        try:
            raw = row["manifest_json"]
        except (IndexError, KeyError):
            return {}
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    def get_scan_result(self, scan_id: str) -> ScanResult | None:
        cur = self._conn.execute(
            "SELECT * FROM scan_results WHERE id = ?", (scan_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return ScanResult(
            scan_id=row["id"],
            target_name=row["target_name"],
            input_path=row["input_path"],
            input_hash=row["input_hash"],
            profile={"av": row["profile_av"], "au": row["profile_au"]},
            global_base_score=row["global_base_score"],
            global_temporal_score=row["global_temporal_score"],
            severity=row["severity"],
            total_directives_scanned=row["total_directives"],
            total_issues_found=row["total_issues"],
            total_chains_detected=row["total_chains"],
            issues=json.loads(row["issues_json"]),
            chains=json.loads(row["chains_json"]),
            manifest=self._manifest_of(row),
        )

    def get_scan_history(self, input_path: str | None = None,
                         limit: int = 10) -> list[dict]:
        """Recent scans (most recent first) for score trending. Optionally
        filtered to one input_path. Returns lightweight dicts, not full
        ScanResults — history only needs score/severity/when."""
        sql = ("SELECT timestamp, input_path, global_temporal_score, severity, "
               "total_issues, host_id FROM scan_results ")
        params: tuple = ()
        if input_path:
            sql += "WHERE input_path = ? "
            params = (input_path,)
        sql += "ORDER BY timestamp DESC LIMIT ?"
        params = params + (limit,)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ #
    # watch sessions (caspar watch, persisted for live dashboard viewing)  #
    # ------------------------------------------------------------------ #

    def touch_watch_heartbeat(self, watch_session: str) -> None:
        """Record that a watch session's poll loop is still running, whether
        or not this tick found a content change. Called once per poll tick
        (every `--interval` seconds) — this is what lets a quiet, unchanged
        config still read as "live" instead of going stale after one missed
        scan_results row (which only ever appends on a real change)."""
        self._conn.execute(
            """
            INSERT INTO watch_heartbeats (watch_session, last_seen)
            VALUES (:session, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(watch_session) DO UPDATE SET
                last_seen = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            {"session": watch_session},
        )
        self._conn.commit()

    def get_active_watches(self, limit: int = 50) -> list[dict]:
        """One row per distinct watch_session — its latest scan summary plus
        the session's last heartbeat (for liveness — see touch_watch_heartbeat)."""
        # Timestamp alone can tie (millisecond resolution, fast polling), so
        # rowid — monotonically increasing with insertion order — breaks ties
        # and guarantees "latest" means the most recently inserted row.
        sql = """
            SELECT scan_results.target_name, scan_results.input_path,
                   scan_results.host_id, scan_results.global_temporal_score,
                   scan_results.severity, scan_results.total_issues,
                   scan_results.total_chains, scan_results.watch_session,
                   scan_results.watch_interval, scan_results.timestamp,
                   h.last_seen
            FROM scan_results
            LEFT JOIN watch_heartbeats AS h
                ON h.watch_session = scan_results.watch_session
            WHERE scan_results.watch_session IS NOT NULL
              AND scan_results.rowid = (
                  SELECT MAX(rowid) FROM scan_results AS s2
                  WHERE s2.watch_session = scan_results.watch_session
              )
            ORDER BY timestamp DESC
            LIMIT ?
        """
        return [dict(r) for r in self._conn.execute(sql, (limit,)).fetchall()]

    def get_watch_events(self, watch_session: str, limit: int = 200) -> list[dict]:
        """Full event history for one watch session, newest first."""
        # O `id` vai junto: cada evento é um scan completo guardado, e sem a
        # chave o painel só conseguia mostrar o score global. Com ela, abrir um
        # evento leva às directivas concretas que o produziram (GET /scans/{id}).
        sql = (
            "SELECT id AS scan_id, timestamp, target_name, input_path, "
            "global_temporal_score, severity, total_issues, total_chains, "
            "watch_interval "
            "FROM scan_results WHERE watch_session = ? "
            "ORDER BY rowid DESC LIMIT ?"
        )
        return [dict(r) for r in self._conn.execute(sql, (watch_session, limit)).fetchall()]

    def get_watch_heartbeat(self, watch_session: str) -> str | None:
        """Last poll-tick timestamp recorded for a session, or None if it
        never sent one (e.g. a session persisted before this table existed)."""
        row = self._conn.execute(
            "SELECT last_seen FROM watch_heartbeats WHERE watch_session = ?",
            (watch_session,),
        ).fetchone()
        return row["last_seen"] if row else None

    def delete_watch_session(self, watch_session: str) -> int:
        """Apagar uma sessão de watch: os seus eventos e o batimento.

        Uma sessão vive em duas tabelas — as leituras em `scan_results` e a
        marca de vida em `watch_heartbeats`. Apagar só uma delas deixava a
        sessão meio existente: sem histórico mas ainda listada, ou o inverso.

        Devolve o número de eventos removidos.
        """
        cur = self._conn.execute(
            "DELETE FROM scan_results WHERE watch_session = ?", (watch_session,))
        removed = cur.rowcount
        self._conn.execute(
            "DELETE FROM watch_heartbeats WHERE watch_session = ?", (watch_session,))
        self._conn.commit()
        return removed

    def delete_stale_watch_sessions(self, keep: set[str] | None = None) -> int:
        """Apagar todas as sessões de watch excepto as indicadas em *keep*.

        Serve a limpeza em lote da consola: uma máquina de testes acumula
        dezenas de sessões paradas e a lista deixa de ser navegável. As
        sessões vivas são protegidas pelo chamador, que é quem sabe quais
        estão a correr neste processo.

        Devolve o número de sessões removidas.
        """
        keep = keep or set()
        rows = self._conn.execute(
            "SELECT DISTINCT watch_session FROM scan_results "
            "WHERE watch_session IS NOT NULL").fetchall()
        targets = [r[0] for r in rows if r[0] not in keep]
        for session in targets:
            self.delete_watch_session(session)
        return len(targets)

    def delete_scan_result(self, scan_id: str) -> bool:
        """Remove a persisted scan record. Returns True if a row was deleted."""
        cur = self._conn.execute("DELETE FROM scan_results WHERE id = ?", (scan_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _scan_filter_sql(target_name: str | None, input_path: str | None,
                         severity_min: float | None,
                         host_id: int | None) -> tuple[str, list]:
        """The WHERE clause shared by `list_scans` and `count_scans`.

        Written once because the two must agree: a count computed over
        different filters than the page it describes would report a total the
        reader can never reach by paging.

        Returns the clause with a trailing space (or empty) and its parameters,
        so callers can append ORDER BY / LIMIT directly.
        """
        clauses: list[str] = []
        params: list = []
        if target_name:
            clauses.append("target_name = ?")
            params.append(target_name)
        if input_path:
            clauses.append("input_path = ?")
            params.append(input_path)
        if severity_min is not None:
            clauses.append("global_temporal_score >= ?")
            params.append(severity_min)
        if host_id is not None:
            clauses.append("host_id = ?")
            params.append(host_id)
        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses) + " ", params

    def count_scans(self, target_name: str | None = None,
                    input_path: str | None = None,
                    severity_min: float | None = None,
                    host_id: int | None = None) -> int:
        """How many scans match the filters, ignoring limit/offset.

        A paged consumer cannot derive this from the page it holds: a full page
        means "there may be more", and there is no way to tell the last page
        from a boundary hit without asking. Exposed as a header on GET /scans.
        """
        where, params = self._scan_filter_sql(
            target_name, input_path, severity_min, host_id)
        row = self._conn.execute(
            "SELECT COUNT(*) FROM scan_results " + where, params).fetchone()
        return int(row[0]) if row else 0

    def list_scans(self, target_name: str | None = None,
                   input_path: str | None = None,
                   severity_min: float | None = None,
                   host_id: int | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
        """Paginated scan listing (id + summary fields), newest first — the
        REST API's GET /scans. Filterable by target, input_path, host, and a
        minimum global_temporal_score threshold.

        Each row also carries `rules_for_target`, read out of the stored
        manifest. Without it a scan of a target whose knowledge base is empty is
        indistinguishable from a clean one — both are score 0.0, severity None,
        0 issues — and a consumer would render the strongest possible all-clear
        for a system nothing ever assessed. The CLI already refuses to do that;
        this is the same signal, made available to every other consumer.
        """
        sql = ("SELECT id, target_name, input_path, global_base_score, "
               "global_temporal_score, severity, total_directives, "
               "total_issues, total_chains, host_id, timestamp, manifest_json "
               "FROM scan_results ")
        where, params = self._scan_filter_sql(
            target_name, input_path, severity_min, host_id)
        sql += where + "ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params = [*params, limit, offset]

        import json as _json
        rows = []
        for r in self._conn.execute(sql, params).fetchall():
            row = dict(r)
            # manifest_json itself stays out of the response: it is a large blob
            # whose other fields (kb hash, versions) belong to GET /scans/{id}.
            # Only the one field a summary consumer cannot do without is lifted.
            raw = row.pop("manifest_json", None)
            try:
                row["rules_for_target"] = (_json.loads(raw) or {}).get(
                    "rules_for_target") if raw else None
            except (ValueError, TypeError):
                # A malformed manifest must not take the listing down. None
                # means "unknown", which callers already treat as assessed —
                # the same reading as a pre-manifest scan.
                row["rules_for_target"] = None
            rows.append(row)
        return rows

    # ------------------------------------------------------------------ #
    # Background jobs (REST API build/plugin_add) — Phase 2                #
    # ------------------------------------------------------------------ #

    def create_job(self, job_id: str, kind: str, params: dict) -> None:
        import json as _json
        self._conn.execute(
            "INSERT INTO jobs (id, kind, status, params_json) VALUES (?, ?, 'queued', ?)",
            (job_id, kind, _json.dumps(params, ensure_ascii=False)),
        )
        self._conn.commit()

    def mark_job_started(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = 'running', "
            "started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (job_id,),
        )
        self._conn.commit()

    def finish_job(self, job_id: str, status: str, result: dict | None = None,
                    error: str | None = None) -> None:
        """status is 'succeeded', 'failed', or 'cancelled'."""
        import json as _json
        self._conn.execute(
            "UPDATE jobs SET status = ?, result_json = ?, error = ?, "
            "finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (status, _json.dumps(result, ensure_ascii=False) if result is not None else None,
             error, job_id),
        )
        self._conn.commit()

    def append_job_log(self, job_id: str, line: str) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM job_logs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        seq = row[0]
        self._conn.execute(
            "INSERT INTO job_logs (job_id, seq, line) VALUES (?, ?, ?)",
            (job_id, seq, line),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM jobs "
        params: list = []
        if kind:
            sql += "WHERE kind = ? "
            params.append(kind)
        sql += "ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_job_logs(self, job_id: str, after: int = -1) -> list[dict]:
        """Lines with seq > after, so a poller need not re-ship the whole log."""
        return [dict(r) for r in self._conn.execute(
            "SELECT seq, ts, line FROM job_logs WHERE job_id = ? AND seq > ? ORDER BY seq",
            (job_id, after),
        ).fetchall()]

    def get_running_jobs(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchall()]
