"""
Interface definitions for content cache components.

Intent:
Defines abstract interfaces (protocols) for core cache components to enable
dependency inversion and testability. These interfaces allow mock implementations
during testing and support alternative storage/integrity implementations without
modifying dependent code.

Following SOLID principles:
- Interface Segregation: Separate interfaces for distinct responsibilities
- Dependency Inversion: High-level code depends on abstractions, not concrete classes
"""
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from .models import CacheEntry, IntegrityStatus


@runtime_checkable
class IStorage(Protocol):
    """
    Interface for persistent storage implementations.

    Intent:
    Defines the contract that all storage backends must implement. This enables
    swapping storage implementations (SQLite, Redis, PostgreSQL) without changing
    dependent code, and allows clean mock implementations for testing.

    All storage implementations must handle concurrent access safely and provide
    atomic operations for cache entry management.
    """

    async def initialize(self) -> None:
        """
        Initialize storage backend (create tables, directories, etc).

        Intent:
        Performs one-time setup required before storage can be used. Must be
        idempotent - safe to call multiple times.

        Raises:
            CacheStorageError: If initialization fails
        """
        ...

    async def add(self, entry: CacheEntry) -> None:
        """
        Add or update cache entry in storage.

        Intent:
        Persists cache entry, overwriting if already exists. Should preserve
        access counts when updating existing entries to maintain LRU accuracy.

        Args:
            entry: Cache entry to store

        Raises:
            CacheStorageError: If storage operation fails
        """
        ...

    async def get(self, file_path: Path) -> Optional[CacheEntry]:
        """
        Retrieve cache entry by file path.

        Intent:
        Primary lookup method for retrieving cached content by file path.

        Args:
            file_path: Path of file to retrieve

        Returns:
            CacheEntry if found, None if not cached

        Raises:
            CacheStorageError: If retrieval operation fails
        """
        ...

    async def remove(self, file_path: Path) -> bool:
        """
        Remove cache entry from storage.

        Intent:
        Deletes cache entry if it exists. Used for explicit invalidation.

        Args:
            file_path: Path of file to remove

        Returns:
            True if entry was removed, False if not found

        Raises:
            CacheStorageError: If deletion fails
        """
        ...

    async def get_all(self) -> list[CacheEntry]:
        """
        Retrieve all cache entries.

        Intent:
        Provides bulk access for analytics and administrative operations.

        Returns:
            List of all cached entries

        Raises:
            CacheStorageError: If retrieval fails
        """
        ...

    async def clear_old_entries(self, days: int) -> int:
        """
        Remove entries not accessed within specified days.

        Intent:
        Implements access-based cleanup for cache maintenance.

        Args:
            days: Age threshold in days since last access

        Returns:
            Number of entries removed

        Raises:
            CacheStorageError: If cleanup fails
        """
        ...

    async def get_statistics(self) -> dict[str, int]:
        """
        Get storage utilization statistics.

        Intent:
        Provides metrics for monitoring and capacity planning.

        Returns:
            Dictionary with statistics (total_entries, total_size, etc)

        Raises:
            CacheStorageError: If statistics retrieval fails
        """
        ...

    async def close(self) -> None:
        """
        Close storage backend and release resources.

        Intent:
        Performs graceful shutdown, ensuring data integrity. Must be safe
        to call multiple times.
        """
        ...


@runtime_checkable
class IBlobStorage(Protocol):
    """
    Interface for blob storage implementations.

    Intent:
    Defines contract for storing large content externally. Separate from main
    storage interface to support different backends (local filesystem, S3, etc).
    """

    async def store(self, content_hash: str, content: str) -> Path:
        """
        Store content and return storage path.

        Args:
            content_hash: Hash for deduplication
            content: Content to store

        Returns:
            Path where content was stored
        """
        ...

    async def retrieve(self, content_hash: str) -> Optional[str]:
        """
        Retrieve content by hash.

        Args:
            content_hash: Hash of content to retrieve

        Returns:
            Content if found, None if not found or corrupted
        """
        ...

    async def delete(self, content_hash: str) -> bool:
        """
        Delete content by hash.

        Args:
            content_hash: Hash of content to delete

        Returns:
            True if deleted, False if not found
        """
        ...

    async def exists(self, content_hash: str) -> bool:
        """
        Check if content exists.

        Args:
            content_hash: Hash to check

        Returns:
            True if exists, False otherwise
        """
        ...


@runtime_checkable
class IIntegrityChecker(Protocol):
    """
    Interface for file integrity verification implementations.

    Intent:
    Defines contract for integrity verification strategies. This allows different
    verification approaches (hash-based, timestamp-based, checksum-based) and
    clean mocking during tests.

    Implementations must provide both single-entry and batch verification for
    performance optimization.
    """

    async def compute_file_hash(self, file_path: Path) -> str:
        """
        Compute hash of file contents.

        Intent:
        Provides cryptographically secure content fingerprinting for integrity
        verification and deduplication. This is a core operation used by the cache
        to detect content changes and enable content-addressable storage.

        Args:
            file_path: Path to file to hash

        Returns:
            Hexadecimal hash string (implementation-specific algorithm)
        """
        ...

    async def check_integrity(self, entry: CacheEntry) -> IntegrityStatus:
        """
        Verify integrity of a single cache entry.

        Intent:
        Determines if cached content is still valid by checking file existence,
        modification time, and optionally content hash.

        Args:
            entry: Cache entry to verify

        Returns:
            IntegrityStatus indicating verification result
        """
        ...

    async def check_batch(self, entries: list[CacheEntry]) -> dict[Path, IntegrityStatus]:
        """
        Verify integrity of multiple entries concurrently.

        Intent:
        Enables efficient bulk verification through parallelization.

        Args:
            entries: List of entries to verify

        Returns:
            Dictionary mapping file paths to their integrity status
        """
        ...
