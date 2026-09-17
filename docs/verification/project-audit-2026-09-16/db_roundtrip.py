"""Migrate/seed/dump/restore only fresh audit-owned PostgreSQL databases."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


async def main():
    cfg = dotenv_values(ROOT / ".env")
    base = URL.create("postgresql", username=cfg["POSTGRES_USER"],
                      password=cfg["POSTGRES_PASSWORD"], host=cfg["POSTGRES_HOST"],
                      port=int(cfg["POSTGRES_PORT"]), database="postgres")
    admin = await asyncpg.connect(base.render_as_string(hide_password=False))
    names = ["aml_audit_" + uuid4().hex for _ in range(2)]
    created = []
    env = dict(os.environ, PYTHONUTF8="1", PGHOST=str(base.host),
               PGPORT=str(base.port), PGUSER=str(base.username),
               PGPASSWORD=str(base.password),
               BOOTSTRAP_ADMIN_EMAIL="audit@example.com",
               BOOTSTRAP_ADMIN_PASSWORD=uuid4().hex)
    report = {"databases": names, "seed_runs": []}
    tools = ROOT / ".local-run/postgresql/pgsql/bin"

    def run(args):
        proc = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True,
                              encoding="utf-8", timeout=90)
        if proc.returncode:
            raise RuntimeError(f"{Path(args[0]).name} failed, exit {proc.returncode}")
        return proc.stdout.strip()

    async def state(name):
        conn = await asyncpg.connect(base.set(database=name).render_as_string(hide_password=False))
        try:
            tables = [row[0] for row in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            counts = {table: await conn.fetchval(f'SELECT count(*) FROM "{table}"') for table in tables}
            snapshot = await conn.fetchval("SELECT game_config::text FROM rounds")
            return {"counts": counts, "snapshot": json.loads(snapshot),
                    "migration": await conn.fetchval("SELECT version_num FROM alembic_version")}
        finally:
            await conn.close()

    try:
        for name in names:
            assert name.startswith("aml_audit_") and len(name) == 42
            await admin.execute(f'CREATE DATABASE "{name}"')
            created.append(name)
        env["DATABASE_URL"] = base.set(drivername="postgresql+asyncpg", database=names[0]).render_as_string(hide_password=False)
        for _ in range(2):
            report["seed_runs"].append(run([sys.executable, "-m", "scripts.seed_database", "--migrate"]))
        original = await state(names[0])
        with tempfile.TemporaryDirectory(prefix="aml-audit-backup-") as tmp:
            archive = str(Path(tmp) / "database.dump")
            run([str(tools / "pg_dump.exe"), "-Fc", "-d", names[0], "-f", archive])
            run([str(tools / "pg_restore.exe"), "--no-owner", "--no-privileges", "-d", names[1], archive])
            restored = await state(names[1])
        assert original == restored
        assert report["seed_runs"][0] == report["seed_runs"][1]
        report.update(passed=True, migration=original["migration"], counts=original["counts"],
                      snapshot_equal=True, repeat_seed_idempotent=True)
    finally:
        for name in created:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
    report["temporary_databases_removed"] = True
    (OUT / "db-roundtrip.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
