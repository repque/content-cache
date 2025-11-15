"""
Tests for file integrity checking functionality
"""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from content_cache.integrity import FileIntegrityChecker
from content_cache.models import CacheEntry, IntegrityStatus


@pytest.fixture
def temp_file():
    """
    Create a temporary file for testing
    """
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"Test content for integrity checking")
        temp_path = Path(tf.name)
    yield temp_path
    try:
        temp_path.unlink()
    except FileNotFoundError:
        pass  # File already deleted in test


@pytest.fixture
def sample_cache_entry(temp_file):
    """
    Create a sample cache entry for testing
    """
    return CacheEntry(
        file_path=temp_file,
        content_hash="abc123def456789",
        modification_time=temp_file.stat().st_mtime,
        file_size=temp_file.stat().st_size,
        content="Test content",
        extraction_timestamp=datetime.now(),
        access_count=0,
        last_accessed=datetime.now(),
    )


class TestFileIntegrityChecker:
    """
    Test cases for FileIntegrityChecker
    """

    @pytest.mark.asyncio
    async def test_valid_file_quick_check(self, sample_cache_entry, temp_file):
        """
        Test quick integrity check for valid unchanged file
        """
        checker = FileIntegrityChecker(verify_hash=False)
        status = await checker.check_integrity(sample_cache_entry)
        assert status == IntegrityStatus.VALID

    @pytest.mark.asyncio
    async def test_missing_file_detection(self, sample_cache_entry):
        """
        Test detection of missing files
        """
        # Delete the file
        sample_cache_entry.file_path.unlink()
        
        checker = FileIntegrityChecker(verify_hash=False)
        status = await checker.check_integrity(sample_cache_entry)
        assert status == IntegrityStatus.FILE_MISSING

    @pytest.mark.asyncio
    async def test_modified_file_detection(self, sample_cache_entry, temp_file):
        """
        Test detection of modified files based on mtime
        """
        # Simulate file modification by changing mtime
        original_mtime = temp_file.stat().st_mtime
        sample_cache_entry.modification_time = original_mtime - 100  # Old mtime
        
        checker = FileIntegrityChecker(verify_hash=False)
        status = await checker.check_integrity(sample_cache_entry)
        assert status == IntegrityStatus.FILE_MODIFIED

    @pytest.mark.asyncio
    async def test_hash_verification_valid(self, sample_cache_entry, temp_file):
        """
        Test hash verification for unchanged content
        """
        # Mock the hash computation to return expected hash
        checker = FileIntegrityChecker(verify_hash=True)
        
        with patch.object(checker, 'compute_file_hash', 
                         return_value="abc123def456789"):
            status = await checker.check_integrity(sample_cache_entry)
            assert status == IntegrityStatus.VALID

    @pytest.mark.asyncio
    async def test_hash_verification_changed(self, sample_cache_entry, temp_file):
        """
        Test hash verification detects content changes
        """
        checker = FileIntegrityChecker(verify_hash=True)
        
        # Mock hash computation to return different hash
        with patch.object(checker, 'compute_file_hash', 
                         return_value="different_hash"):
            status = await checker.check_integrity(sample_cache_entry)
            assert status == IntegrityStatus.CONTENT_CHANGED

    @pytest.mark.asyncio
    async def testcompute_file_hash(self, temp_file):
        """
        Test actual file hash computation
        """
        checker = FileIntegrityChecker(verify_hash=True)
        hash1 = await checker.compute_file_hash(temp_file)
        hash2 = await checker.compute_file_hash(temp_file)
        
        # Same file should produce same hash
        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA-256 produces 64 character hex string

    @pytest.mark.asyncio
    async def testcompute_file_hash_large_file(self):
        """
        Test hash computation for large files
        """
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            # Write 10MB of data
            data = b"x" * (10 * 1024 * 1024)
            tf.write(data)
            large_file = Path(tf.name)
        
        try:
            checker = FileIntegrityChecker(verify_hash=True)
            hash_result = await checker.compute_file_hash(large_file)
            assert isinstance(hash_result, str)
            assert len(hash_result) == 64
        finally:
            large_file.unlink()

    @pytest.mark.asyncio
    async def test_batch_integrity_check(self):
        """
        Test checking integrity of multiple entries
        """
        # Create multiple temporary files
        temp_files = []
        entries = []
        
        try:
            for i in range(3):
                with tempfile.NamedTemporaryFile(delete=False) as tf:
                    tf.write(f"Content {i}".encode())
                    tf.flush()  # Ensure data is written
                    temp_path = Path(tf.name)
                    temp_files.append(temp_path)
                
                # Get stats after file is closed
                stat = temp_path.stat()
                entries.append(CacheEntry(
                    file_path=temp_path,
                    content_hash=f"hash_{i}",
                    modification_time=stat.st_mtime,
                    file_size=stat.st_size,
                    content=f"Content {i}",
                    extraction_timestamp=datetime.now(),
                    access_count=i,
                    last_accessed=datetime.now(),
                ))
            
            checker = FileIntegrityChecker(verify_hash=False)
            results = await checker.check_batch(entries)
            
            assert len(results) == 3
            assert all(status == IntegrityStatus.VALID for status in results.values())
        finally:
            # Clean up all temp files
            for temp_file in temp_files:
                try:
                    temp_file.unlink()
                except FileNotFoundError:
                    pass