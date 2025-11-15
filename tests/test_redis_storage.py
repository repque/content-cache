"""
Tests for Redis storage implementation
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from content_cache.models import CacheEntry
from content_cache.redis_storage import RedisStorage


class MockRedis:
    """Mock Redis client for testing"""

    def __init__(self):
        self.data = {}
        self.closed = False

    async def ping(self):
        """Mock ping"""
        return True

    async def exists(self, key):
        """Mock exists"""
        return key in self.data

    async def hset(self, key, field=None, value=None, mapping=None, **kwargs):
        """Mock hset"""
        if key not in self.data:
            self.data[key] = {}

        # Handle field/value pair
        if field is not None and value is not None:
            self.data[key][field] = value
            return 1

        # Handle mapping
        if mapping:
            self.data[key].update(mapping)
            return len(mapping)

        # Handle kwargs
        if kwargs:
            self.data[key].update(kwargs)
            return len(kwargs)

        return 0

    async def hget(self, key, field):
        """Mock hget"""
        if key in self.data and field in self.data[key]:
            return self.data[key][field]
        return None

    async def hgetall(self, key):
        """Mock hgetall"""
        return self.data.get(key, {})

    async def hincrby(self, key, field, amount=1):
        """Mock hincrby"""
        if key not in self.data:
            self.data[key] = {}
        if field not in self.data[key]:
            self.data[key][field] = "0"

        current = int(self.data[key][field])
        self.data[key][field] = str(current + amount)
        return int(self.data[key][field])

    async def delete(self, key):
        """Mock delete"""
        if key in self.data:
            del self.data[key]
            return 1
        return 0

    async def scan(self, cursor, match=None, count=100):
        """Mock scan"""
        keys = list(self.data.keys())

        if match:
            import re

            pattern = match.replace("*", ".*")
            keys = [k for k in keys if re.match(pattern, k)]

        # Simple pagination simulation
        if cursor == 0:
            return (0, keys)  # Return all keys at once for simplicity
        return (0, [])

    def pipeline(self):
        """Mock pipeline"""
        return MockPipeline(self)

    async def close(self):
        """Mock close"""
        self.closed = True


class MockPipeline:
    """Mock Redis pipeline"""

    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def hgetall(self, key):
        """Queue hgetall command"""
        self.commands.append(("hgetall", key))
        return self

    def hget(self, key, field):
        """Queue hget command"""
        self.commands.append(("hget", key, field))
        return self

    async def execute(self):
        """Execute queued commands"""
        results = []
        for cmd in self.commands:
            if cmd[0] == "hgetall":
                results.append(await self.redis.hgetall(cmd[1]))
            elif cmd[0] == "hget":
                results.append(await self.redis.hget(cmd[1], cmd[2]))
        self.commands = []
        return results


@pytest.fixture
def mock_redis():
    """Create a mock Redis client"""
    return MockRedis()


@pytest.fixture
async def storage_instance(mock_redis):
    """Create a RedisStorage instance with mock Redis"""
    storage = RedisStorage(mock_redis, key_prefix="test_cache")
    await storage.initialize()
    return storage


@pytest.fixture
def sample_cache_entry():
    """Create a sample cache entry for testing"""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        test_file = Path(tf.name)
        tf.write(b"Test content for caching")

    return CacheEntry(
        file_path=test_file,
        content_hash="abc123def456",
        modification_time=test_file.stat().st_mtime,
        file_size=100,
        content="Small test content",
        extraction_timestamp=datetime.now(),
        access_count=0,
        last_accessed=datetime.now(),
    )


class TestRedisStorage:
    """Test suite for RedisStorage"""

    @pytest.mark.asyncio
    async def test_initialization(self, mock_redis):
        """Test storage initialization"""
        storage = RedisStorage(mock_redis, key_prefix="test_cache")
        await storage.initialize()

        assert storage._initialized is True
        assert "test_cache:stats" in mock_redis.data

    @pytest.mark.asyncio
    async def test_add_and_get_entry(self, storage_instance, sample_cache_entry):
        """Test adding and retrieving a cache entry"""
        await storage_instance.add(sample_cache_entry)

        retrieved = await storage_instance.get(sample_cache_entry.file_path)

        assert retrieved is not None
        assert retrieved.file_path == sample_cache_entry.file_path
        assert retrieved.content_hash == sample_cache_entry.content_hash
        assert retrieved.content == sample_cache_entry.content
        assert retrieved.file_size == sample_cache_entry.file_size

    @pytest.mark.asyncio
    async def test_update_existing_entry(self, storage_instance, sample_cache_entry):
        """Test updating an existing cache entry preserves access count"""
        # Add initial entry
        await storage_instance.add(sample_cache_entry)

        # Simulate access by updating access count manually
        entry_key = storage_instance._entry_key(sample_cache_entry.file_path)
        await storage_instance.redis.hset(entry_key, "access_count", "5")

        # Update entry with new content
        sample_cache_entry.content = "Updated content"
        await storage_instance.add(sample_cache_entry)

        # Retrieve and verify access count was preserved
        retrieved = await storage_instance.get(sample_cache_entry.file_path)
        assert retrieved.access_count == 5
        assert retrieved.content == "Updated content"

    @pytest.mark.asyncio
    async def test_remove_entry(self, storage_instance, sample_cache_entry):
        """Test removing a cache entry"""
        await storage_instance.add(sample_cache_entry)

        result = await storage_instance.remove(sample_cache_entry.file_path)
        assert result is True

        retrieved = await storage_instance.get(sample_cache_entry.file_path)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_entry(self, storage_instance):
        """Test removing an entry that doesn't exist"""
        result = await storage_instance.remove(Path("/nonexistent/file.txt"))
        assert result is False

    @pytest.mark.asyncio
    async def test_get_all_entries(self, storage_instance, sample_cache_entry):
        """Test retrieving all cache entries"""
        # Add multiple entries
        entries = []
        for i in range(3):
            entry = CacheEntry(
                file_path=Path(f"/tmp/test_{i}.txt"),
                content_hash=f"hash{i}",
                modification_time=datetime.now().timestamp(),
                file_size=100 + i,
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=i,
                last_accessed=datetime.now(),
            )
            entries.append(entry)
            await storage_instance.add(entry)

        all_entries = await storage_instance.get_all()

        assert len(all_entries) == 3
        assert all(isinstance(e, CacheEntry) for e in all_entries)

        # Verify sorting by file path
        paths = [str(e.file_path) for e in all_entries]
        assert paths == sorted(paths)

    @pytest.mark.asyncio
    async def test_clear_old_entries(self, storage_instance):
        """Test clearing entries based on access time"""
        # Add entries with different last_accessed times
        now = datetime.now()

        old_entry = CacheEntry(
            file_path=Path("/tmp/old.txt"),
            content_hash="old_hash",
            modification_time=now.timestamp(),
            file_size=100,
            content="Old content",
            extraction_timestamp=now - timedelta(days=10),
            access_count=0,
            last_accessed=now - timedelta(days=10),
        )

        recent_entry = CacheEntry(
            file_path=Path("/tmp/recent.txt"),
            content_hash="recent_hash",
            modification_time=now.timestamp(),
            file_size=100,
            content="Recent content",
            extraction_timestamp=now,
            access_count=0,
            last_accessed=now,
        )

        await storage_instance.add(old_entry)
        await storage_instance.add(recent_entry)

        # Clear entries older than 7 days
        removed = await storage_instance.clear_old_entries(7)

        assert removed == 1

        # Verify old entry is gone
        assert await storage_instance.get(old_entry.file_path) is None
        # Verify recent entry remains
        assert await storage_instance.get(recent_entry.file_path) is not None

    @pytest.mark.asyncio
    async def test_get_statistics(self, storage_instance, sample_cache_entry):
        """Test retrieving storage statistics"""
        # Add entries
        await storage_instance.add(sample_cache_entry)

        stats = await storage_instance.get_statistics()

        assert "total_entries" in stats
        assert "total_size" in stats
        assert "unique_hashes" in stats
        assert stats["total_entries"] >= 1
        assert stats["unique_hashes"] >= 1

    @pytest.mark.asyncio
    async def test_large_content_handling(self, storage_instance):
        """Test handling of large content (blob storage)"""
        # Create entry with large content that should use blob storage
        large_content = "x" * (2 * 1024 * 1024)  # 2MB
        large_entry = CacheEntry(
            file_path=Path("/tmp/large.txt"),
            content_hash="large_hash",
            modification_time=datetime.now().timestamp(),
            file_size=len(large_content),
            content=None,  # Content stored in blob
            content_blob_path=Path("/blobs/large_hash.gz"),
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )

        await storage_instance.add(large_entry)
        retrieved = await storage_instance.get(large_entry.file_path)

        assert retrieved is not None
        assert retrieved.content_blob_path == large_entry.content_blob_path
        assert retrieved.content is None  # Content not stored in Redis

    @pytest.mark.asyncio
    async def test_serialize_deserialize_entry(self, storage_instance, sample_cache_entry):
        """Test entry serialization and deserialization"""
        # Serialize
        serialized = storage_instance._serialize_entry(sample_cache_entry)

        assert isinstance(serialized, dict)
        assert "content_hash" in serialized
        assert "content" in serialized
        assert serialized["content_hash"] == sample_cache_entry.content_hash

        # Add to Redis and retrieve to test full round-trip
        await storage_instance.add(sample_cache_entry)
        retrieved = await storage_instance.get(sample_cache_entry.file_path)

        # Verify all fields match
        assert retrieved.content_hash == sample_cache_entry.content_hash
        assert retrieved.file_size == sample_cache_entry.file_size
        assert retrieved.content == sample_cache_entry.content

    @pytest.mark.asyncio
    async def test_concurrent_access(self, storage_instance):
        """Test concurrent operations on storage"""
        import asyncio

        entries = [
            CacheEntry(
                file_path=Path(f"/tmp/concurrent_{i}.txt"),
                content_hash=f"hash_{i}",
                modification_time=datetime.now().timestamp(),
                file_size=100,
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )
            for i in range(10)
        ]

        # Add all entries concurrently
        tasks = [storage_instance.add(entry) for entry in entries]
        await asyncio.gather(*tasks)

        # Retrieve all entries concurrently
        tasks = [storage_instance.get(entry.file_path) for entry in entries]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_close(self, storage_instance):
        """Test closing the storage"""
        await storage_instance.close()
        assert storage_instance.redis.closed is True

    @pytest.mark.asyncio
    async def test_key_prefix_isolation(self, mock_redis):
        """Test that key prefixes provide namespace isolation"""
        storage1 = RedisStorage(mock_redis, key_prefix="app1")
        storage2 = RedisStorage(mock_redis, key_prefix="app2")

        await storage1.initialize()
        await storage2.initialize()

        entry = CacheEntry(
            file_path=Path("/tmp/test.txt"),
            content_hash="test_hash",
            modification_time=datetime.now().timestamp(),
            file_size=100,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )

        # Add to storage1
        await storage1.add(entry)

        # Storage2 should not see it
        assert await storage2.get(entry.file_path) is None

        # Storage1 should see it
        assert await storage1.get(entry.file_path) is not None

    @pytest.mark.asyncio
    async def test_statistics_update_on_add(self, storage_instance, sample_cache_entry):
        """Test that statistics are updated when entries are added"""
        stats_before = await storage_instance.get_statistics()

        await storage_instance.add(sample_cache_entry)

        stats_after = await storage_instance.get_statistics()

        assert stats_after["total_entries"] == stats_before["total_entries"] + 1
        assert stats_after["total_size"] >= stats_before["total_size"]

    @pytest.mark.asyncio
    async def test_statistics_update_on_remove(self, storage_instance, sample_cache_entry):
        """Test that statistics are updated when entries are removed"""
        await storage_instance.add(sample_cache_entry)
        stats_before = await storage_instance.get_statistics()

        await storage_instance.remove(sample_cache_entry.file_path)

        stats_after = await storage_instance.get_statistics()

        assert stats_after["total_entries"] == stats_before["total_entries"] - 1
