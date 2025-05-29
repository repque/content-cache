"""
Tests for SQLite storage layer
"""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from content_cache.models import CacheEntry
from content_cache.sqlite_storage import SQLiteStorage


@pytest.fixture
async def temp_db():
    """
    Create a temporary SQLite database
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = Path(tf.name)
    
    storage = SQLiteStorage(db_path, pool_size=5)
    await storage.initialize()
    
    yield storage
    
    await storage.close()
    db_path.unlink()


class TestSQLiteStorage:
    """
    Test cases for SQLite storage implementation
    """

    @pytest.mark.asyncio
    async def test_initialization(self, temp_db):
        """
        Test database initialization and table creation
        """
        # Check that tables were created
        async with temp_db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = await cursor.fetchall()
            table_names = [t[0] for t in tables]
            
            assert "cache_entries" in table_names
            assert "cache_metadata" in table_names

    @pytest.mark.asyncio
    async def test_add_and_get_entry(self, temp_db):
        """
        Test adding and retrieving entries
        """
        entry = CacheEntry(
            file_path=Path("/test/file.pdf"),
            content_hash="abc123def456",
            modification_time=1234567890.0,
            file_size=1024,
            content="Test content from PDF",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        # Add entry
        await temp_db.add(entry)
        
        # Retrieve entry
        retrieved = await temp_db.get(Path("/test/file.pdf"))
        assert retrieved is not None
        assert retrieved.content == "Test content from PDF"
        assert retrieved.content_hash == "abc123def456"
        assert retrieved.file_size == 1024

    @pytest.mark.asyncio
    async def test_update_existing_entry(self, temp_db):
        """
        Test updating an existing entry
        """
        path = Path("/test/update.txt")
        
        # Add initial entry
        entry1 = CacheEntry(
            file_path=path,
            content_hash="hash1",
            modification_time=1000.0,
            file_size=100,
            content="Initial content",
            extraction_timestamp=datetime.now(),
            access_count=5,
            last_accessed=datetime.now(),
        )
        await temp_db.add(entry1)
        
        # Update with new content
        entry2 = CacheEntry(
            file_path=path,
            content_hash="hash2",
            modification_time=2000.0,
            file_size=200,
            content="Updated content",
            extraction_timestamp=datetime.now(),
            access_count=0,  # Should be preserved from original
            last_accessed=datetime.now(),
        )
        await temp_db.add(entry2)
        
        # Verify update
        retrieved = await temp_db.get(path)
        assert retrieved.content == "Updated content"
        assert retrieved.content_hash == "hash2"
        assert retrieved.modification_time == 2000.0
        assert retrieved.access_count == 5  # Preserved from original

    @pytest.mark.asyncio
    async def test_remove_entry(self, temp_db):
        """
        Test removing entries
        """
        path = Path("/test/remove.txt")
        
        entry = CacheEntry(
            file_path=path,
            content_hash="hash123",
            modification_time=1234567890.0,
            file_size=500,
            content="To be removed",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        await temp_db.add(entry)
        assert await temp_db.get(path) is not None
        
        # Remove entry
        removed = await temp_db.remove(path)
        assert removed is True
        
        # Verify removal
        assert await temp_db.get(path) is None

    @pytest.mark.asyncio
    async def test_get_by_hash(self, temp_db):
        """
        Test retrieving entries by content hash
        """
        # Add multiple entries with same hash (duplicates)
        hash_value = "duplicate_hash_123"
        paths = []
        
        for i in range(3):
            path = Path(f"/test/dup{i}.txt")
            paths.append(path)
            entry = CacheEntry(
                file_path=path,
                content_hash=hash_value,
                modification_time=1234567890.0,
                file_size=100,
                content=f"Duplicate content {i}",
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )
            await temp_db.add(entry)
        
        # Get all entries with same hash
        entries = await temp_db.get_by_hash(hash_value)
        assert len(entries) == 3
        assert all(e.content_hash == hash_value for e in entries)
        assert set(e.file_path for e in entries) == set(paths)

    @pytest.mark.asyncio
    async def test_get_all_entries(self, temp_db):
        """
        Test retrieving all entries
        """
        # Add multiple entries
        for i in range(5):
            entry = CacheEntry(
                file_path=Path(f"/test/file{i}.txt"),
                content_hash=f"hash{i}",
                modification_time=1234567890.0 + i,
                file_size=100 * i,
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=i,
                last_accessed=datetime.now(),
            )
            await temp_db.add(entry)
        
        # Get all entries
        all_entries = await temp_db.get_all()
        assert len(all_entries) == 5
        
        # Verify order (should be by path)
        paths = [e.file_path for e in all_entries]
        assert paths == sorted(paths)

    @pytest.mark.asyncio
    async def test_clear_old_entries(self, temp_db):
        """
        Test clearing old entries based on last access time
        """
        now = datetime.now()
        
        # Add entries with different last_accessed times
        # Old entry (10 days ago)
        old_entry = CacheEntry(
            file_path=Path("/test/old.txt"),
            content_hash="old_hash",
            modification_time=1234567890.0,
            file_size=100,
            content="Old content",
            extraction_timestamp=now,
            access_count=10,
            last_accessed=datetime.fromtimestamp(now.timestamp() - 10 * 24 * 3600),
        )
        await temp_db.add(old_entry)
        
        # Recent entry (1 day ago)
        recent_entry = CacheEntry(
            file_path=Path("/test/recent.txt"),
            content_hash="recent_hash",
            modification_time=1234567890.0,
            file_size=100,
            content="Recent content",
            extraction_timestamp=now,
            access_count=5,
            last_accessed=datetime.fromtimestamp(now.timestamp() - 1 * 24 * 3600),
        )
        await temp_db.add(recent_entry)
        
        # Clear entries older than 7 days
        removed_count = await temp_db.clear_old_entries(days=7)
        assert removed_count == 1
        
        # Verify old entry is gone, recent entry remains
        assert await temp_db.get(Path("/test/old.txt")) is None
        assert await temp_db.get(Path("/test/recent.txt")) is not None

    @pytest.mark.asyncio
    async def test_get_statistics(self, temp_db):
        """
        Test retrieving storage statistics
        """
        # Add some entries
        for i in range(3):
            entry = CacheEntry(
                file_path=Path(f"/test/file{i}.txt"),
                content_hash="hash" if i < 2 else "unique_hash",  # 2 duplicates
                modification_time=1234567890.0,
                file_size=1000 * (i + 1),
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=i * 2,
                last_accessed=datetime.now(),
            )
            await temp_db.add(entry)
        
        stats = await temp_db.get_statistics()
        
        assert stats["total_entries"] == 3
        assert stats["total_size"] == 6000  # 1000 + 2000 + 3000
        assert stats["unique_hashes"] == 2  # "hash" and "unique_hash"
        assert stats["total_access_count"] == 6  # 0 + 2 + 4

    @pytest.mark.asyncio
    async def test_concurrent_access(self, temp_db):
        """
        Test concurrent database operations
        """
        # Add initial entries
        paths = []
        for i in range(10):
            path = Path(f"/test/concurrent{i}.txt")
            paths.append(path)
            entry = CacheEntry(
                file_path=path,
                content_hash=f"hash{i}",
                modification_time=1234567890.0,
                file_size=100,
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )
            await temp_db.add(entry)
        
        # Concurrent reads
        async def read_entry(path):
            return await temp_db.get(path)
        
        # Run multiple concurrent reads
        tasks = [read_entry(path) for path in paths]
        results = await asyncio.gather(*tasks)
        
        # All reads should succeed
        assert all(r is not None for r in results)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_large_content_handling(self, temp_db):
        """
        Test handling of large content with external blob path
        """
        # Create large content (> 1MB)
        large_content = "x" * (2 * 1024 * 1024)  # 2MB
        
        # When storing large content, the caller should set blob_path and clear content
        entry = CacheEntry(
            file_path=Path("/test/large.txt"),
            content_hash="large_hash",
            modification_time=1234567890.0,
            file_size=len(large_content),
            content=None,  # Content not stored in DB
            content_blob_path=Path("blobs/la/rg/large_hash.gz"),  # External storage path
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        await temp_db.add(entry)
        
        # Retrieve and verify
        retrieved = await temp_db.get(Path("/test/large.txt"))
        assert retrieved is not None
        assert retrieved.content_blob_path is not None
        assert str(retrieved.content_blob_path) == "blobs/la/rg/large_hash.gz"
        
        # The SQLite storage simulates large content retrieval in _row_to_entry
        assert retrieved.content is not None  # Simulated content
        assert len(retrieved.content) == 2 * 1024 * 1024