"""
cli/commands/init_cmds.py — `caspar init`: create the working database.

A `pip install cvm-caspar` has no repository, so `data/ccss_canonical.sql` —
the file every other installation restores the DB from — is out of reach.
Without it the CLI installs and runs but cannot assess anything: `caspar scan`
stops at "DB 'ccss.db' not found" and points at `caspar build --benchmark`,
which means an LLM extraction of an hour or more to rebuild knowledge that
already exists and is already validated.

So the canonical dump travels inside the wheel (gzipped, ~133 KB against 674 KB
plain) and this command restores it. It is the pip-install counterpart of what
install-native.sh does with `sqlite3 ccss.db < data/ccss_canonical.sql` and what
the Docker entrypoint does with the baked seed DB — same knowledge base, same
sha256, so scores stay comparable across the three installations.

Refusing to overwrite by default is the important part: the working DB
accumulates scan history and user-installed plugins, none of which is in the
dump. `--force` is the way to say that losing them is intended.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

import click


def canonical_dump() -> Path:
    """The gzipped canonical SQL dump shipped inside the package.

    Kept next to the db package rather than at the repository root: the wheel
    has no repository root, and `importlib.resources`-style co-location is what
    makes the file addressable in both a source tree and an installed package.
    """
    return Path(__file__).resolve().parents[2] / "config_assessment" / "core" / "db" / "ccss_canonical.sql.gz"


def restore_from_dump(db_path: Path, dump: Path) -> int:
    """Restore `db_path` from the gzipped SQL `dump`. Returns rows in the KB.

    Written to a temporary file first and moved into place only on success, so
    an interrupted restore cannot leave a half-populated database that later
    scans would silently read as if it were complete.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False,
                                     dir=str(db_path.parent)) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with gzip.open(dump, "rt", encoding="utf-8") as fh:
            sql = fh.read()
        conn = sqlite3.connect(str(tmp_path))
        try:
            conn.executescript(sql)
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM misconfigurations").fetchone()[0]
        finally:
            conn.close()
        shutil.move(str(tmp_path), str(db_path))
        return int(count)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


@click.command("init")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite an existing database (loses scan history and "
                   "user-installed plugins).")
@click.pass_context
def init(ctx: click.Context, force: bool) -> None:
    """Create the working database from the built-in knowledge base.

    Run this once after `pip install cvm-caspar`. Other installations do it for
    you: install-native.sh restores the same dump, and the Docker image seeds
    from a baked copy on first run.
    """
    db_path = Path(ctx.obj["db_path"])
    dump = canonical_dump()

    if not dump.is_file():
        click.echo(
            click.style("The built-in knowledge base is missing from this "
                        "installation.\n", fg="red") +
            f"Expected: {dump}\n"
            "A wheel built without it cannot initialise a database. Reinstall "
            "from PyPI, or use the repository's data/ccss_canonical.sql.",
            err=True)
        ctx.exit(2)

    if db_path.exists() and not force:
        click.echo(
            click.style(f"'{db_path}' already exists — not touching it.\n",
                        fg="yellow") +
            "It holds your scan history and any plugins you installed, none of\n"
            "which is in the built-in dump. To replace it anyway: " +
            click.style("caspar init --force", bold=True),
            err=True)
        ctx.exit(1)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    count = restore_from_dump(db_path, dump)

    click.echo(click.style(f"✅ Database ready: {db_path}", fg="green"))
    click.echo(click.style(f"   {count} misconfigurations in the knowledge base",
                           dim=True))
    click.echo()
    click.echo("Next: " + click.style("caspar targets", bold=True) +
               "   (list what can be assessed)")
    click.echo("      " + click.style("caspar demo", bold=True) +
               "      (write example configurations to scan)")
