"""
File system storage for large content blobs
"""
import asyncio
import zlib
from pathlib import Path
from typing import Optional

import aiofiles


class FileStorage:
    """
    Handles storage of large content on the file system with compression.
    
    Intent:
    Provides efficient storage for large content that would bloat the SQLite
    database. Uses compression to minimize disk usage and directory sharding
    to avoid file system performance issues with large directories.
    
    Key design decisions:
    - Compression reduces storage requirements for text content
    - Directory sharding prevents too many files in a single directory
    - Hash-based paths enable content deduplication
    - Async I/O prevents blocking on disk operations
    
    The sharding scheme (hash[:2]/hash[2:4]/hash.gz) distributes files across
    subdirectories, maintaining good file system performance even with millions
    of cached files.
    """

    def __init__(self, base_path: Path, compression_level: int = 6):
        """
        Initialize file storage with base directory and compression settings.
        
        Intent:
        Sets up blob storage in a specified directory with configurable compression.
        Level 6 provides good balance between compression ratio and speed, but can
        be tuned based on storage vs CPU trade-offs.
        
        Args:
            base_path: Root directory for blob storage
            compression_level: zlib compression level (0-9, 6 is balanced)
        """
        self.base_path = base_path
        self.compression_level = compression_level
        self._lock = asyncio.Lock()

    def _get_path_for_hash(self, content_hash: str) -> Path:
        """
        Generate file path for content hash using directory sharding.
        
        Intent:
        Creates a predictable, evenly distributed directory structure that scales
        well with large numbers of files. The sharding prevents any single directory
        from becoming too large, which would hurt file system performance.
        
        The pattern (ab/c1/abc123...gz) creates up to 65,536 leaf directories,
        distributing files evenly across the hash space.
        
        Args:
            content_hash: SHA-256 hash to generate path for
            
        Returns:
            Path where content should be stored
        """
        # Use first 4 characters for directory sharding to avoid too many files in one directory
        # Structure: base_path/ab/c1/abc123def456789.gz
        dir1 = content_hash[:2]
        dir2 = content_hash[2:4]
        filename = f"{content_hash}.gz"

        return self.base_path / dir1 / dir2 / filename

    async def store(self, content_hash: str, content: str) -> Path:
        """
        Store content to file system with compression.
        
        Intent:
        Saves large content to disk with compression to minimize storage usage.
        Creates the directory structure as needed and handles encoding/compression
        transparently. Returns the path for storage in the database.
        
        The content is compressed before writing to achieve significant space
        savings, especially for text content which often compresses very well.
        
        Args:
            content_hash: Hash to use for file naming and deduplication
            content: Text content to store
            
        Returns:
            Path where content was stored
        """
        blob_path = self._get_path_for_hash(content_hash)

        # Create parent directories
        blob_path.parent.mkdir(parents=True, exist_ok=True)

        # Compress content
        compressed_data = zlib.compress(
            content.encode('utf-8'),
            level=self.compression_level
        )

        # Write to file
        async with aiofiles.open(blob_path, 'wb') as f:
            await f.write(compressed_data)

        return blob_path

    async def retrieve(self, content_hash: str) -> Optional[str]:
        """
        Retrieve and decompress content from file system.
        
        Intent:
        Loads and decompresses previously stored content. Handles file corruption
        gracefully by returning None rather than raising exceptions, allowing
        the cache to fall back to regenerating content.
        
        This resilient approach ensures that corrupted blob files don't crash
        the application - they're simply treated as cache misses.
        
        Args:
            content_hash: Hash of content to retrieve
            
        Returns:
            Decompressed content string, or None if not found/corrupted
        """
        blob_path = self._get_path_for_hash(content_hash)

        if not blob_path.exists():
            return None

        try:
            # Read compressed data
            async with aiofiles.open(blob_path, 'rb') as f:
                compressed_data = await f.read()

            # Decompress and decode
            content = zlib.decompress(compressed_data).decode('utf-8')
            return content
        except Exception:
            # Handle corrupted files
            return None

    async def delete(self, content_hash: str) -> bool:
        """
        Delete content from file system.
        
        Intent:
        Removes stored content and cleans up empty directories to prevent
        directory proliferation. The cleanup is opportunistic - it only removes
        directories if they're empty, avoiding race conditions with concurrent
        operations.
        
        This approach maintains the directory structure's efficiency over time
        by removing unused directories while being safe in concurrent environments.
        
        Args:
            content_hash: Hash of content to delete
            
        Returns:
            True if content was deleted, False if not found or error occurred
        """
        blob_path = self._get_path_for_hash(content_hash)

        if not blob_path.exists():
            return False

        try:
            blob_path.unlink()

            # Clean up empty parent directories
            for parent in [blob_path.parent, blob_path.parent.parent]:
                try:
                    if parent != self.base_path and not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    pass  # Directory not empty or other error

            return True
        except Exception:
            return False

    async def exists(self, content_hash: str) -> bool:
        """
        Check if content exists in storage.
        
        Intent:
        Provides fast existence checking without reading file contents.
        Useful for optimizing storage decisions and verifying blob references
        before attempting retrieval operations.
        
        Args:
            content_hash: Hash of content to check
            
        Returns:
            True if content file exists, False otherwise
        """
        blob_path = self._get_path_for_hash(content_hash)
        return blob_path.exists()

    async def get_size(self, content_hash: str) -> int:
        """
        Get size of stored content (compressed size).
        
        Intent:
        Provides storage utilization metrics without reading file contents.
        Reports compressed size, which is useful for understanding actual
        disk usage and compression effectiveness.
        
        This is valuable for capacity planning and storage analytics,
        allowing monitoring of storage efficiency trends over time.
        
        Args:
            content_hash: Hash of content to measure
            
        Returns:
            Size in bytes of compressed content file, 0 if not found
        """
        blob_path = self._get_path_for_hash(content_hash)

        if not blob_path.exists():
            return 0

        return blob_path.stat().st_size

