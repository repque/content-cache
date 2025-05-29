"""
Tests for the improvements made to the content cache
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from content_cache import (
    CacheConfigurationError,
    CachePermissionError,
    ContentCache,
)
from content_cache.config import CacheConfig


class TestSecurityFeatures:
    """
    Test security improvements
    """

    @pytest.mark.asyncio
    async def test_path_traversal_detection(self):
        """
        Test that path traversal attempts are blocked
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = CacheConfig(cache_dir=Path(tmpdir))
            cache = ContentCache(config)
            await cache.initialize()
            
            # Try path traversal
            malicious_path = Path("../../../etc/passwd")
            
            with pytest.raises(CachePermissionError, match="Path traversal detected"):
                await cache.get_content(malicious_path, lambda p: "content")
            
            await cache.close()

    @pytest.mark.asyncio
    async def test_allowed_paths_restriction(self):
        """
        Test that file access is restricted to allowed paths
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_dir = Path(tmpdir) / "allowed"
            allowed_dir.mkdir()
            
            # Create a file in allowed directory
            allowed_file = allowed_dir / "test.txt"
            allowed_file.write_text("allowed content")
            
            # Create a file outside allowed directory
            outside_file = Path(tmpdir) / "outside.txt"
            outside_file.write_text("outside content")
            
            config = CacheConfig(
                cache_dir=Path(tmpdir) / "cache",
                allowed_paths=[allowed_dir]
            )
            cache = ContentCache(config)
            await cache.initialize()
            
            # Allowed file should work
            async def read_file(p):
                return p.read_text()
            result = await cache.get_content(allowed_file, read_file)
            assert result.content == "allowed content"
            
            # Outside file should be blocked
            with pytest.raises(CachePermissionError, match="not within allowed paths"):
                await cache.get_content(outside_file, read_file)
            
            await cache.close()


class TestConfigurationValidation:
    """
    Test configuration validation
    """

    def test_memory_size_validation(self):
        """
        Test memory size validation
        """
        # Too small
        with pytest.raises(ValueError, match="Memory size must be at least 1MB"):
            CacheConfig(max_memory_size=500_000)
        
        # Too large
        with pytest.raises(ValueError, match="Memory size must not exceed 10GB"):
            CacheConfig(max_memory_size=11 * 1024 * 1024 * 1024)
        
        # Valid
        config = CacheConfig(max_memory_size=100 * 1024 * 1024)
        assert config.max_memory_size == 100 * 1024 * 1024

    def test_compression_level_validation(self):
        """
        Test compression level validation
        """
        # Too low
        with pytest.raises(ValueError, match="Compression level must be between 0 and 9"):
            CacheConfig(compression_level=-1)
        
        # Too high
        with pytest.raises(ValueError, match="Compression level must be between 0 and 9"):
            CacheConfig(compression_level=10)
        
        # Valid
        config = CacheConfig(compression_level=6)
        assert config.compression_level == 6


class TestBatchProcessing:
    """
    Test batch processing features
    """

    @pytest.mark.asyncio
    async def test_batch_get_content(self):
        """
        Test batch content retrieval
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            files = []
            for i in range(5):
                file_path = Path(tmpdir) / f"file{i}.txt"
                file_path.write_text(f"Content {i}")
                files.append(file_path)
            
            config = CacheConfig(cache_dir=Path(tmpdir) / "cache")
            cache = ContentCache(config)
            await cache.initialize()
            
            # Process files in batch
            async def read_file(p):
                return p.read_text()
            
            results = await cache.get_content_batch(
                files,
                read_file,
                max_concurrent=3
            )
            
            assert len(results) == 5
            for i, result in enumerate(results):
                assert result.content == f"Content {i}"
            
            # Second batch should use cache
            results2 = await cache.get_content_batch(files, read_file)
            assert all(r.from_cache for r in results2)
            
            await cache.close()

    @pytest.mark.asyncio
    async def test_batch_invalidate(self):
        """
        Test batch cache invalidation
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            files = []
            for i in range(3):
                file_path = Path(tmpdir) / f"file{i}.txt"
                file_path.write_text(f"Content {i}")
                files.append(file_path)
            
            config = CacheConfig(cache_dir=Path(tmpdir) / "cache")
            cache = ContentCache(config)
            await cache.initialize()
            
            # Cache all files
            async def read_file(p):
                return p.read_text()
            
            for file_path in files:
                await cache.get_content(file_path, read_file)
            
            # Verify they're cached
            for file_path in files:
                result = await cache.get_content(file_path, read_file)
                assert result.from_cache
            
            # Invalidate all
            count = await cache.invalidate_batch(files)
            assert count == 3
            
            # Verify they're no longer cached
            for file_path in files:
                result = await cache.get_content(file_path, read_file)
                assert not result.from_cache
            
            await cache.close()


class TestMetrics:
    """
    Test metrics and monitoring
    """

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """
        Test that metrics are collected correctly
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Test content")
            
            config = CacheConfig(cache_dir=Path(tmpdir) / "cache")
            cache = ContentCache(config)
            await cache.initialize()
            
            # Initial metrics
            stats = await cache.get_statistics()
            assert stats["total_requests"] == 0
            assert stats["cache_hits"] == 0
            assert stats["cache_misses"] == 0
            
            # First request (miss)
            async def read_file(p):
                return p.read_text()
            await cache.get_content(test_file, read_file)
            stats = await cache.get_statistics()
            assert stats["total_requests"] == 1
            assert stats["cache_hits"] == 0
            assert stats["cache_misses"] == 1
            assert stats["hit_rate"] == 0.0
            
            # Second request (hit)
            await cache.get_content(test_file, read_file)
            stats = await cache.get_statistics()
            assert stats["total_requests"] == 2
            assert stats["cache_hits"] == 1
            assert stats["cache_misses"] == 1
            assert stats["hit_rate"] == 0.5
            
            await cache.close()

    @pytest.mark.asyncio
    async def test_bloom_filter_metrics(self):
        """
        Test bloom filter hit tracking
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = CacheConfig(cache_dir=Path(tmpdir))
            cache = ContentCache(config)
            await cache.initialize()
            
            non_existent = Path(tmpdir) / "does_not_exist.txt"
            
            # First check - adds to bloom filter
            with pytest.raises(FileNotFoundError):
                await cache.get_content(non_existent, lambda p: "")
            
            # Second check - should hit bloom filter
            with pytest.raises(FileNotFoundError):
                await cache.get_content(non_existent, lambda p: "")
            
            stats = await cache.get_statistics()
            assert stats["bloom_filter_hits"] == 1
            
            await cache.close()

    @pytest.mark.asyncio
    async def test_prometheus_metrics(self):
        """
        Test Prometheus format export
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = CacheConfig(cache_dir=Path(tmpdir))
            cache = ContentCache(config)
            await cache.initialize()
            
            prometheus_output = cache.get_metrics_prometheus()
            
            # Check for key metrics
            assert "cache_requests_total" in prometheus_output
            assert "cache_hits_total" in prometheus_output
            assert "cache_hit_rate" in prometheus_output
            assert "cache_response_time_seconds" in prometheus_output
            assert "cache_memory_usage_bytes" in prometheus_output
            
            await cache.close()