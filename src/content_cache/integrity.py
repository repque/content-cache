"""
File integrity checking functionality
"""
import asyncio
import hashlib
from pathlib import Path

import aiofiles

from .models import CacheEntry, IntegrityStatus


class FileIntegrityChecker:
    """
    Handles file integrity verification for cached entries.
    
    Intent:
    Provides multi-level integrity verification to ensure cached content remains
    valid and fresh. Implements a cascading validation strategy that balances
    performance with thoroughness - quick checks first, expensive hash verification
    only when needed.
    
    Key design decisions:
    - Tiered verification: existence → modification time → content hash
    - Async hash computation prevents blocking on large files
    - Configurable hash verification for performance tuning
    - Chunked reading for memory efficiency with large files
    
    The integrity checker is central to cache reliability - it ensures that
    stale or corrupted content is never served to clients.
    """

    def __init__(self, verify_hash: bool = True, chunk_size: int = 8192):
        """
        Initialize integrity checker with configuration.
        
        Intent:
        Sets up integrity verification with configurable thoroughness levels.
        Hash verification can be disabled for performance in scenarios where
        modification time checking is sufficient.
        
        Args:
            verify_hash: Whether to perform expensive content hash verification
            chunk_size: Size of chunks for reading large files (memory efficiency)
        """
        self.verify_hash = verify_hash
        self.chunk_size = chunk_size

    async def check_integrity(self, entry: CacheEntry) -> IntegrityStatus:
        """
        Perform integrity check on a single cache entry.
        
        Intent:
        Implements a tiered verification strategy that optimizes for the common
        case (file unchanged) while catching all forms of staleness. The levels
        are ordered by cost - cheap checks first, expensive verification last.
        
        Level 1 (cheapest): File existence and modification time
        Level 2 (expensive): Content hash verification
        
        This approach minimizes I/O for the common case where files haven't
        changed, while providing strong guarantees when hash verification is enabled.
        
        Args:
            entry: Cache entry to verify
            
        Returns:
            IntegrityStatus indicating the verification result
        """
        # Level 1: Quick checks
        if not entry.file_path.exists():
            return IntegrityStatus.FILE_MISSING

        try:
            stat = entry.file_path.stat()
        except OSError:
            return IntegrityStatus.FILE_MISSING

        # Check modification time
        if stat.st_mtime > entry.modification_time:
            # File was modified - but check if content actually changed
            if self.verify_hash:
                current_hash = await self._compute_file_hash(entry.file_path)
                if current_hash == entry.content_hash:
                    # Content unchanged despite new mtime (e.g., re-downloaded same file)
                    # This is still valid, but we'll need to update the mtime in cache
                    return IntegrityStatus.VALID
                else:
                    # Content actually changed
                    return IntegrityStatus.CONTENT_CHANGED
            else:
                # Without hash verification, assume file was modified
                return IntegrityStatus.FILE_MODIFIED

        # Level 2: Hash verification (if enabled and mtime unchanged)
        if self.verify_hash:
            current_hash = await self._compute_file_hash(entry.file_path)
            if current_hash != entry.content_hash:
                return IntegrityStatus.CONTENT_CHANGED

        return IntegrityStatus.VALID

    async def _compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA-256 hash of file contents asynchronously.
        
        Intent:
        Provides cryptographically secure content fingerprinting while maintaining
        async compatibility. Uses chunked reading to handle large files without
        consuming excessive memory.
        
        SHA-256 is chosen for its excellent collision resistance and widespread
        support. The async implementation prevents blocking the event loop during
        I/O operations, which is crucial for maintaining responsiveness.
        
        Args:
            file_path: Path to file to hash
            
        Returns:
            Hexadecimal SHA-256 hash of file contents
        """
        sha256_hash = hashlib.sha256()

        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(self.chunk_size):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    async def check_batch(self, entries: list[CacheEntry]) -> dict[Path, IntegrityStatus]:
        """
        Check integrity of multiple entries concurrently.
        
        Intent:
        Enables efficient bulk integrity verification by parallelizing the checks.
        This is particularly valuable during cache initialization or maintenance
        operations where many entries need verification.
        
        The concurrent approach dramatically reduces total verification time
        compared to sequential processing, especially when hash verification
        is enabled and I/O latency is significant.
        
        Args:
            entries: List of cache entries to verify
            
        Returns:
            Dictionary mapping file paths to their integrity status
        """
        tasks = [self.check_integrity(entry) for entry in entries]
        results = await asyncio.gather(*tasks)

        return {entry.file_path: status for entry, status in zip(entries, results)}

