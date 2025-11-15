"""
Configuration module for content cache component
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv()


class CacheConfig(BaseModel):
    """
    Configuration for content cache component with environment variable support.

    Intent:
    Centralizes all cache configuration with intelligent defaults and environment
    variable overrides. This design allows the cache to work out-of-the-box for
    development while being fully configurable for production environments.

    Key design decisions:
    - Environment variables take precedence over defaults for 12-factor app compliance
    - Validation ensures configuration values are safe and sensible
    - Security controls (allowed_paths) are configurable but default to unrestricted
    - Performance tuning parameters are exposed for optimization

    The configuration balances ease of use (sensible defaults) with production
    needs (full customization via environment variables).
    """

    cache_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("CACHE_DIR", "./cache_storage"))
    )
    max_memory_size: int = Field(
        default_factory=lambda: int(os.getenv("MAX_MEMORY_SIZE", "104857600"))
    )
    verify_hash: bool = Field(
        default_factory=lambda: os.getenv("VERIFY_HASH", "true").lower() == "true"
    )
    db_pool_size: int = Field(default_factory=lambda: int(os.getenv("DB_POOL_SIZE", "10")))
    compression_level: int = Field(
        default_factory=lambda: int(os.getenv("COMPRESSION_LEVEL", "6"))
    )
    bloom_filter_size: int = Field(
        default_factory=lambda: int(os.getenv("BLOOM_FILTER_SIZE", "1000000"))
    )
    debug: bool = Field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")

    # Security: allowed paths for file access (empty list means no restrictions)
    allowed_paths: list[Path] = Field(default_factory=list)

    model_config = ConfigDict(validate_assignment=True)

    @field_validator("max_memory_size")
    @classmethod
    def validate_memory_size(cls, v: int) -> int:
        """
        Validate memory size is reasonable.

        Intent:
        Prevents configuration errors that could cause system instability.
        Memory cache that's too small provides little benefit, while excessively
        large caches could consume all available system memory.

        The bounds (1MB to 10GB) represent practical limits - smaller caches
        aren't useful for most content, while larger caches should use more
        sophisticated memory management strategies.
        """
        if v < 1024 * 1024:  # 1MB minimum
            raise ValueError("Memory size must be at least 1MB")
        if v > 10 * 1024 * 1024 * 1024:  # 10GB maximum
            raise ValueError("Memory size must not exceed 10GB")
        return v

    @field_validator("compression_level")
    @classmethod
    def validate_compression_level(cls, v: int) -> int:
        """
        Validate compression level is valid.

        Intent:
        Ensures compression level is within the valid range for zlib compression.
        Invalid levels would cause runtime errors when storing large content
        in blob storage.

        Level 6 is the default as it provides good balance between compression
        ratio and speed. Lower levels (0-2) favor speed, higher levels (7-9)
        favor compression ratio at the cost of CPU time.
        """
        if v < 0 or v > 9:
            raise ValueError("Compression level must be between 0 and 9")
        return v

