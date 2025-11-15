"""
In-memory LRU cache implementation
"""
import asyncio
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import CacheEntry


class MemoryCache:
    """
    Thread-safe in-memory cache with LRU eviction policy.

    Intent:
    Provides the fastest possible access to frequently used cache entries by
    keeping them in memory. Uses LRU (Least Recently Used) eviction to automatically
    manage memory usage while keeping hot data accessible.

    Key design decisions:
    - OrderedDict provides O(1) access with efficient LRU ordering
    - Size tracking prevents uncontrolled memory growth
    - Async locks ensure thread safety in concurrent environments
    - Access tracking updates on every retrieval for accurate LRU behavior

    The cache acts as the first tier in a multi-level storage hierarchy,
    providing sub-millisecond access times for recently accessed content.
    """

    def __init__(self, max_size_bytes: int):
        """
        Initialize memory cache with size limit.

        Intent:
        Sets up the cache infrastructure with a configurable memory limit.
        The size limit prevents the cache from consuming unlimited memory,
        which is crucial in production environments where memory is shared
        with other processes.

        Args:
            max_size_bytes: Maximum memory usage in bytes. When exceeded,
                          LRU entries are evicted to make space.
        """
        self.max_size_bytes = max_size_bytes
        self.current_size_bytes = 0
        self.entries: OrderedDict[Path, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def add(self, entry: CacheEntry) -> None:
        """
        Add entry to cache, evicting LRU entries if needed.

        Intent:
        Implements intelligent cache admission and eviction policies. Large
        entries that exceed the total cache size are rejected to prevent
        thrashing. Otherwise, LRU entries are evicted as needed to make space.

        The method ensures the cache never exceeds its memory limit while
        maintaining optimal access patterns through LRU ordering. Existing
        entries are updated rather than duplicated.

        Args:
            entry: Cache entry to add. If larger than max cache size, it's ignored.
        """
        async with self._lock:
            # Calculate entry size
            entry_size = self._calculate_entry_size(entry)

            # If entry is larger than max cache size, don't cache it
            if entry_size > self.max_size_bytes:
                return

            # Remove existing entry if present
            if entry.file_path in self.entries:
                await self._remove_internal(entry.file_path)

            # Evict entries until we have space
            while self.current_size_bytes + entry_size > self.max_size_bytes and self.entries:
                # Remove least recently used (first item)
                lru_path = next(iter(self.entries))
                await self._remove_internal(lru_path)

            # Add new entry
            self.entries[entry.file_path] = entry
            self.current_size_bytes += entry_size

            # Move to end (most recently used)
            self.entries.move_to_end(entry.file_path)

    async def get(self, file_path: Path) -> Optional[CacheEntry]:
        """
        Get entry from cache and update access order.

        Intent:
        Retrieves cached content while maintaining accurate LRU ordering.
        Every access updates both the LRU position and access tracking metadata,
        ensuring the cache reflects actual usage patterns.

        The access tracking (count, timestamp) provides valuable analytics data
        and supports more sophisticated eviction policies in the future.

        Args:
            file_path: Path of file to retrieve from cache

        Returns:
            CacheEntry if found, None if not in cache
        """
        async with self._lock:
            if file_path not in self.entries:
                return None

            entry = self.entries[file_path]

            # Update access tracking
            entry.access_count += 1
            entry.last_accessed = datetime.now()

            # Move to end (most recently used)
            self.entries.move_to_end(file_path)

            return entry

    async def remove(self, file_path: Path) -> bool:
        """
        Remove specific entry from cache.

        Intent:
        Provides explicit cache invalidation for cases where content is known
        to be stale or invalid. This is essential for maintaining cache
        consistency when files are modified externally.

        Args:
            file_path: Path of file to remove from cache

        Returns:
            True if entry was removed, False if not found
        """
        async with self._lock:
            return await self._remove_internal(file_path)

    async def _remove_internal(self, file_path: Path) -> bool:
        """
        Internal method to remove entry without lock.

        Intent:
        Provides lock-free removal for use within other locked methods.
        This prevents deadlocks when removal is needed as part of larger
        operations (like eviction during add).

        Maintains accurate size tracking by calculating entry size before
        removal. This is critical for proper memory limit enforcement.

        Args:
            file_path: Path of file to remove

        Returns:
            True if entry was removed, False if not found
        """
        if file_path not in self.entries:
            return False

        entry = self.entries[file_path]
        entry_size = self._calculate_entry_size(entry)

        del self.entries[file_path]
        self.current_size_bytes -= entry_size

        return True

    async def clear(self) -> None:
        """
        Clear all entries from cache.

        Intent:
        Provides bulk cache invalidation for maintenance operations or
        when cache consistency can't be guaranteed. Efficiently resets
        both the entry storage and size tracking.

        Used during cache cleanup operations and for testing scenarios
        where a clean slate is needed.
        """
        async with self._lock:
            self.entries.clear()
            self.current_size_bytes = 0

    def _calculate_entry_size(self, entry: CacheEntry) -> int:
        """
        Calculate approximate memory size of cache entry.

        Intent:
        Provides reasonably accurate memory usage estimation for cache entries.
        While not perfect (Python's memory model is complex), this gives a
        good approximation for memory limit enforcement.

        The calculation includes:
        - Base object overhead
        - String content (the largest component)
        - Path strings and metadata

        This size tracking is essential for preventing memory exhaustion
        while maintaining predictable cache behavior.

        Args:
            entry: Cache entry to measure

        Returns:
            Approximate memory usage in bytes
        """
        # Base size of the object
        size = sys.getsizeof(entry)

        # Add size of string content if present
        if entry.content:
            size += sys.getsizeof(entry.content)

        # Add size of path strings
        size += sys.getsizeof(str(entry.file_path))
        if entry.content_blob_path:
            size += sys.getsizeof(str(entry.content_blob_path))

        # Add size of other string fields
        size += sys.getsizeof(entry.content_hash)

        return size

