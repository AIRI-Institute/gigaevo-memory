"""Tests for the Postgres backup script (P2 §7, iter #38).

Tests run the script in ``--dry-run`` mode (prints the commands it
would execute, without actually invoking docker / pg_dump / aws cli).
That lets us assert:

  * The script is on disk and executable.
  * `--help` returns 0 and prints usage information.
  * Defaults produce sensible pg_dump + filesystem commands.
  * Env-var overrides (``BACKUP_DIR`` / ``POSTGRES_USER`` / ``POSTGRES_DB`` /
    ``COMPOSE_FILE``) propagate into the printed command.
  * ``S3_BUCKET`` triggers the ``aws s3 cp`` upload line; its absence
    prints the explicit "skipping S3 upload" message.
  * The dump filename includes a UTC ISO-style timestamp (so two
    concurrent backups never collide).

No real DB / Docker / AWS is touched.
"""

from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess

SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "deploy" / "scripts" / "backup.sh"
)


def _run(env: dict | None = None, args: tuple[str, ...] = ("--dry-run",)) -> tuple[int, str, str]:
    """Invoke the script and return (returncode, stdout, stderr)."""
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = subprocess.run(
        [str(SCRIPT), *args],
        env=proc_env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Existence + help
# ---------------------------------------------------------------------------


class TestScriptOnDisk:
    def test_script_exists(self):
        assert SCRIPT.exists(), f"missing: {SCRIPT}"

    def test_script_is_executable(self):
        mode = SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "owner cannot execute"
        assert mode & stat.S_IXGRP, "group cannot execute"
        assert mode & stat.S_IXOTH, "other cannot execute"

    def test_help_returns_zero_with_usage(self):
        rc, out, _ = _run(args=("--help",))
        assert rc == 0
        assert "Usage:" in out
        assert "BACKUP_DIR" in out
        assert "S3_BUCKET" in out

    def test_unknown_flag_returns_2(self):
        rc, _, err = _run(args=("--bogus",))
        assert rc == 2
        assert "unknown flag" in err


# ---------------------------------------------------------------------------
# Dry-run output: pg_dump invocation
# ---------------------------------------------------------------------------


class TestDryRunPgDump:
    def test_default_dump_command_shape(self):
        rc, out, _ = _run(
            env={
                "BACKUP_DIR": "./backups",
                "POSTGRES_USER": "memory",
                "POSTGRES_DB": "memory",
            }
        )
        assert rc == 0
        # The line that *would* run for the dump:
        assert "would run: docker compose" in out
        assert "exec -T postgres pg_dump -U memory -d memory" in out
        assert "| gzip > ./backups/gigaevo-memory-" in out

    def test_custom_db_user_propagates(self):
        rc, out, _ = _run(
            env={"POSTGRES_USER": "alice", "POSTGRES_DB": "alice_db"}
        )
        assert rc == 0
        assert "pg_dump -U alice -d alice_db" in out

    def test_custom_backup_dir(self):
        rc, out, _ = _run(env={"BACKUP_DIR": "/var/lib/gigaevo/backups"})
        assert rc == 0
        assert "would mkdir -p /var/lib/gigaevo/backups" in out
        assert "/var/lib/gigaevo/backups/gigaevo-memory-" in out

    def test_compose_file_override(self):
        rc, out, _ = _run(env={"COMPOSE_FILE": "deploy/staging.yml"})
        assert rc == 0
        assert "-f deploy/staging.yml" in out

    def test_compose_project_override(self):
        rc, out, _ = _run(env={"COMPOSE_PROJECT": "gigaevo-staging"})
        assert rc == 0
        assert "-p gigaevo-staging" in out


# ---------------------------------------------------------------------------
# Dry-run output: S3 upload branch
# ---------------------------------------------------------------------------


class TestDryRunS3Upload:
    def test_no_s3_bucket_skips_upload(self):
        rc, out, _ = _run(env={"S3_BUCKET": ""})
        assert rc == 0
        assert "skipping S3 upload" in out
        assert "aws s3 cp" not in out

    def test_s3_bucket_triggers_upload_command(self):
        rc, out, _ = _run(env={"S3_BUCKET": "my-bucket"})
        assert rc == 0
        assert "would run: aws s3 cp" in out
        assert "s3://my-bucket/gigaevo-memory/backups/gigaevo-memory-" in out

    def test_s3_prefix_override(self):
        rc, out, _ = _run(
            env={
                "S3_BUCKET": "my-bucket",
                "S3_PREFIX": "prod/db-dumps",
            }
        )
        assert rc == 0
        assert "s3://my-bucket/prod/db-dumps/gigaevo-memory-" in out


# ---------------------------------------------------------------------------
# Filename pattern
# ---------------------------------------------------------------------------


class TestFilenamePattern:
    def test_dump_filename_includes_utc_timestamp(self):
        """Filename pattern: gigaevo-memory-YYYYMMDD-HHMMSSZ.sql.gz"""
        rc, out, _ = _run()
        assert rc == 0
        m = re.search(
            r"gigaevo-memory-(\d{8}-\d{6}Z)\.sql\.gz",
            out,
        )
        assert m is not None, f"filename pattern not found in:\n{out}"
        # YYYYMMDD-HHMMSSZ → 8 digits, dash, 6 digits, Z
        assert re.fullmatch(r"\d{8}-\d{6}Z", m.group(1))

    def test_filename_has_seconds_precision(self):
        """Filename includes 6 seconds-digits so any non-zero gap
        between two backups yields distinct paths and concurrent
        runs can't clobber each other."""
        _, out, _ = _run()
        m = re.search(r"gigaevo-memory-\d{8}-(\d{6})Z", out)
        assert m is not None
        assert len(m.group(1)) == 6


# ---------------------------------------------------------------------------
# Sanity: the script doesn't actually run anything in --dry-run
# ---------------------------------------------------------------------------


class TestDryRunHasNoSideEffects:
    def test_dry_run_does_not_create_backup_dir(self, tmp_path):
        target = tmp_path / "nonexistent-backups"
        rc, out, _ = _run(env={"BACKUP_DIR": str(target)})
        assert rc == 0
        assert "would mkdir" in out
        assert not target.exists(), "dry-run must not mkdir"

    def test_dry_run_prints_would_run_for_every_action(self):
        rc, out, _ = _run(env={"S3_BUCKET": "test-bucket"})
        assert rc == 0
        # mkdir + dump + upload = at least 3 "would" lines.
        would_lines = [line for line in out.splitlines() if line.startswith("would ")]
        assert len(would_lines) >= 3
