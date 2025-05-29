"""
Tests for the main ContentCache class
"""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from content_cache import ContentCache, CachedContent, IntegrityStatus
from content_cache.config import CacheConfig


@pytest.fixture
async def temp_cache_dir():
    """
    Create a temporary cache directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
async def cache_instance(temp_cache_dir):
    """
    Create a ContentCache instance for testing
    """
    config = CacheConfig(
        cache_dir=temp_cache_dir,
        max_memory_size=10 * 1024 * 1024,  # 10MB
        verify_hash=True,
        compression_level=6,
    )
    
    cache = ContentCache(config)
    await cache.initialize()
    
    yield cache
    
    await cache.close()


# Sample processor functions for testing
async def process_text_file(file_path: Path) -> str:
    """
    Simple text file processor
    """
    with open(file_path, 'r') as f:
        return f.read()


async def process_uppercase(file_path: Path) -> str:
    """
    Process text file and convert to uppercase
    """
    with open(file_path, 'r') as f:
        return f.read().upper()


class TestContentCache:
    """
    Test cases for ContentCache main functionality
    """

    @pytest.mark.asyncio
    async def test_cache_initialization(self, cache_instance):
        """
        Test cache initialization
        """
        assert cache_instance.config.cache_dir.exists()
        assert cache_instance._initialized is True

    @pytest.mark.asyncio
    async def test_get_content_fresh_file(self, cache_instance, temp_cache_dir):
        """
        Test getting content from a file not in cache
        """
        # Create a test file
        test_file = temp_cache_dir / "test.txt"
        test_file.write_text("Hello, World!")
        
        # Get content (should process file)
        result = await cache_instance.get_content(test_file, process_text_file)
        
        assert isinstance(result, CachedContent)
        assert result.content == "Hello, World!"
        assert result.from_cache is False
        assert len(result.content_hash) == 64  # SHA-256 hash

    @pytest.mark.asyncio
    async def test_get_content_cached_file(self, cache_instance, temp_cache_dir):
        """
        Test getting content from cache on second access
        """
        # Create a test file
        test_file = temp_cache_dir / "cached.txt"
        test_file.write_text("Cached content test")
        
        # First access - process file
        result1 = await cache_instance.get_content(test_file, process_text_file)
        assert result1.from_cache is False
        
        # Second access - should use cache
        result2 = await cache_instance.get_content(test_file, process_text_file)
        assert result2.from_cache is True
        assert result2.content == result1.content
        assert result2.content_hash == result1.content_hash

    @pytest.mark.asyncio
    async def test_file_modification_detection(self, cache_instance, temp_cache_dir):
        """
        Test that modified files are reprocessed
        """
        # Create a test file
        test_file = temp_cache_dir / "modify.txt"
        test_file.write_text("Original content")
        
        # First access
        result1 = await cache_instance.get_content(test_file, process_text_file)
        assert result1.content == "Original content"
        
        # Modify file
        await asyncio.sleep(0.1)  # Ensure mtime changes
        test_file.write_text("Modified content")
        
        # Second access - should detect modification
        result2 = await cache_instance.get_content(test_file, process_text_file)
        assert result2.from_cache is False
        assert result2.content == "Modified content"
        assert result2.content_hash != result1.content_hash

    @pytest.mark.asyncio
    async def test_different_processors_same_file(self, cache_instance, temp_cache_dir):
        """
        Test using different processors on the same file
        """
        # Create a test file
        test_file = temp_cache_dir / "multi_process.txt"
        test_file.write_text("hello world")
        
        # Process with first processor
        result1 = await cache_instance.get_content(test_file, process_text_file)
        assert result1.content == "hello world"
        
        # Process with different processor (cache is file-based, so it will use cache)
        # The cache stores the result of the first processor
        result2 = await cache_instance.get_content(test_file, process_uppercase)
        assert result2.content == "hello world"  # Will get cached content
        assert result2.from_cache is True

    @pytest.mark.asyncio
    async def test_missing_file_handling(self, cache_instance):
        """
        Test handling of missing files
        """
        missing_file = Path("/does/not/exist.txt")
        
        with pytest.raises(FileNotFoundError):
            await cache_instance.get_content(missing_file, process_text_file)

    @pytest.mark.asyncio
    async def test_large_content_handling(self, cache_instance, temp_cache_dir):
        """
        Test handling of large content (should use file storage)
        """
        # Create a large file (2MB)
        large_file = temp_cache_dir / "large.txt"
        large_content = "x" * (2 * 1024 * 1024)
        large_file.write_text(large_content)
        
        # Process large file
        result = await cache_instance.get_content(large_file, process_text_file)
        assert result.content == large_content
        assert result.from_cache is False
        
        # Second access should still work
        result2 = await cache_instance.get_content(large_file, process_text_file)
        assert result2.from_cache is True
        assert result2.content == large_content

    @pytest.mark.asyncio
    async def test_concurrent_access_same_file(self, cache_instance, temp_cache_dir):
        """
        Test concurrent access to the same file
        """
        # Create a test file
        test_file = temp_cache_dir / "concurrent.txt"
        test_file.write_text("Concurrent access test")
        
        # Concurrent access
        async def get_content():
            return await cache_instance.get_content(test_file, process_text_file)
        
        # Run multiple concurrent requests
        tasks = [get_content() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All should succeed with same content
        assert all(r.content == "Concurrent access test" for r in results)
        
        # At least one should be from cache
        assert any(r.from_cache for r in results)

    @pytest.mark.asyncio
    async def test_invalidate_cache_entry(self, cache_instance, temp_cache_dir):
        """
        Test invalidating specific cache entries
        """
        # Create and cache a file
        test_file = temp_cache_dir / "invalidate.txt"
        test_file.write_text("To be invalidated")
        
        # First access
        result1 = await cache_instance.get_content(test_file, process_text_file)
        assert result1.from_cache is False
        
        # Verify it's cached
        result2 = await cache_instance.get_content(test_file, process_text_file)
        assert result2.from_cache is True
        
        # Invalidate
        await cache_instance.invalidate(test_file)
        
        # Next access should reprocess
        result3 = await cache_instance.get_content(test_file, process_text_file)
        assert result3.from_cache is False

    @pytest.mark.asyncio
    async def test_clear_old_entries(self, cache_instance, temp_cache_dir):
        """
        Test clearing old cache entries
        """
        # Create multiple files
        for i in range(3):
            test_file = temp_cache_dir / f"old_test_{i}.txt"
            test_file.write_text(f"Content {i}")
            await cache_instance.get_content(test_file, process_text_file)
        
        # Clear entries older than 0 days (all entries)
        removed = await cache_instance.clear_old_entries(days=0)
        assert removed > 0

    @pytest.mark.asyncio
    async def test_get_statistics(self, cache_instance, temp_cache_dir):
        """
        Test getting cache statistics
        """
        # Create and process some files
        for i in range(3):
            test_file = temp_cache_dir / f"stats_{i}.txt"
            test_file.write_text(f"Stats content {i}")
            await cache_instance.get_content(test_file, process_text_file)
        
        # Get statistics
        stats = await cache_instance.get_statistics()
        
        assert stats["total_entries"] >= 3
        assert stats["memory_entries"] >= 0
        assert stats["cache_hits"] >= 0
        assert stats["cache_misses"] >= 3

    @pytest.mark.asyncio
    async def test_duplicate_content_detection(self, cache_instance, temp_cache_dir):
        """
        Test detection of duplicate content across different files
        """
        # Create files with identical content
        content = "Duplicate content for testing"
        file1 = temp_cache_dir / "dup1.txt"
        file2 = temp_cache_dir / "dup2.txt"
        
        file1.write_text(content)
        file2.write_text(content)
        
        # Process both files
        result1 = await cache_instance.get_content(file1, process_text_file)
        result2 = await cache_instance.get_content(file2, process_text_file)
        
        # Should have same content hash
        assert result1.content_hash == result2.content_hash
        
        # Get duplicate statistics
        stats = await cache_instance.get_statistics()
        assert "duplicate_groups" in stats
        assert stats["duplicate_groups"] >= 1

    @pytest.mark.asyncio
    async def test_processor_exception_handling(self, cache_instance, temp_cache_dir):
        """
        Test handling of processor exceptions
        """
        test_file = temp_cache_dir / "error.txt"
        test_file.write_text("Will cause error")
        
        async def failing_processor(file_path: Path) -> str:
            raise ValueError("Processing failed")
        
        with pytest.raises(ValueError):
            await cache_instance.get_content(test_file, failing_processor)