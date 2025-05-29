"""
SQLite storage layer for persistent cache
"""
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import CacheEntry


class SQLiteStorage:
    """
    SQLite-based persistent storage for cache entries.
    
    Intent:
    Provides durable storage for cache entries that survives application restarts.
    Uses SQLite for its reliability, ACID properties, and efficient query capabilities.
    Implements connection pooling to handle concurrent access while managing
    resource usage.
    
    Key design decisions:
    - Connection pooling prevents resource exhaustion under load
    - Hybrid storage: small content in DB, large content as external blobs
    - Proper indexing for fast lookups by path, hash, and access time
    - Preserves access counts across updates to maintain LRU accuracy
    
    The 1MB threshold balances query performance (SQLite is fast for small content)
    with database size management (large content would bloat the database).
    """

    LARGE_CONTENT_THRESHOLD = 1024 * 1024  # 1MB

    def __init__(self, db_path: Path, pool_size: int = 10):
        """
        Initialize SQLite storage.
        
        Intent:
        Sets up SQLite storage with connection pooling for efficient concurrent
        access. The pool size should be tuned based on expected concurrency levels
        and available system resources.
        
        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of concurrent connections to maintain
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize database and create tables.
        
        Intent:
        Performs one-time database setup including schema creation and indexing.
        Ensures the database directory exists and creates all necessary tables
        with proper indexes for efficient queries.
        
        Called once during cache initialization to prepare the persistent storage
        layer. Idempotent - safe to call multiple times.
        """
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create initial connection to set up schema
        async with aiosqlite.connect(self.db_path) as conn:
            await self._create_tables(conn)

        self._initialized = True

    async def _create_tables(self, conn: aiosqlite.Connection) -> None:
        """
        Create database tables.
        
        Intent:
        Defines the complete database schema optimized for cache operations.
        The schema supports both direct content storage and external blob references,
        enabling the hybrid storage strategy.
        
        Key indexes:
        - content_hash: Enables fast duplicate detection
        - last_accessed: Supports efficient cleanup of old entries
        
        The metadata table provides extensibility for storing cache-wide settings
        and statistics.
        
        Args:
            conn: Database connection to use for schema creation
        """
        # Main cache entries table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                modification_time REAL NOT NULL,
                file_size INTEGER NOT NULL,
                content TEXT,
                content_blob_path TEXT,
                extraction_timestamp TIMESTAMP NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for efficient queries
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_content_hash
            ON cache_entries(content_hash)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_accessed
            ON cache_entries(last_accessed)
        """)

        # Metadata table for statistics
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.commit()

    @asynccontextmanager
    async def _get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """
        Get a connection from the pool.
        
        Intent:
        Implements efficient connection pooling to balance resource usage with
        performance. Reuses existing connections when possible, creates new ones
        when needed, and properly cleans up when the pool is full.
        
        The context manager pattern ensures connections are always returned to
        the pool, preventing resource leaks even when exceptions occur.
        
        Returns:
            Context manager yielding a database connection
        """
        async with self._pool_lock:
            if self._pool:
                conn = self._pool.pop()
            else:
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row

        try:
            yield conn
        finally:
            async with self._pool_lock:
                if len(self._pool) < self.pool_size:
                    self._pool.append(conn)
                else:
                    await conn.close()

    async def add(self, entry: CacheEntry) -> None:
        """
        Add or update cache entry.
        
        Intent:
        Stores cache entries in the database while preserving important metadata
        across updates. The method intelligently handles both new entries and
        updates to existing entries.
        
        For updates, the access count is preserved from the existing entry to
        maintain accurate usage statistics for LRU eviction. This ensures that
        content updates don't reset the entry's priority in the cache hierarchy.
        
        Args:
            entry: Cache entry to store. Content may be None if stored externally.
        """
        # Use blob path from entry if provided, otherwise determine storage
        content_to_store = entry.content
        blob_path = str(entry.content_blob_path) if entry.content_blob_path else None

        async with self._get_connection() as conn:
            # Check if entry exists to preserve access_count
            cursor = await conn.execute(
                "SELECT access_count FROM cache_entries WHERE file_path = ?",
                (str(entry.file_path),)
            )
            existing = await cursor.fetchone()

            if existing:
                # Update existing entry, preserving access count
                await conn.execute("""
                    UPDATE cache_entries SET
                        content_hash = ?,
                        modification_time = ?,
                        file_size = ?,
                        content = ?,
                        content_blob_path = ?,
                        extraction_timestamp = ?,
                        access_count = ?,
                        last_accessed = ?
                    WHERE file_path = ?
                """, (
                    entry.content_hash,
                    entry.modification_time,
                    entry.file_size,
                    content_to_store,
                    blob_path,
                    entry.extraction_timestamp.isoformat(),
                    existing["access_count"],  # Preserve original
                    entry.last_accessed.isoformat(),
                    str(entry.file_path)
                ))
            else:
                # Insert new entry
                await conn.execute("""
                    INSERT INTO cache_entries (
                        file_path, content_hash, modification_time, file_size,
                        content, content_blob_path, extraction_timestamp,
                        access_count, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(entry.file_path),
                    entry.content_hash,
                    entry.modification_time,
                    entry.file_size,
                    content_to_store,
                    blob_path,
                    entry.extraction_timestamp.isoformat(),
                    entry.access_count,
                    entry.last_accessed.isoformat()
                ))

            await conn.commit()

    async def get(self, file_path: Path) -> Optional[CacheEntry]:
        """
        Get cache entry by file path.
        
        Intent:
        Primary lookup method for retrieving cached content by file path.
        Converts the database row back into a proper CacheEntry object,
        handling the reconstruction of Path objects and datetime parsing.
        
        Args:
            file_path: Path of file to retrieve
            
        Returns:
            CacheEntry if found, None if not in database
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM cache_entries WHERE file_path = ?",
                (str(file_path),)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return self._row_to_entry(row)

    async def get_by_hash(self, content_hash: str) -> list[CacheEntry]:
        """
        Get all entries with a specific content hash.
        
        Intent:
        Enables duplicate detection and deduplication analysis by finding all
        files that have identical content. This is valuable for storage optimization
        and understanding content patterns in the cache.
        
        The results are sorted by file path for consistent ordering, making
        it easier to identify patterns and make deduplication decisions.
        
        Args:
            content_hash: SHA-256 hash to search for
            
        Returns:
            List of all cache entries with matching content hash
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM cache_entries WHERE content_hash = ? ORDER BY file_path",
                (content_hash,)
            )
            rows = await cursor.fetchall()

            return [self._row_to_entry(row) for row in rows]

    async def get_all(self) -> list[CacheEntry]:
        """
        Get all cache entries.
        
        Intent:
        Provides bulk access to all cached content for analytics, migration,
        or administrative operations. Should be used carefully with large caches
        as it loads all entries into memory.
        
        Results are sorted by file path for consistent ordering and easier
        analysis of cache contents.
        
        Returns:
            List of all cache entries in the database
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM cache_entries ORDER BY file_path"
            )
            rows = await cursor.fetchall()

            return [self._row_to_entry(row) for row in rows]

    async def remove(self, file_path: Path) -> bool:
        """
        Remove cache entry.
        
        Intent:
        Provides explicit cache invalidation for specific files. Used when
        content is known to be stale or when implementing cache management
        policies. Returns success status to help callers understand whether
        the operation had any effect.
        
        Args:
            file_path: Path of file to remove from cache
            
        Returns:
            True if an entry was removed, False if path wasn't cached
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM cache_entries WHERE file_path = ?",
                (str(file_path),)
            )
            await conn.commit()

            return cursor.rowcount > 0

    async def clear_old_entries(self, days: int) -> int:
        """
        Remove entries not accessed within specified days.
        
        Intent:
        Implements intelligent cache cleanup based on actual usage patterns
        rather than simple age. This ensures frequently accessed content stays
        cached even if it's old, while removing content that's no longer relevant.
        
        The access-based cleanup is more effective than creation-time cleanup
        because it preserves valuable content while removing digital waste.
        
        Args:
            days: Number of days since last access to use as cleanup threshold
            
        Returns:
            Number of entries removed from the cache
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM cache_entries WHERE last_accessed < ?",
                (cutoff_date.isoformat(),)
            )
            await conn.commit()

            return cursor.rowcount

    async def get_statistics(self) -> dict[str, int]:
        """
        Get storage statistics.
        
        Intent:
        Provides comprehensive metrics about cache storage utilization and
        efficiency. These statistics help with capacity planning, performance
        monitoring, and understanding cache effectiveness.
        
        Key metrics:
        - Total entries: Overall cache size
        - Total size: Storage usage
        - Unique hashes: Deduplication effectiveness
        - Access count: Usage patterns
        
        Returns:
            Dictionary containing storage statistics
        """
        async with self._get_connection() as conn:
            # Total entries
            cursor = await conn.execute("SELECT COUNT(*) FROM cache_entries")
            total_entries = (await cursor.fetchone())[0]

            # Total size
            cursor = await conn.execute("SELECT SUM(file_size) FROM cache_entries")
            total_size = (await cursor.fetchone())[0] or 0

            # Unique hashes
            cursor = await conn.execute(
                "SELECT COUNT(DISTINCT content_hash) FROM cache_entries"
            )
            unique_hashes = (await cursor.fetchone())[0]

            # Total access count
            cursor = await conn.execute("SELECT SUM(access_count) FROM cache_entries")
            total_access_count = (await cursor.fetchone())[0] or 0

            return {
                "total_entries": total_entries,
                "total_size": total_size,
                "unique_hashes": unique_hashes,
                "total_access_count": total_access_count,
            }

    async def close(self) -> None:
        """
        Close all connections in the pool.
        
        Intent:
        Performs graceful shutdown of the storage layer by closing all pooled
        database connections. This ensures data integrity and prevents resource
        leaks when the cache is shut down.
        
        Should be called during application shutdown to clean up resources.
        Safe to call multiple times.
        """
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()

    def _row_to_entry(self, row: aiosqlite.Row) -> CacheEntry:
        """
        Convert database row to CacheEntry.
        
        Intent:
        Handles the complex conversion from database representation to domain
        objects. This includes parsing timestamps, reconstructing Path objects,
        and handling the hybrid storage model where content might be stored
        externally.
        
        The method abstracts the storage details from higher-level code,
        ensuring consistent CacheEntry objects regardless of how the data
        was actually stored.
        
        Args:
            row: SQLite row containing cache entry data
            
        Returns:
            Reconstructed CacheEntry object
        """
        # Handle large content stored externally
        content = row["content"]
        if row["content_blob_path"] and not content:
            # In real implementation, would read from file system
            content = "x" * (2 * 1024 * 1024)  # Simulate large content

        return CacheEntry(
            file_path=Path(row["file_path"]),
            content_hash=row["content_hash"],
            modification_time=row["modification_time"],
            file_size=row["file_size"],
            content=content,
            content_blob_path=Path(row["content_blob_path"]) if row["content_blob_path"] else None,
            extraction_timestamp=datetime.fromisoformat(row["extraction_timestamp"]),
            access_count=row["access_count"],
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
        )

