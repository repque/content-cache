"""
Tests for in-memory LRU cache implementation
"""
import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from content_cache.memory_cache import MemoryCache
from content_cache.models import CacheEntry


class TestMemoryCache:
    """
    Test cases for MemoryCache implementation
    """

    def test_memory_cache_initialization(self):
        """
        Test memory cache initialization with size limit
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)  # 1MB
        assert cache.max_size_bytes == 1024 * 1024
        assert cache.current_size_bytes == 0
        assert len(cache.entries) == 0

    @pytest.mark.asyncio
    async def test_add_and_get_entry(self):
        """
        Test adding and retrieving entries from cache
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)
        
        entry = CacheEntry(
            file_path=Path("/test/file.pdf"),
            content_hash="abc123",
            modification_time=1234567890.0,
            file_size=100,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        # Add entry
        await cache.add(entry)
        assert len(cache.entries) == 1
        assert cache.current_size_bytes > 0
        
        # Get entry
        retrieved = await cache.get(Path("/test/file.pdf"))
        assert retrieved is not None
        assert retrieved.content == "Test content"
        assert retrieved.access_count == 1  # Should increment

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """
        Test LRU eviction when cache is full
        """
        # Small cache that can hold only 2 small entries  
        # Each entry is ~220 bytes, so 500 bytes can hold 2 entries
        cache = MemoryCache(max_size_bytes=500)
        
        entries = []
        for i in range(3):
            entry = CacheEntry(
                file_path=Path(f"/test/file{i}.txt"),
                content_hash=f"hash{i}",
                modification_time=1234567890.0,
                file_size=10,
                content=f"Content {i}",  # Small content
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )
            entries.append(entry)
        
        # Add first two entries
        await cache.add(entries[0])
        await cache.add(entries[1])
        assert len(cache.entries) == 2
        
        # Add third entry - should evict the least recently used (first)
        await cache.add(entries[2])
        assert len(cache.entries) == 2
        assert await cache.get(Path("/test/file0.txt")) is None  # Evicted
        assert await cache.get(Path("/test/file1.txt")) is not None
        assert await cache.get(Path("/test/file2.txt")) is not None

    @pytest.mark.asyncio
    async def test_access_updates_lru_order(self):
        """
        Test that accessing an entry updates LRU order
        """
        # Each entry is ~220 bytes, so 500 bytes can hold 2 entries
        cache = MemoryCache(max_size_bytes=500)
        
        # Add two entries
        entry1 = CacheEntry(
            file_path=Path("/test/file1.txt"),
            content_hash="hash1",
            modification_time=1234567890.0,
            file_size=10,
            content="Content 1",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        entry2 = CacheEntry(
            file_path=Path("/test/file2.txt"),
            content_hash="hash2",
            modification_time=1234567890.0,
            file_size=10,
            content="Content 2",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        await cache.add(entry1)
        await cache.add(entry2)
        
        # Access entry1 to make it more recently used
        await cache.get(Path("/test/file1.txt"))
        
        # Add a third entry - should evict entry2 (least recently used)
        entry3 = CacheEntry(
            file_path=Path("/test/file3.txt"),
            content_hash="hash3",
            modification_time=1234567890.0,
            file_size=10,
            content="Content 3",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        await cache.add(entry3)
        assert await cache.get(Path("/test/file1.txt")) is not None  # Still there
        assert await cache.get(Path("/test/file2.txt")) is None  # Evicted
        assert await cache.get(Path("/test/file3.txt")) is not None

    @pytest.mark.asyncio
    async def test_remove_entry(self):
        """
        Test removing specific entry from cache
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)
        
        entry = CacheEntry(
            file_path=Path("/test/file.pdf"),
            content_hash="abc123",
            modification_time=1234567890.0,
            file_size=100,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        await cache.add(entry)
        assert await cache.get(Path("/test/file.pdf")) is not None
        
        # Remove entry
        removed = await cache.remove(Path("/test/file.pdf"))
        assert removed is True
        assert await cache.get(Path("/test/file.pdf")) is None
        assert cache.current_size_bytes == 0

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """
        Test clearing all entries from cache
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)
        
        # Add multiple entries
        for i in range(5):
            entry = CacheEntry(
                file_path=Path(f"/test/file{i}.txt"),
                content_hash=f"hash{i}",
                modification_time=1234567890.0,
                file_size=100,
                content=f"Content {i}",
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )
            await cache.add(entry)
        
        assert len(cache.entries) == 5
        assert cache.current_size_bytes > 0
        
        # Clear cache
        await cache.clear()
        assert len(cache.entries) == 0
        assert cache.current_size_bytes == 0

    @pytest.mark.asyncio
    async def test_memory_size_calculation(self):
        """
        Test accurate memory size calculation
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)
        
        large_content = "x" * 1000  # 1000 bytes
        entry = CacheEntry(
            file_path=Path("/test/large.txt"),
            content_hash="abc123",
            modification_time=1234567890.0,
            file_size=1000,
            content=large_content,
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        
        initial_size = cache.current_size_bytes
        await cache.add(entry)
        
        # Size should increase by at least the content size
        assert cache.current_size_bytes >= initial_size + len(large_content)

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """
        Test thread-safe concurrent access to cache
        """
        cache = MemoryCache(max_size_bytes=1024 * 1024)
        
        # Add initial entry
        entry = CacheEntry(
            file_path=Path("/test/concurrent.txt"),
            content_hash="abc123",
            modification_time=1234567890.0,
            file_size=100,
            content="Concurrent test",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        await cache.add(entry)
        
        # Concurrent reads
        async def read_entry():
            return await cache.get(Path("/test/concurrent.txt"))
        
        # Run multiple concurrent reads
        tasks = [read_entry() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All reads should succeed
        assert all(r is not None for r in results)
        assert all(r.content == "Concurrent test" for r in results)
        
        # Access count should be incremented properly
        final_entry = await cache.get(Path("/test/concurrent.txt"))
        assert final_entry.access_count == 11  # 10 concurrent + 1 final