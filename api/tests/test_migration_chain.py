"""Static migration-chain integrity gate (P2 §7, iter #36).

Validates the Alembic revision graph **without touching a database**:

* Every migration module under ``app/db/migrations/versions/`` declares
  a ``revision`` string and a ``down_revision`` pointing at its parent
  (or ``None`` for the root).
* No duplicate revision IDs.
* No orphan revisions (every revision except the root has a parent that
  also exists in the directory).
* Exactly one root (``down_revision is None``) and one head (no other
  revision points to it).
* ``upgrade`` / ``downgrade`` callables exist on every module.

These checks form the first half of the migration-safety gate the
TODO asked for in §7 P2. The second half — `alembic upgrade head` /
`alembic downgrade -1` against a real Postgres instance — lives in
``.github/workflows/migration-safety.yml``. The static gate runs on
every push (no DB infra required); the dynamic gate runs in CI.
"""

from __future__ import annotations

import importlib.util
import pathlib

MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "app"
    / "db"
    / "migrations"
    / "versions"
)


def _load_module(path: pathlib.Path):
    """Load a migration module by file path (digit-prefixed filenames
    can't be imported via the regular ``import`` statement)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, f"no spec for {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _migration_paths() -> list[pathlib.Path]:
    """Every ``NNN_*.py`` migration file in the versions directory."""
    return sorted(p for p in MIGRATIONS_DIR.glob("*.py") if p.name != "__init__.py")


def _load_all() -> dict[str, object]:
    """Map ``revision_id -> module``. Asserts no duplicates."""
    out: dict[str, object] = {}
    for p in _migration_paths():
        mod = _load_module(p)
        rev = getattr(mod, "revision", None)
        assert isinstance(rev, str), f"{p.name}: missing/non-str revision"
        assert rev not in out, f"duplicate revision id {rev!r}"
        out[rev] = mod
    return out


class TestMigrationChain:
    def test_at_least_one_migration_exists(self):
        paths = _migration_paths()
        assert len(paths) > 0, "expected at least one migration"

    def test_every_module_has_required_attrs(self):
        for path in _migration_paths():
            mod = _load_module(path)
            for attr in ("revision", "down_revision", "upgrade", "downgrade"):
                assert hasattr(mod, attr), f"{path.name} missing {attr}"
            assert callable(mod.upgrade), f"{path.name}: upgrade not callable"
            assert callable(mod.downgrade), f"{path.name}: downgrade not callable"

    def test_no_duplicate_revisions(self):
        seen: set[str] = set()
        for path in _migration_paths():
            mod = _load_module(path)
            assert mod.revision not in seen, (
                f"{path.name}: duplicate revision {mod.revision!r}"
            )
            seen.add(mod.revision)

    def test_every_down_revision_points_to_existing_migration(self):
        mods = _load_all()
        for rev, mod in mods.items():
            down = mod.down_revision
            if down is None:
                continue  # root revision
            assert down in mods, (
                f"revision {rev!r} declares down_revision={down!r} but "
                f"no migration with that id exists"
            )

    def test_exactly_one_root(self):
        """A root revision is one whose ``down_revision is None``."""
        mods = _load_all()
        roots = [rev for rev, mod in mods.items() if mod.down_revision is None]
        assert len(roots) == 1, (
            f"expected exactly one root migration, found {len(roots)}: {roots}"
        )

    def test_exactly_one_head(self):
        """A head is a revision that is nobody's down_revision."""
        mods = _load_all()
        parents = {
            mod.down_revision for mod in mods.values() if mod.down_revision is not None
        }
        heads = [rev for rev in mods if rev not in parents]
        assert len(heads) == 1, (
            f"expected exactly one head revision, found {len(heads)}: {heads}"
        )

    def test_chain_is_linear_no_branches(self):
        """Every revision is referenced by at most one descendant."""
        mods = _load_all()
        children_count: dict[str, int] = {}
        for mod in mods.values():
            down = mod.down_revision
            if down is None:
                continue
            children_count[down] = children_count.get(down, 0) + 1
        for parent, n in children_count.items():
            assert n == 1, (
                f"revision {parent!r} has {n} children — branching migration "
                f"chains are not supported"
            )

    def test_chain_traverses_every_migration_from_root_to_head(self):
        """Walk root → head; every migration must be visited exactly
        once. Catches dangling revisions that don't link into the
        main chain (e.g. a copy-pasted file that forgot to update
        ``down_revision``)."""
        mods = _load_all()
        # Find root.
        roots = [rev for rev, mod in mods.items() if mod.down_revision is None]
        assert len(roots) == 1
        current = roots[0]

        # Build parent→child lookup.
        child_of: dict[str, str] = {}
        for rev, mod in mods.items():
            if mod.down_revision is None:
                continue
            child_of[mod.down_revision] = rev

        visited = [current]
        while current in child_of:
            current = child_of[current]
            visited.append(current)

        assert set(visited) == set(mods.keys()), (
            f"chain walk visited {sorted(visited)} but versions dir contains "
            f"{sorted(mods.keys())}"
        )
