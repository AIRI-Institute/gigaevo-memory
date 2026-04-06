"""Tests for CacheStore and CachePolicy."""

from datetime import datetime, timedelta, timezone

from gigaevo_memory.cache import CacheEntry, CachePolicy, CacheStore


def _make_entry(
    entity_id: str = "ent-1",
    channel: str = "latest",
    cached_at: datetime | None = None,
) -> CacheEntry:
    return CacheEntry(
        entity_type="chain",
        entity_id=entity_id,
        channel=channel,
        version_id="ver-1",
        content_hash="abc123",
        raw_content={"version": "1.1", "steps": []},
        cached_at=cached_at or datetime.now(timezone.utc),
    )


class TestTTLPolicy:
    def test_fresh_entry_returned(self):
        store = CacheStore(policy=CachePolicy.TTL, ttl=300)
        entry = _make_entry()
        store.put(entry)
        assert store.get("chain", "ent-1", "latest") is not None

    def test_expired_entry_evicted(self):
        store = CacheStore(policy=CachePolicy.TTL, ttl=1)
        old = _make_entry(
            cached_at=datetime.now(timezone.utc) - timedelta(seconds=5)
        )
        store.put(old)
        assert store.get("chain", "ent-1", "latest") is None

    def test_different_channels_independent(self):
        store = CacheStore(policy=CachePolicy.TTL, ttl=300)
        store.put(_make_entry(channel="latest"))
        store.put(_make_entry(channel="stable"))
        assert store.get("chain", "ent-1", "latest") is not None
        assert store.get("chain", "ent-1", "stable") is not None
        assert store.get("chain", "ent-1", "experimental") is None


class TestFreshnessPolicy:
    def test_entry_always_returned(self):
        """Freshness check mode returns entry regardless of age (check done at HTTP level)."""
        store = CacheStore(policy=CachePolicy.FRESHNESS_CHECK, ttl=1)
        old = _make_entry(
            cached_at=datetime.now(timezone.utc) - timedelta(seconds=100)
        )
        store.put(old)
        # Freshness policy does NOT evict on age — the client does a conditional GET
        assert store.get("chain", "ent-1", "latest") is not None


class TestInvalidation:
    def test_invalidate_by_entity_id(self):
        store = CacheStore()
        store.put(_make_entry(channel="latest"))
        store.put(_make_entry(channel="stable"))
        assert len(store) == 2
        store.invalidate("ent-1")
        assert len(store) == 0

    def test_invalidate_specific_channel(self):
        store = CacheStore()
        store.put(_make_entry(channel="latest"))
        store.put(_make_entry(channel="stable"))
        store.invalidate("ent-1", channel="latest")
        assert len(store) == 1
        assert store.get("chain", "ent-1", "stable") is not None

    def test_clear(self):
        store = CacheStore()
        store.put(_make_entry(entity_id="a"))
        store.put(_make_entry(entity_id="b"))
        assert len(store) == 2
        store.clear()
        assert len(store) == 0
