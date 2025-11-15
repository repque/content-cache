"""
Data models for content cache component
"""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class IntegrityStatus(str, Enum):
    """
    Enum representing file integrity check results.

    Intent:
    Provides a type-safe way to represent the outcome of file integrity
    verification. Rather than using magic strings or boolean flags, this enum
    makes the code more readable and helps catch errors at development time.

    Each status indicates a specific condition that affects whether cached
    content can be trusted or needs to be regenerated.
    """

    VALID = "valid"
    FILE_MISSING = "file_missing"
    FILE_MODIFIED = "file_modified"
    CONTENT_CHANGED = "content_changed"
    CORRUPTED = "corrupted"


class CacheEntry(BaseModel):
    """
    Represents a single entry in the cache with all metadata.

    Intent:
    This is the core data structure that tracks everything needed to manage
    cached file content. It serves as both the in-memory representation and
    the schema for persistent storage.

    Key design decisions:
    - Includes both content and blob path to support hybrid storage
    - Tracks access patterns (count, last_accessed) for LRU eviction
    - Uses Pydantic for validation and serialization consistency
    - Supports both string and Path inputs for flexibility

    The entry contains enough metadata to:
    - Verify content freshness (modification_time, content_hash)
    - Implement cache eviction policies (access_count, last_accessed)
    - Support storage tier decisions (content vs content_blob_path)
    - Enable analytics and monitoring (extraction_timestamp, file_size)
    """

    model_config = ConfigDict(validate_assignment=True)

    file_path: Path = Field(description="Path to the cached file")
    content_hash: str = Field(description="SHA-256 hash of file content")
    modification_time: float = Field(description="File modification time (unix timestamp)")
    file_size: int = Field(description="Size of the file in bytes")
    content: Optional[str] = Field(default=None, description="Extracted content (if stored in DB)")
    content_blob_path: Optional[Path] = Field(
        default=None, description="Path to compressed content blob"
    )
    extraction_timestamp: datetime = Field(description="When content was extracted")
    access_count: int = Field(default=0, description="Number of times accessed")
    last_accessed: datetime = Field(description="Last access timestamp")

    @field_validator("file_path", mode="before")
    @classmethod
    def validate_file_path(cls, v: Any) -> Path:
        """
        Ensure file_path is a Path object.

        Intent:
        Provides flexible input handling while maintaining type safety internally.
        Users can pass either string paths or Path objects, but internally we
        always work with Path objects for consistency and to leverage Path's
        rich API (exists(), stat(), etc.).

        This validation happens before other Pydantic validation, ensuring
        downstream code can always assume file_path is a proper Path object.
        """
        if isinstance(v, str):
            return Path(v)
        if isinstance(v, Path):
            return v
        raise ValueError("file_path must be a Path object or string")

    @field_validator("content_blob_path", mode="before")
    @classmethod
    def validate_content_blob_path(cls, v: Any) -> Optional[Path]:
        """
        Ensure content_blob_path is a Path object if provided.

        Intent:
        Similar to file_path validation but handles the optional nature of
        blob paths. Small content is stored directly in the database with
        content_blob_path=None, while large content is stored as compressed
        blobs with the path recorded here.

        This dual approach optimizes for query performance (small content) and
        storage efficiency (large content compression).
        """
        if v is None:
            return v
        if isinstance(v, str):
            return Path(v)
        if isinstance(v, Path):
            return v
        raise ValueError("content_blob_path must be a Path object or string")

    @field_serializer("file_path", "content_blob_path")
    def serialize_path(self, path: Optional[Path]) -> Optional[str]:
        """
        Serialize Path objects to strings.

        Intent:
        Ensures Path objects are properly serialized when the model is converted
        to JSON or stored in databases. Path objects aren't natively JSON-serializable,
        so we convert them to strings for persistence and API responses.

        This serializer maintains cross-platform compatibility by using string
        representation rather than attempting to preserve Path object state.
        """
        return str(path) if path is not None else None


class CachedContent(BaseModel):
    """
    Response model for cached content retrieval.

    Intent:
    This is the public-facing response model returned by the cache's get_content
    method. It provides everything a client needs to understand the result:
    the actual content plus metadata about its source and characteristics.

    Key design decisions:
    - Separates public API from internal storage model (CacheEntry)
    - Includes from_cache flag for performance monitoring
    - Provides content hash for client-side verification if needed
    - Includes extraction timestamp for freshness assessment

    The model helps clients make informed decisions about content usage,
    understand cache performance, and implement their own caching strategies
    if needed.
    """

    content: str = Field(description="The extracted content")
    from_cache: bool = Field(description="Whether content was served from cache")
    content_hash: str = Field(description="SHA-256 hash of file content")
    extraction_timestamp: datetime = Field(description="When content was extracted")
    file_size: int = Field(description="Original file size in bytes")

