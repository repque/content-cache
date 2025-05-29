"""
Tests for file system storage component
"""
import tempfile
import zlib
from pathlib import Path

import pytest

from content_cache.file_storage import FileStorage


@pytest.fixture
def temp_storage_dir():
    """
    Create a temporary directory for file storage
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestFileStorage:
    """
    Test cases for FileStorage implementation
    """

    def test_initialization(self, temp_storage_dir):
        """
        Test file storage initialization
        """
        storage = FileStorage(temp_storage_dir, compression_level=6)
        assert storage.base_path == temp_storage_dir
        assert storage.compression_level == 6

    @pytest.mark.asyncio
    async def test_store_and_retrieve_content(self, temp_storage_dir):
        """
        Test storing and retrieving content
        """
        storage = FileStorage(temp_storage_dir)
        
        content = "This is test content for file storage"
        content_hash = "abc123def456789"
        
        # Store content
        blob_path = await storage.store(content_hash, content)
        assert blob_path is not None
        assert blob_path.exists()
        
        # Retrieve content
        retrieved = await storage.retrieve(content_hash)
        assert retrieved == content

    @pytest.mark.asyncio
    async def test_store_large_content(self, temp_storage_dir):
        """
        Test storing large content with compression
        """
        storage = FileStorage(temp_storage_dir, compression_level=6)
        
        # Create large content (1MB of repeated text)
        large_content = "Large content chunk. " * 50000
        content_hash = "large_content_hash_123"
        
        # Store content
        blob_path = await storage.store(content_hash, large_content)
        
        # Verify compression worked (file should be smaller than original)
        file_size = blob_path.stat().st_size
        original_size = len(large_content.encode())
        assert file_size < original_size  # Compressed
        
        # Retrieve and verify
        retrieved = await storage.retrieve(content_hash)
        assert retrieved == large_content

    @pytest.mark.asyncio
    async def test_delete_content(self, temp_storage_dir):
        """
        Test deleting stored content
        """
        storage = FileStorage(temp_storage_dir)
        
        content = "Content to be deleted"
        content_hash = "delete_test_hash"
        
        # Store content
        blob_path = await storage.store(content_hash, content)
        assert blob_path.exists()
        
        # Delete content
        deleted = await storage.delete(content_hash)
        assert deleted is True
        assert not blob_path.exists()
        
        # Try to retrieve deleted content
        retrieved = await storage.retrieve(content_hash)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_exists_check(self, temp_storage_dir):
        """
        Test checking if content exists
        """
        storage = FileStorage(temp_storage_dir)
        
        content = "Existing content"
        content_hash = "exists_test_hash"
        
        # Check non-existent content
        assert await storage.exists(content_hash) is False
        
        # Store content
        await storage.store(content_hash, content)
        
        # Check existing content
        assert await storage.exists(content_hash) is True

    @pytest.mark.asyncio
    async def test_get_path_for_hash(self, temp_storage_dir):
        """
        Test path generation for content hash
        """
        storage = FileStorage(temp_storage_dir)
        
        content_hash = "abc123def456789"
        path = storage._get_path_for_hash(content_hash)
        
        # Verify path structure
        assert path.parent.parent.parent == temp_storage_dir
        assert path.parent.parent.name == "ab"  # First 2 chars
        assert path.parent.name == "c1"  # Next 2 chars
        assert path.name == "abc123def456789.gz"

    @pytest.mark.asyncio
    async def test_concurrent_access(self, temp_storage_dir):
        """
        Test concurrent read/write operations
        """
        storage = FileStorage(temp_storage_dir)
        
        # Store initial content
        content = "Concurrent test content"
        content_hash = "concurrent_test_hash"
        await storage.store(content_hash, content)
        
        # Concurrent reads
        import asyncio
        
        async def read_content():
            return await storage.retrieve(content_hash)
        
        # Run multiple concurrent reads
        tasks = [read_content() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All reads should succeed with same content
        assert all(r == content for r in results)

    @pytest.mark.asyncio
    async def test_invalid_hash_handling(self, temp_storage_dir):
        """
        Test handling of invalid or non-existent hashes
        """
        storage = FileStorage(temp_storage_dir)
        
        # Try to retrieve non-existent content
        retrieved = await storage.retrieve("non_existent_hash")
        assert retrieved is None
        
        # Try to delete non-existent content
        deleted = await storage.delete("non_existent_hash")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_compression_levels(self, temp_storage_dir):
        """
        Test different compression levels
        """
        content = "Test content for compression" * 100
        content_hash = "compression_test"
        
        sizes = {}
        
        for level in [0, 6, 9]:  # No compression, default, max
            storage = FileStorage(temp_storage_dir / f"level_{level}", compression_level=level)
            blob_path = await storage.store(content_hash, content)
            sizes[level] = blob_path.stat().st_size
        
        # Verify compression effectiveness
        assert sizes[0] > sizes[6]  # Uncompressed larger than default
        assert sizes[6] >= sizes[9]  # Default larger or equal to max

    @pytest.mark.asyncio
    async def test_get_size(self, temp_storage_dir):
        """
        Test getting size of stored content
        """
        storage = FileStorage(temp_storage_dir)
        
        content = "Content with known size"
        content_hash = "size_test_hash"
        
        # Check size of non-existent content
        size = await storage.get_size(content_hash)
        assert size == 0
        
        # Store content and check size
        await storage.store(content_hash, content)
        size = await storage.get_size(content_hash)
        assert size > 0  # Should have some size
        
    @pytest.mark.asyncio
    async def test_cleanup_empty_directories(self, temp_storage_dir):
        """
        Test that empty directories are cleaned up after deletion
        """
        storage = FileStorage(temp_storage_dir)
        
        content = "Cleanup test content"
        content_hash = "cleanup_test_hash"
        
        # Store and then delete content
        blob_path = await storage.store(content_hash, content)
        parent_dir = blob_path.parent
        
        await storage.delete(content_hash)
        
        # Parent directory should be cleaned up if empty
        assert not parent_dir.exists()