"""
Content File Cache Component - High-performance caching for file content extraction
"""
from .cache import ContentCache
from .config import CacheConfig
from .exceptions import (
    CacheConfigurationError,
    CacheCorruptionError,
    CacheError,
    CachePermissionError,
    CacheProcessingError,
    CacheStorageError,
)
from .interfaces import IBlobStorage, IIntegrityChecker, IStorage
from .models import CachedContent, CacheEntry, IntegrityStatus

# Optional Redis support
try:
    from .redis_storage import RedisStorage

    __all_with_redis = ["RedisStorage"]
except ImportError:
    __all_with_redis = []

__version__ = "0.1.0"
__all__ = [
    "ContentCache",
    "CacheConfig",
    "CachedContent",
    "CacheEntry",
    "IntegrityStatus",
    "IStorage",
    "IBlobStorage",
    "IIntegrityChecker",
    "CacheError",
    "CacheCorruptionError",
    "CacheStorageError",
    "CacheConfigurationError",
    "CachePermissionError",
    "CacheProcessingError",
    *__all_with_redis,
]

