"""
Main ContentCache implementation
"""
import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pybloom_live import BloomFilter

from .config import CacheConfig
from .exceptions import CachePermissionError
from .file_storage import FileStorage
from .integrity import FileIntegrityChecker
from .memory_cache import MemoryCache
from .metrics import CacheMetrics, MetricsCollector
from .models import CachedContent, CacheEntry, IntegrityStatus
from .sqlite_storage import SQLiteStorage

logger = logging.getLogger(__name__)


class ContentCache:
    """
    High-performance content cache with multi-tier storage.
    
    Intent:
    This class orchestrates a sophisticated caching system designed to eliminate
    redundant file processing operations. By maintaining multiple storage tiers
    (memory, SQLite, compressed blobs) and intelligent change detection, it ensures
    that file content extraction only happens when absolutely necessary.
    
    The cache operates on the principle that file processing (especially for formats
    like PDF) is expensive, but content rarely changes. By tracking file hashes and
    modification times, we can serve cached results with sub-millisecond latency
    while guaranteeing freshness.
    
    Key Design Decisions:
    - Multi-tier storage balances speed vs capacity
    - Async architecture supports high concurrency
    - File-level locking prevents duplicate processing
    - Bloom filters reduce I/O for non-existent files
    - Content hashing enables deduplication across file paths
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        """
        Initialize content cache with configuration.
        
        Intent:
        Sets up the cache infrastructure without performing any I/O operations.
        This lazy initialization pattern allows the cache to be created quickly
        and initialized only when first used, supporting dependency injection
        and testing scenarios.
        
        Args:
            config: Cache configuration object. If None, uses sensible defaults.
                   Allows customization of storage paths, memory limits, and
                   performance tuning parameters.
        """
        self.config = config or CacheConfig()
        self._initialized = False

        # Components
        self.memory_cache = MemoryCache(self.config.max_memory_size)
        self.sqlite_storage: Optional[SQLiteStorage] = None
        self.file_storage: Optional[FileStorage] = None
        self.integrity_checker = FileIntegrityChecker(self.config.verify_hash)

        # Bloom filter for negative cache (non-existent files)
        self.bloom_filter = BloomFilter(
            capacity=self.config.bloom_filter_size,
            error_rate=0.001
        )

        # Metrics
        self.metrics = CacheMetrics()

        # Locks for thread safety
        self._processing_locks: dict[Path, asyncio.Lock] = {}
        self._lock_manager = asyncio.Lock()

    async def initialize(self) -> None:
        """
        Initialize all cache components.
        
        Intent:
        Performs the actual setup of storage components that require I/O operations.
        This includes creating the cache directory structure, initializing the
        SQLite database with proper schema, and setting up blob storage.
        
        Called automatically on first cache access to ensure components are ready.
        Idempotent - safe to call multiple times.
        
        Raises:
            CacheStorageError: If unable to create cache directory or initialize storage
        """
        if self._initialized:
            return

        # Ensure cache directory exists
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize storage components
        db_path = self.config.cache_dir / "cache.db"
        self.sqlite_storage = SQLiteStorage(db_path, self.config.db_pool_size)
        await self.sqlite_storage.initialize()

        blob_dir = self.config.cache_dir / "blobs"
        self.file_storage = FileStorage(blob_dir, self.config.compression_level)

        self._initialized = True

    async def get_content(
        self,
        file_path: Path,
        process_callback: Callable[[Path], str]
    ) -> CachedContent:
        """
        Get content from cache or process file if needed.
        
        Intent:
        This is the primary cache interface that implements the core caching logic.
        It follows a cascading lookup strategy: memory → SQLite → blob storage,
        only falling back to expensive file processing when cache misses occur.
        
        The method guarantees content freshness by validating file integrity
        (modification time and optionally content hash) before serving cached results.
        File-level locking prevents duplicate processing when multiple requests
        for the same file arrive concurrently.
        
        Args:
            file_path: Path to the file whose content should be retrieved
            process_callback: Function that extracts content from the file.
                            Only called on cache misses. Should be idempotent.
        
        Returns:
            CachedContent object containing the extracted content and metadata
            indicating whether it was served from cache
        
        Raises:
            FileNotFoundError: If the file doesn't exist
            CachePermissionError: If file access is denied or path is invalid
            CacheProcessingError: If the process_callback fails
        """
        if not self._initialized:
            await self.initialize()

        with MetricsCollector(self.metrics) as collector:
            # Validate file path for security
            self._validate_file_path(file_path)

            # Check bloom filter first for non-existent files
            file_path_str = str(file_path)
            if file_path_str in self.bloom_filter and not file_path.exists():
                self.metrics.bloom_filter_hits += 1
                raise FileNotFoundError(f"File not found: {file_path}")

            # Ensure file exists
            if not file_path.exists():
                # Add to bloom filter to avoid repeated checks
                self.bloom_filter.add(file_path_str)
                raise FileNotFoundError(f"File not found: {file_path}")

            # Get a lock for this specific file to prevent duplicate processing
            file_lock = await self._get_file_lock(file_path)

            async with file_lock:
                # Try to get from memory cache
                cached_content = await self._check_memory_cache(file_path)
                if cached_content:
                    collector.mark_cache_hit()
                    return cached_content

                # Try to get from persistent cache
                cached_content = await self._check_persistent_cache(file_path)
                if cached_content:
                    collector.mark_cache_hit()
                    return cached_content

                # Cache miss - process and cache the file
                return await self._process_and_cache(file_path, process_callback)

    async def _get_file_lock(self, file_path: Path) -> asyncio.Lock:
        """
        Get or create a lock for the specific file.
        
        Intent:
        Prevents duplicate processing when multiple concurrent requests arrive
        for the same file. Each file gets its own lock to avoid blocking unrelated
        operations. The lock manager itself is protected to prevent race conditions
        in lock creation.
        
        This pattern is crucial for performance - without it, concurrent requests
        for uncached files would each trigger expensive processing operations.
        
        Args:
            file_path: Path to get/create lock for
            
        Returns:
            Asyncio lock specific to this file path
        """
        async with self._lock_manager:
            if file_path not in self._processing_locks:
                self._processing_locks[file_path] = asyncio.Lock()
            return self._processing_locks[file_path]

    async def _check_memory_cache(self, file_path: Path) -> Optional[CachedContent]:
        """
        Check memory cache for the file.
        
        Intent:
        First tier lookup in the caching hierarchy. Memory cache provides
        sub-millisecond access times but limited capacity. This method performs
        integrity validation to ensure cached content is still valid before
        returning it.
        
        The integrity check is crucial because files can be modified externally
        without the cache being notified. Rather than serving stale content,
        we validate and invalidate when necessary.
        
        Args:
            file_path: Path to look up in memory cache
            
        Returns:
            CachedContent if found and valid, None if not found or invalid
        """
        cached_entry = await self.memory_cache.get(file_path)
        if not cached_entry:
            return None

        # Verify integrity
        integrity_status = await self.integrity_checker.check_integrity(cached_entry)
        if integrity_status == IntegrityStatus.VALID:
            return CachedContent(
                content=cached_entry.content,
                from_cache=True,
                content_hash=cached_entry.content_hash,
                extraction_timestamp=cached_entry.extraction_timestamp,
                file_size=cached_entry.file_size,
            )
        return None

    async def _check_persistent_cache(self, file_path: Path) -> Optional[CachedContent]:
        """
        Check persistent storage (SQLite + blob storage) for the file.
        
        Intent:
        Second tier lookup that checks SQLite database and blob storage for
        cached content. This tier survives application restarts but has higher
        latency than memory cache. Large content is stored in compressed blobs
        to keep the SQLite database manageable.
        
        On successful retrieval, content is promoted to memory cache for faster
        future access. This implements a natural heat-based promotion strategy
        where frequently accessed content stays in faster tiers.
        
        Args:
            file_path: Path to look up in persistent storage
            
        Returns:
            CachedContent if found and valid, None if not found or invalid
        """
        cached_entry = await self.sqlite_storage.get(file_path)
        if not cached_entry:
            return None

        # Verify integrity
        integrity_status = await self.integrity_checker.check_integrity(cached_entry)
        if integrity_status != IntegrityStatus.VALID:
            return None

        # Load content from blob storage if needed
        if cached_entry.content_blob_path and not cached_entry.content:
            content = await self.file_storage.retrieve(cached_entry.content_hash)
            if content:
                cached_entry.content = content

        if cached_entry.content:
            # Add to memory cache for faster future access
            await self._add_to_memory_cache(cached_entry)

            return CachedContent(
                content=cached_entry.content,
                from_cache=True,
                content_hash=cached_entry.content_hash,
                extraction_timestamp=cached_entry.extraction_timestamp,
                file_size=cached_entry.file_size,
            )
        return None

    async def _add_to_memory_cache(self, entry: CacheEntry) -> None:
        """
        Add entry to memory cache.
        
        Intent:
        Promotes content to the fastest cache tier for future access.
        Creates a new CacheEntry object to avoid sharing mutable state between
        cache tiers. The memory cache will handle LRU eviction automatically
        when capacity limits are reached.
        
        This promotion strategy ensures frequently accessed content remains
        in the fastest tier while less popular content naturally ages out.
        
        Args:
            entry: Cache entry to add to memory cache
        """
        memory_entry = CacheEntry(
            file_path=entry.file_path,
            content_hash=entry.content_hash,
            modification_time=entry.modification_time,
            file_size=entry.file_size,
            content=entry.content,
            extraction_timestamp=entry.extraction_timestamp,
            access_count=entry.access_count,
            last_accessed=entry.last_accessed,
        )
        await self.memory_cache.add(memory_entry)

    async def _process_and_cache(
        self,
        file_path: Path,
        process_callback: Callable[[Path], str]
    ) -> CachedContent:
        """
        Process file and store in cache.
        
        Intent:
        Handles cache misses by invoking the user-provided processing function
        and storing the results in appropriate cache tiers. This is the most
        expensive code path, so it's only executed when absolutely necessary.
        
        The method captures file metadata (size, modification time) and computes
        content hash for future integrity checks. Content is stored in the most
        appropriate tier based on size - large content goes to blob storage to
        avoid bloating the SQLite database.
        
        Args:
            file_path: Path to the file to process
            process_callback: User function that extracts content from the file
            
        Returns:
            CachedContent with from_cache=False indicating fresh processing
        """

        # Compute file hash
        file_hash = await self.integrity_checker._compute_file_hash(file_path)

        # Process content
        content = await process_callback(file_path)

        # Create cache entry
        stat = file_path.stat()
        entry = CacheEntry(
            file_path=file_path,
            content_hash=file_hash,
            modification_time=stat.st_mtime,
            file_size=stat.st_size,
            content=content,
            extraction_timestamp=datetime.now(),
            access_count=0,
            last_accessed=datetime.now(),
        )

        # Store in appropriate tier
        await self._store_in_cache(entry, content)

        return CachedContent(
            content=content,
            from_cache=False,
            content_hash=file_hash,
            extraction_timestamp=entry.extraction_timestamp,
            file_size=entry.file_size,
        )

    async def _store_in_cache(self, entry: CacheEntry, content: str) -> None:
        """
        Store entry in appropriate cache tiers.
        
        Intent:
        Implements intelligent storage tier selection based on content size.
        Small content is stored directly in SQLite for fast access, while large
        content is compressed and stored as blobs with only metadata in SQLite.
        
        This hybrid approach balances query performance (SQLite is fast for
        small content) with storage efficiency (compression helps with large
        content). All content under the threshold also gets promoted to memory
        cache for immediate future access.
        
        Args:
            entry: Cache entry metadata
            content: Extracted content to store
        """
        # Store large content in file system
        if len(content) > SQLiteStorage.LARGE_CONTENT_THRESHOLD:
            blob_path = await self.file_storage.store(entry.content_hash, content)
            entry.content_blob_path = blob_path
            entry.content = None  # Don't store in SQLite

        # Store in SQLite
        await self.sqlite_storage.add(entry)

        # Store in memory cache if small enough
        if len(content) <= SQLiteStorage.LARGE_CONTENT_THRESHOLD:
            entry.content = content  # Restore content for memory cache
            await self._add_to_memory_cache(entry)

    async def get_content_batch(
        self,
        file_paths: Sequence[Path],
        process_callback: Callable[[Path], str],
        max_concurrent: int = 10
    ) -> list[CachedContent]:
        """
        Process multiple files efficiently with controlled concurrency.
        
        Intent:
        Enables efficient batch processing while preventing resource exhaustion.
        Uses a semaphore to limit concurrent operations, preventing the system
        from being overwhelmed when processing large batches of files.
        
        This is particularly important for file processing operations which can
        be I/O and CPU intensive. The concurrency limit allows tuning based on
        system capabilities and downstream service limits.
        
        Args:
            file_paths: Sequence of file paths to process
            process_callback: Function to extract content from each file
            max_concurrent: Maximum number of concurrent processing operations
            
        Returns:
            List of CachedContent objects in the same order as input paths
        """
        # Use semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(file_path: Path) -> CachedContent:
            async with semaphore:
                return await self.get_content(file_path, process_callback)

        # Process all files concurrently
        tasks = [process_with_semaphore(path) for path in file_paths]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def invalidate(self, file_path: Path) -> None:
        """
        Invalidate cache entry for a specific file.
        
        Intent:
        Forcibly removes a file from all cache tiers when you know the content
        has changed or become invalid. This is useful for programmatic cache
        management when external processes modify files.
        
        The method ensures complete cleanup by removing from memory cache,
        deleting any blob storage files, and removing SQLite records. This
        prevents storage leaks and ensures the next access will trigger
        fresh processing.
        
        Args:
            file_path: Path of file to remove from cache
        """
        # Remove from memory cache
        await self.memory_cache.remove(file_path)

        # Get entry to check for blob storage
        entry = await self.sqlite_storage.get(file_path)
        if entry and entry.content_blob_path:
            # Delete blob file
            await self.file_storage.delete(entry.content_hash)

        # Remove from SQLite
        await self.sqlite_storage.remove(file_path)

    async def invalidate_batch(self, file_paths: Sequence[Path]) -> int:
        """
        Invalidate multiple cache entries.
        
        Intent:
        Efficiently removes multiple files from cache, useful for bulk operations
        like clearing cache for an entire directory. Processes invalidations
        concurrently for better performance while gracefully handling individual
        failures.
        
        Args:
            file_paths: Sequence of file paths to invalidate
            
        Returns:
            Number of entries invalidated (always equals input length)
        """
        tasks = [self.invalidate(path) for path in file_paths]
        await asyncio.gather(*tasks, return_exceptions=True)
        return len(file_paths)

    async def clear_old_entries(self, days: int) -> int:
        """
        Clear entries not accessed within specified days.
        
        Intent:
        Implements automatic cache cleanup based on access patterns rather than
        just creation time. This ensures frequently accessed content remains
        cached while stale content is removed to free storage space.
        
        This is more intelligent than simple time-based expiration because it
        considers actual usage patterns. A file cached months ago but accessed
        yesterday is more valuable than a file cached yesterday but never accessed.
        
        Args:
            days: Number of days since last access for cleanup threshold
            
        Returns:
            Number of entries removed from cache
        """
        # Clear from SQLite (this returns the count)
        removed = await self.sqlite_storage.clear_old_entries(days)

        # Clear from memory cache
        await self.memory_cache.clear()

        return removed

    async def get_statistics(self) -> dict:
        """
        Get comprehensive cache statistics.
        
        Intent:
        Provides comprehensive metrics for cache performance monitoring and
        capacity planning. Calculates advanced metrics like duplicate detection
        (files with identical content) which helps understand storage efficiency.
        
        The statistics help operators understand cache effectiveness, identify
        opportunities for optimization, and plan capacity requirements. Duplicate
        group detection reveals how much storage is saved through deduplication.
        
        Returns:
            Dictionary containing cache performance and utilization metrics
        """
        # Get SQLite statistics
        db_stats = await self.sqlite_storage.get_statistics()

        # Calculate duplicate groups
        all_entries = await self.sqlite_storage.get_all()
        hash_groups = {}
        for entry in all_entries:
            if entry.content_hash not in hash_groups:
                hash_groups[entry.content_hash] = []
            hash_groups[entry.content_hash].append(entry.file_path)

        duplicate_groups = sum(1 for paths in hash_groups.values() if len(paths) > 1)

        # Update metrics with current storage info
        self.metrics.memory_usage_bytes = self.memory_cache.current_size_bytes
        self.metrics.total_entries = db_stats["total_entries"]
        self.metrics.disk_usage_bytes = db_stats["total_size"]

        # Get base metrics dict and add additional info
        stats = self.metrics.to_dict()
        stats.update({
            "memory_entries": len(self.memory_cache.entries),
            "unique_hashes": db_stats["unique_hashes"],
            "duplicate_groups": duplicate_groups,
        })

        return stats

    def get_metrics_prometheus(self) -> str:
        """
        Get metrics in Prometheus format.
        
        Intent:
        Exports cache metrics in Prometheus format for integration with
        monitoring systems. This enables alerting on cache performance issues,
        capacity problems, and trending analysis over time.
        
        Prometheus format is the de facto standard for cloud-native monitoring,
        making it easy to integrate with existing observability infrastructure.
        
        Returns:
            String containing metrics in Prometheus exposition format
        """
        return self.metrics.to_prometheus()

    def _validate_file_path(self, file_path: Path) -> None:
        """
        Validate file path for security - prevent path traversal attacks.
        
        Intent:
        Implements security controls to prevent malicious file path manipulation.
        Path traversal attacks (../) could allow access to files outside intended
        directories, potentially exposing sensitive system files.
        
        The validation includes:
        - Path traversal detection (".." sequences)
        - Path resolution to catch encoded traversals
        - Allowlist enforcement if configured
        
        This is critical for any application that accepts user-provided file paths,
        as it prevents common file system security vulnerabilities.
        
        Args:
            file_path: Path to validate
            
        Raises:
            CachePermissionError: If path is invalid or access is denied
        """
        # Resolve to absolute path
        try:
            abs_path = file_path.resolve(strict=False)
        except Exception as e:
            raise CachePermissionError(f"Invalid file path: {file_path}") from e

        # Check for path traversal attempts
        if ".." in str(file_path):
            raise CachePermissionError(f"Path traversal detected: {file_path}")

        # If allowed paths are configured, check if file is within them
        if self.config.allowed_paths:
            is_allowed = any(
                abs_path.is_relative_to(allowed_path.resolve())
                for allowed_path in self.config.allowed_paths
            )
            if not is_allowed:
                raise CachePermissionError(
                    f"Access denied: {file_path} is not within allowed paths"
                )

    async def close(self) -> None:
        """
        Close all cache components.
        
        Intent:
        Performs graceful shutdown of all cache components, ensuring data
        integrity and resource cleanup. This includes closing database connections,
        flushing any pending writes, and releasing system resources.
        
        Should be called when the cache is no longer needed to prevent resource
        leaks and ensure data consistency. Safe to call multiple times.
        """
        if self.sqlite_storage:
            await self.sqlite_storage.close()

