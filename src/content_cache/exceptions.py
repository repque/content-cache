"""
Custom exceptions for the content cache system
"""


class CacheError(Exception):
    """
    Base exception for all cache-related errors.
    
    Intent:
    Provides a common base class for all cache-specific exceptions, enabling
    callers to catch cache-related errors distinctly from other system errors.
    This supports better error handling and logging strategies.
    
    All cache exceptions inherit from this base to maintain a clear exception
    hierarchy and enable comprehensive error handling patterns.
    """
    pass


class CacheCorruptionError(CacheError):
    """
    Raised when cache integrity check fails or data is corrupted.
    
    Intent:
    Indicates that stored cache data has been corrupted or cannot be validated.
    This typically triggers cache invalidation and content regeneration rather
    than serving potentially invalid data.
    
    Common scenarios:
    - Hash mismatch during integrity verification
    - Corrupted blob files that can't be decompressed
    - Database corruption in SQLite storage
    
    The cache handles this gracefully by treating it as a cache miss.
    """
    pass


class CacheStorageError(CacheError):
    """
    Raised when storage operations fail (SQLite, file system, etc.).
    
    Intent:
    Indicates failure in the underlying storage layers that prevents normal
    cache operation. This could be temporary (disk full, network issues) or
    permanent (corrupted database, missing directories).
    
    Common scenarios:
    - Disk space exhaustion preventing blob storage
    - SQLite database lock timeouts
    - File system permission issues
    - Network storage unavailability
    
    Applications should implement appropriate retry logic and fallback strategies.
    """
    pass


class CacheConfigurationError(CacheError):
    """
    Raised when cache configuration is invalid.
    
    Intent:
    Indicates that the cache cannot be initialized or operated due to invalid
    configuration parameters. This is typically a startup-time error that
    prevents the cache from functioning.
    
    Common scenarios:
    - Invalid memory size limits (too small or too large)
    - Inaccessible cache directories
    - Invalid compression levels
    - Conflicting security settings
    
    These errors should be caught early and result in application startup failure.
    """
    pass


class CachePermissionError(CacheError):
    """
    Raised when file access is denied due to permissions.
    
    Intent:
    Indicates security-related access violations, either due to file system
    permissions or cache security policies. This helps distinguish permission
    issues from other I/O errors.
    
    Common scenarios:
    - Path traversal attack attempts (../ sequences)
    - Access to files outside allowed paths
    - Insufficient file system permissions
    - SELinux or other security policy violations
    
    These errors should be logged for security monitoring and not retried.
    """
    pass


class CacheProcessingError(CacheError):
    """
    Raised when content processing fails.
    
    Intent:
    Indicates that the user-provided content processing callback failed to
    extract content from a file. This wraps processing errors to distinguish
    them from cache infrastructure errors.
    
    Common scenarios:
    - PDF parsing failures (corrupted files, unsupported formats)
    - Encoding issues in text files
    - Memory exhaustion during large file processing
    - Processing timeout exceeded
    
    The cache treats these as non-cacheable errors and propagates them to callers.
    """
    pass
