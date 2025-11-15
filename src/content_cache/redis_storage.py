"""
Redis-based persistent storage for cache entries.
"""
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import CacheEntry


class RedisStorage:
    """
    Redis-based persistent storage for cache entries.

    Implements: IStorage interface

    Intent:
    Provides distributed, high-performance storage for cache entries that can
    be shared across multiple processes and machines. Uses Redis for its excellent
    concurrency handling, atomic operations, and built-in LRU eviction.

    Key design decisions:
    - Redis hashes for structured entry storage
    - Atomic operations for statistics (INCR, HINCRBY)
    - Hybrid storage: small content in Redis, large content as external blobs
    - JSON serialization for complex data types
    - Key prefixing for namespace isolation

    Redis is ideal for multi-process deployments where cache sharing eliminates
    duplicate processing. For single-process applications, SQLiteStorage may be
    more efficient due to lower overhead.
    """

    LARGE_CONTENT_THRESHOLD = 1024 * 1024  # 1MB

    def __init__(self, redis_client, key_prefix: str = "cache"):
        """
        Initialize Redis storage.

        Intent:
        Sets up Redis-based storage with an existing Redis client. Requires
        the client to be passed in to support different Redis configurations
        (standalone, cluster, sentinel) and async implementations.

        Args:
            redis_client: Async Redis client (redis.asyncio.Redis)
            key_prefix: Prefix for all Redis keys (for namespace isolation)
        """
        self.redis = redis_client
        self.key_prefix = key_prefix
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize Redis storage.

        Intent:
        Performs one-time setup to verify Redis connectivity and initialize
        global statistics. Unlike SQLiteStorage, no schema creation is needed
        as Redis is schemaless.

        Called once during cache initialization to prepare the storage layer.
        Idempotent - safe to call multiple times.
        """
        if self._initialized:
            return

        # Verify Redis connection
        await self.redis.ping()

        # Initialize statistics if they don't exist
        stats_key = f"{self.key_prefix}:stats"
        if not await self.redis.exists(stats_key):
            await self.redis.hset(
                stats_key,
                mapping={
                    "total_entries": 0,
                    "total_size": 0,
                    "total_access_count": 0,
                },
            )

        self._initialized = True

    def _entry_key(self, file_path: Path) -> str:
        """
        Generate Redis key for a cache entry.

        Intent:
        Creates consistent, namespaced keys for cache entries. Using file path
        as the key component ensures natural lookup patterns and prevents
        key collisions.

        Args:
            file_path: File path to generate key for

        Returns:
            Redis key string
        """
        return f"{self.key_prefix}:entry:{file_path}"

    def _serialize_entry(self, entry: CacheEntry) -> dict[str, str]:
        """
        Convert CacheEntry to Redis hash mapping.

        Intent:
        Serializes cache entry metadata to Redis-compatible string values.
        Uses JSON for complex types (datetime, Path) to maintain type
        information while keeping Redis keys simple.

        Args:
            entry: Cache entry to serialize

        Returns:
            Dictionary mapping field names to string values
        """
        # Determine content storage strategy
        content_to_store = None
        blob_path_str = None

        if entry.content and len(entry.content) <= self.LARGE_CONTENT_THRESHOLD:
            # Small content: store directly in Redis
            content_to_store = entry.content
        elif entry.content_blob_path:
            # Large content: only store blob path reference
            blob_path_str = str(entry.content_blob_path)

        mapping = {
            "content_hash": entry.content_hash,
            "modification_time": str(entry.modification_time),
            "file_size": str(entry.file_size),
            "extraction_timestamp": entry.extraction_timestamp.isoformat(),
            "access_count": str(entry.access_count),
            "last_accessed": entry.last_accessed.isoformat(),
        }

        if content_to_store is not None:
            mapping["content"] = content_to_store

        if blob_path_str is not None:
            mapping["content_blob_path"] = blob_path_str

        return mapping

    def _deserialize_entry(self, file_path: Path, data: dict) -> CacheEntry:
        """
        Convert Redis hash mapping to CacheEntry.

        Intent:
        Reconstructs cache entry objects from Redis storage. Handles type
        conversion from strings back to proper Python types (int, float, datetime).

        Args:
            file_path: File path for the entry
            data: Redis hash data (bytes values from Redis)

        Returns:
            Reconstructed CacheEntry object
        """
        # Decode bytes to strings if needed
        if isinstance(next(iter(data.values())), bytes):
            data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in data.items()}

        return CacheEntry(
            file_path=file_path,
            content_hash=data["content_hash"],
            modification_time=float(data["modification_time"]),
            file_size=int(data["file_size"]),
            content=data.get("content"),
            content_blob_path=Path(data["content_blob_path"]) if "content_blob_path" in data else None,
            extraction_timestamp=datetime.fromisoformat(data["extraction_timestamp"]),
            access_count=int(data["access_count"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
        )

    async def add(self, entry: CacheEntry) -> None:
        """
        Add or update cache entry.

        Intent:
        Stores cache entries in Redis while preserving access counts across
        updates. Uses atomic operations to maintain statistics consistency
        even under high concurrency.

        For updates, the access count is preserved from the existing entry to
        maintain accurate usage statistics. This ensures that content updates
        don't reset the entry's priority.

        Args:
            entry: Cache entry to store. Content may be None if stored externally.
        """
        entry_key = self._entry_key(entry.file_path)

        # Check if entry exists to preserve access_count
        existing = await self.redis.hget(entry_key, "access_count")
        if existing:
            # Update entry while preserving access count
            mapping = self._serialize_entry(entry)
            mapping["access_count"] = existing.decode() if isinstance(existing, bytes) else existing
            await self.redis.hset(entry_key, mapping=mapping)
        else:
            # New entry - increment total entries count
            await self.redis.hset(entry_key, mapping=self._serialize_entry(entry))
            await self.redis.hincrby(f"{self.key_prefix}:stats", "total_entries", 1)

        # Update total size statistics
        await self.redis.hincrby(
            f"{self.key_prefix}:stats",
            "total_size",
            entry.file_size,
        )

    async def get(self, file_path: Path) -> Optional[CacheEntry]:
        """
        Get cache entry by file path.

        Intent:
        Primary lookup method for retrieving cached content by file path.
        Returns None if the entry doesn't exist, making it easy to distinguish
        cache misses from errors.

        Args:
            file_path: Path of file to retrieve

        Returns:
            CacheEntry if found, None if not in cache
        """
        entry_key = self._entry_key(file_path)
        data = await self.redis.hgetall(entry_key)

        if not data:
            return None

        return self._deserialize_entry(file_path, data)

    async def get_all(self) -> list[CacheEntry]:
        """
        Get all cache entries.

        Intent:
        Provides bulk access to all cached content for analytics, migration,
        or administrative operations. Uses Redis SCAN to avoid blocking the
        server with large result sets.

        Results are sorted by file path for consistent ordering and easier
        analysis of cache contents.

        Returns:
            List of all cache entries in Redis
        """
        entries = []
        pattern = f"{self.key_prefix}:entry:*"

        # Use SCAN to iterate over keys without blocking
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            # Fetch all entries in parallel
            if keys:
                pipeline = self.redis.pipeline()
                for key in keys:
                    pipeline.hgetall(key)
                results = await pipeline.execute()

                # Deserialize entries
                for key, data in zip(keys, results):
                    if data:
                        # Extract file path from key
                        key_str = key.decode() if isinstance(key, bytes) else key
                        file_path_str = key_str.replace(f"{self.key_prefix}:entry:", "")
                        entries.append(self._deserialize_entry(Path(file_path_str), data))

            if cursor == 0:
                break

        # Sort by file path for consistency
        entries.sort(key=lambda e: str(e.file_path))
        return entries

    async def remove(self, file_path: Path) -> bool:
        """
        Remove cache entry.

        Intent:
        Provides explicit cache invalidation for specific files. Updates
        statistics atomically to maintain consistency. Returns success status
        to help callers understand whether the operation had any effect.

        Args:
            file_path: Path of file to remove from cache

        Returns:
            True if an entry was removed, False if path wasn't cached
        """
        entry_key = self._entry_key(file_path)

        # Get file size before deletion for statistics update
        data = await self.redis.hgetall(entry_key)
        if not data:
            return False

        # Decode file_size
        file_size_bytes = data.get(b"file_size") or data.get("file_size")
        if isinstance(file_size_bytes, bytes):
            file_size = int(file_size_bytes.decode())
        else:
            file_size = int(file_size_bytes)

        # Delete entry
        deleted = await self.redis.delete(entry_key)

        if deleted:
            # Update statistics
            await self.redis.hincrby(f"{self.key_prefix}:stats", "total_entries", -1)
            await self.redis.hincrby(f"{self.key_prefix}:stats", "total_size", -file_size)

        return bool(deleted)

    async def clear_old_entries(self, days: int) -> int:
        """
        Remove entries not accessed within specified days.

        Intent:
        Implements intelligent cache cleanup based on actual usage patterns
        rather than simple age. This ensures frequently accessed content stays
        cached even if it's old, while removing content that's no longer relevant.

        Uses Redis SCAN to iterate safely over large key sets without blocking
        the server. Each entry is checked individually for last access time.

        Args:
            days: Number of days since last access to use as cleanup threshold

        Returns:
            Number of entries removed from the cache
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        removed_count = 0
        pattern = f"{self.key_prefix}:entry:*"

        # Use SCAN to iterate over keys
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            for key in keys:
                # Get last_accessed timestamp
                last_accessed_str = await self.redis.hget(key, "last_accessed")
                if last_accessed_str:
                    if isinstance(last_accessed_str, bytes):
                        last_accessed_str = last_accessed_str.decode()

                    last_accessed = datetime.fromisoformat(last_accessed_str)

                    if last_accessed < cutoff_date:
                        # Extract file path from key for remove()
                        key_str = key.decode() if isinstance(key, bytes) else key
                        file_path_str = key_str.replace(f"{self.key_prefix}:entry:", "")
                        if await self.remove(Path(file_path_str)):
                            removed_count += 1

            if cursor == 0:
                break

        return removed_count

    async def get_statistics(self) -> dict[str, int]:
        """
        Get storage statistics.

        Intent:
        Provides comprehensive metrics about cache storage utilization and
        efficiency. These statistics help with capacity planning, performance
        monitoring, and understanding cache effectiveness.

        Uses atomic Redis operations to ensure statistics are consistent
        even under concurrent access.

        Key metrics:
        - Total entries: Overall cache size
        - Total size: Storage usage
        - Unique hashes: Deduplication effectiveness
        - Access count: Usage patterns

        Returns:
            Dictionary containing storage statistics
        """
        stats_key = f"{self.key_prefix}:stats"
        stats = await self.redis.hgetall(stats_key)

        # Decode and convert to integers
        result = {}
        for key, value in stats.items():
            key_str = key.decode() if isinstance(key, bytes) else key
            value_str = value.decode() if isinstance(value, bytes) else value
            result[key_str] = int(value_str)

        # Calculate unique hashes by scanning all entries
        unique_hashes = set()
        pattern = f"{self.key_prefix}:entry:*"

        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            if keys:
                pipeline = self.redis.pipeline()
                for key in keys:
                    pipeline.hget(key, "content_hash")
                hashes = await pipeline.execute()
                unique_hashes.update(h.decode() if isinstance(h, bytes) else h for h in hashes if h)

            if cursor == 0:
                break

        result["unique_hashes"] = len(unique_hashes)

        return result

    async def close(self) -> None:
        """
        Close Redis connection.

        Intent:
        Performs graceful shutdown of the Redis connection. Unlike SQLiteStorage
        which manages a connection pool, RedisStorage expects the Redis client
        to be managed externally, so this method primarily ensures any pending
        operations are flushed.

        Should be called during application shutdown to clean up resources.
        Safe to call multiple times.
        """
        # Redis client is managed externally, but we can close it if needed
        if hasattr(self.redis, "close"):
            await self.redis.close()
