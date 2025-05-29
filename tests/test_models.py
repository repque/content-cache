"""
Tests for cache models
"""
import pytest
from datetime import datetime
from pathlib import Path

from content_cache.models import CacheEntry, CachedContent, IntegrityStatus


class TestCacheEntry:
    """
    Test cases for CacheEntry model
    """

    def test_cache_entry_creation(self):
        """
        Test creating a cache entry with all required fields
        """
        entry = CacheEntry(
            file_path=Path("/test/file.pdf"),
            content_hash="abc123def456",
            modification_time=1234567890.0,
            file_size=1024,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )

        assert entry.file_path == Path("/test/file.pdf")
        assert entry.content_hash == "abc123def456"
        assert entry.modification_time == 1234567890.0
        assert entry.file_size == 1024
        assert entry.content == "Test content"
        assert entry.access_count == 0

    def test_cache_entry_validation(self):
        """
        Test validation of cache entry fields
        """
        # Test that string paths are converted to Path objects
        entry = CacheEntry(
            file_path="/test/file.pdf",  # String should be converted to Path
            content_hash="abc123",
            modification_time=1234567890.0,
            file_size=1024,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )
        assert isinstance(entry.file_path, Path)
        assert str(entry.file_path) == "/test/file.pdf"
        
        # Test invalid type raises error
        with pytest.raises(ValueError):
            CacheEntry(
                file_path=123,  # Invalid type
                content_hash="abc123",
                modification_time=1234567890.0,
                file_size=1024,
                content="Test content",
                extraction_timestamp=datetime.now(),
                access_count=0,
                last_accessed=datetime.now(),
            )

    def test_cache_entry_serialization(self):
        """
        Test serialization and deserialization of cache entry
        """
        entry = CacheEntry(
            file_path=Path("/test/file.pdf"),
            content_hash="abc123def456",
            modification_time=1234567890.0,
            file_size=1024,
            content="Test content",
            extraction_timestamp=datetime.now(),
            access_count=5,
            last_accessed=datetime.now(),
        )

        # Convert to dict
        entry_dict = entry.model_dump()
        assert isinstance(entry_dict["file_path"], str)  # Path serialized to string

        # Create from dict
        entry2 = CacheEntry.model_validate(entry_dict)
        assert entry2.file_path == entry.file_path
        assert entry2.content_hash == entry.content_hash


class TestCachedContent:
    """
    Test cases for CachedContent model
    """

    def test_cached_content_creation(self):
        """
        Test creating cached content response
        """
        content = CachedContent(
            content="Extracted text from PDF",
            from_cache=True,
            content_hash="abc123def456",
            extraction_timestamp=datetime.now(),
            file_size=2048,
        )

        assert content.content == "Extracted text from PDF"
        assert content.from_cache is True
        assert content.content_hash == "abc123def456"
        assert content.file_size == 2048

    def test_cached_content_fresh_extraction(self):
        """
        Test cached content for fresh extraction (not from cache)
        """
        content = CachedContent(
            content="Fresh content",
            from_cache=False,
            content_hash="xyz789",
            extraction_timestamp=datetime.now(),
            file_size=512,
        )

        assert content.from_cache is False


class TestIntegrityStatus:
    """
    Test cases for IntegrityStatus enum
    """

    def test_integrity_status_values(self):
        """
        Test all integrity status values exist
        """
        assert IntegrityStatus.VALID.value == "valid"
        assert IntegrityStatus.FILE_MISSING.value == "file_missing"
        assert IntegrityStatus.FILE_MODIFIED.value == "file_modified"
        assert IntegrityStatus.CONTENT_CHANGED.value == "content_changed"
        assert IntegrityStatus.CORRUPTED.value == "corrupted"

    def test_integrity_status_comparison(self):
        """
        Test integrity status comparison
        """
        assert IntegrityStatus.VALID != IntegrityStatus.FILE_MODIFIED
        assert IntegrityStatus.FILE_MISSING != IntegrityStatus.CORRUPTED