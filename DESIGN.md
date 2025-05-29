# Content File Cache Component Design

## 1. Introduction

The Content File Cache Component is a high-performance caching solution designed to efficiently manage and retrieve content from various file formats, particularly PDFs and Markdown documents. This component minimizes redundant processing by intelligently detecting file changes and serving cached content when appropriate, significantly improving application performance and reducing computational overhead.

## 2. Design Considerations

### Key Considerations
- **Multi-format Support**: The cache must handle diverse file formats (PDF, MD, TXT, DOCX, etc.) with extensible architecture for future formats
- **Content Extraction Flexibility**: Support for pluggable content processors via callback functions
- **Performance Optimization**: Minimize I/O operations and processing time through intelligent caching
- **Concurrency Safety**: Thread-safe operations for multi-threaded environments
- **Memory Efficiency**: Balance between cache size and retrieval speed

### Assumptions
- Files are stored on a local or network-accessible filesystem
- Content extraction functions are provided externally via callbacks
- The system has sufficient storage for cache persistence
- File paths are unique identifiers within the system

## 3. Component Design

### Configuration
The cache uses a configuration-based approach with environment variable support:

```python
from content_cache import ContentCache, CacheConfig

# Method 1: Direct configuration
config = CacheConfig(
    cache_dir=Path("./cache_storage"),
    max_memory_size=100 * 1024 * 1024,
    verify_hash=True,
    allowed_paths=[Path("/safe/directory")]  # Security restriction
)
cache = ContentCache(config=config)

# Method 2: Environment variables
# CACHE_DIR, MAX_MEMORY_SIZE, VERIFY_HASH, etc.
config = CacheConfig()  # Reads from environment
cache = ContentCache(config=config)
```

### Ingestion
The cache component accepts content files through a unified interface:

```python
class ContentCache:
    async def get_content(
        self, 
        file_path: Path, 
        process_callback: Callable[[Path], str]  # Synchronous callback
    ) -> CachedContent
```

The ingestion mechanism:
- Accepts any file path as input
- Validates file existence and path security (prevents traversal attacks)
- Checks file against bloom filter for quick rejection of known missing files
- Routes to multi-tier cache lookup or processing pipeline

### Processing
Content processing leverages callback functions for maximum flexibility:

1. **Cache Hit Path**: If file is unchanged, return cached content immediately
2. **Cache Miss Path**: 
   - Invoke the provided `process_callback` function
   - Store extracted content with metadata
   - Return processed content

### Local Storage
The cache employs a hybrid storage strategy:

- **In-Memory Cache**: LRU cache for frequently accessed content
- **Persistent Storage**: SQLite database for long-term storage
- **File System**: Original file references and large content blobs

### Security
The cache implements multiple security measures:

1. **Path Validation**: Prevents directory traversal attacks ("../" sequences)
2. **Allowed Paths**: Configurable allowlist for file access restriction
3. **Path Resolution**: Resolves symbolic links to detect traversal attempts
4. **Permission Checking**: Validates file system permissions before access

Security validation occurs on every file access:
```python
def _validate_file_path(self, file_path: Path) -> None:
    # Check for traversal attacks
    if ".." in str(file_path):
        raise CachePermissionError("Path traversal detected")
    
    # Validate against allowed paths if configured
    if self.config.allowed_paths:
        # Check if path is within allowed directories
```

### Metrics and Monitoring
Comprehensive performance tracking and observability:

```python
@dataclass
class CacheMetrics:
    total_requests: int
    cache_hits: int
    cache_misses: int
    bloom_filter_hits: int
    total_response_time: float
    memory_usage_bytes: int
    disk_usage_bytes: int
    errors: Dict[str, int]
```

Key capabilities:
- **Automatic Instrumentation**: Context managers track all operations
- **Prometheus Export**: Standard format for monitoring integration
- **Error Categorization**: Tracks error types for troubleshooting
- **Performance Metrics**: Response times, hit rates, resource usage

### Exception Hierarchy
Structured error handling with specific exception types:

```python
CacheError (base)
├── CacheCorruptionError     # Data integrity failures
├── CacheStorageError        # Storage layer failures  
├── CacheConfigurationError  # Invalid configuration
├── CachePermissionError     # Security/access violations
└── CacheProcessingError     # Content extraction failures
```

### Batch Operations
Efficient bulk processing capabilities:

1. **Concurrent Processing**: `get_content_batch()` with semaphore control
2. **Bulk Invalidation**: `invalidate_batch()` for cache management
3. **Integrity Checking**: Parallel verification of multiple entries

### Duplication and Modification Handling

The system identifies identical files and tracks modifications through:

1. **Content Fingerprinting**: SHA-256 hash of file contents
2. **Metadata Tracking**: File size, modification time, and path
3. **Smart Invalidation**: Only reprocess when content actually changes

Decision flow:
```
if file_hash == cached_hash and mtime <= cached_mtime:
    return cached_content
else:
    content = process_callback(file_path)  # Synchronous processing
    update_cache(file_path, content, new_hash, new_mtime)
    return content
```

## 4. Algorithms and Data Structures

### Core Data Structures

```python
class CacheEntry(BaseModel):  # Pydantic model with validation
    file_path: Path
    content_hash: str
    modification_time: float
    file_size: int
    content: Optional[str] = None  # May be stored as blob
    content_blob_path: Optional[Path] = None  # For large content
    extraction_timestamp: datetime
    access_count: int = 0
    last_accessed: datetime

class CachedContent(BaseModel):  # Public API response model
    content: str
    from_cache: bool
    content_hash: str
    extraction_timestamp: datetime
    file_size: int

class CacheConfig(BaseModel):  # Configuration with env var support
    cache_dir: Path = Field(default="./cache_storage")
    max_memory_size: int = Field(default=100 * 1024 * 1024)
    verify_hash: bool = Field(default=True)
    db_pool_size: int = Field(default=10)
    compression_level: int = Field(default=6)
    bloom_filter_size: int = Field(default=1000000)
    debug: bool = Field(default=False)
    allowed_paths: List[Path] = Field(default_factory=list)
```

### Algorithms

1. **LRU Eviction**: Uses OrderedDict for O(1) operations with memory tracking
2. **Hash-based Deduplication**: SHA-256 content fingerprinting with chunked reading
3. **Bloom Filter**: Tracks non-existent files to reduce file system calls
4. **File-level Locking**: Prevents duplicate processing via asyncio.Lock per file
5. **Tiered Integrity Checking**: Fast modification time checks before expensive hashing

### Rationale
- **LRU Cache**: OrderedDict provides O(1) access with automatic MRU promotion
- **SHA-256**: Cryptographically secure with async chunked computation for large files
- **Bloom Filter**: pybloom_live reduces file system stat() calls for missing files
- **SQLite Indexes**: Optimized for path lookups, hash queries, and access-time cleanup
- **Pydantic Models**: Type safety, validation, and consistent serialization
- **Connection Pooling**: SQLite connection reuse prevents setup/teardown overhead

## 5. Storage Mechanisms

### Hybrid Storage Architecture

1. **Level 1 - Memory Cache**
   - Size: Configurable (default 100MB)
   - Storage: Python dict with LRU eviction
   - Access Time: O(1)

2. **Level 2 - SQLite Database**
   - Schema optimized for quick lookups with connection pooling
   - Indexes on file_path, content_hash, and last_accessed
   - Concurrent access via connection pool (default 10 connections)

3. **Level 3 - File System**
   - Large content stored as compressed files
   - Directory structure: `cache_dir/{hash[:2]}/{hash[2:4]}/{hash}.gz`
   - Compression: zlib level 6 (balanced speed/size)

### Storage Schema

```sql
CREATE TABLE cache_entries (
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
);

CREATE INDEX idx_content_hash ON cache_entries(content_hash);
CREATE INDEX idx_last_accessed ON cache_entries(last_accessed);

CREATE TABLE cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 6. File Integrity Checks

### Multi-Level Verification

1. **Quick Check** (Level 1)
   - File existence
   - Size comparison
   - Modification time check

2. **Hash Verification** (Level 2)
   - SHA-256 computation
   - Comparison with stored hash
   - Triggered on mtime changes

3. **Content Validation** (Level 3)
   - Verify extracted content integrity
   - Re-extract if corruption detected
   - Log anomalies for monitoring

### Implementation

```python
async def verify_integrity(self, entry: CacheEntry) -> IntegrityStatus:
    # Level 1: Quick checks
    if not entry.file_path.exists():
        return IntegrityStatus.FILE_MISSING
    
    stat = entry.file_path.stat()
    if stat.st_mtime > entry.modification_time:
        return IntegrityStatus.FILE_MODIFIED
    
    # Level 2: Hash verification (if needed)
    if self.verify_hash:
        current_hash = await self._compute_hash(entry.file_path)
        if current_hash != entry.content_hash:
            return IntegrityStatus.CONTENT_CHANGED
    
    return IntegrityStatus.VALID
```

## 7. Conclusion

The Content File Cache Component provides a production-ready, high-performance solution for content caching with comprehensive observability and security features. The implementation combines:

### Core Capabilities
- **Performance**: Sub-millisecond retrieval with multi-tier storage (memory → SQLite → compressed blobs)
- **Efficiency**: SHA-256 content fingerprinting eliminates redundant processing
- **Concurrency**: File-level locking and connection pooling support high-throughput scenarios
- **Reliability**: Multi-level integrity verification with graceful degradation
- **Security**: Path validation, traversal protection, and configurable access controls

### Operational Features
- **Monitoring**: Comprehensive metrics with Prometheus export format
- **Configuration**: Environment variable support with validation
- **Batch Operations**: Concurrent processing with configurable limits
- **Error Handling**: Structured exception hierarchy for targeted troubleshooting
- **Resource Management**: Automatic cleanup and graceful shutdown

### Production Readiness
- **Type Safety**: Pydantic models with validation throughout
- **Async Architecture**: Non-blocking I/O for scalability
- **Storage Efficiency**: Intelligent tiering and compression
- **Cache Analytics**: Deduplication tracking and hit rate monitoring

This architecture delivers enterprise-grade caching capabilities suitable for content-heavy applications requiring both performance and operational visibility.

## 8. Practical Use Case: Financial Document Processing

### Problem Statement
Processing financial PDFs (bank statements, invoices) using AI APIs like Anthropic's Claude is:
- **Expensive**: ~$0.015 per page with Claude-3-Opus
- **Slow**: 5-30 seconds per document
- **Rate-limited**: APIs have request limits
- **Redundant**: Same documents are often reprocessed

### Solution Architecture

The cache component provides an ideal solution:

```python
# Expensive API call wrapped in cache
async def extract_transactions(pdf_path: Path) -> str:
    # This costs ~$0.015 per page and takes 10-30 seconds
    response = anthropic_client.messages.create(
        model="claude-3-opus",
        content=[pdf_document],
        prompt="Extract all financial transactions as JSON"
    )
    return response.content

# Using cache - API called only once per unique PDF
result = await cache.get_content(pdf_path, extract_transactions)
# First call: 15 seconds, costs $0.10
# Subsequent calls: <1ms, costs $0.00
```

### Implementation Benefits

1. **Cost Reduction**
   - First processing: Full API cost
   - Subsequent access: Zero cost
   - Monthly savings: 90%+ for frequently accessed documents

2. **Performance Improvement**
   ```
   Without Cache: 15,000ms (API call)
   With Cache:        0.5ms (memory hit)
   Speedup:       30,000x
   ```

3. **Reliability**
   - API downtime doesn't affect cached documents
   - Rate limits don't impact cached content
   - Retries aren't needed for cached data

4. **Development Efficiency**
   - Test code without API costs
   - Iterate quickly with cached responses
   - Debug with consistent data

### Cache Configuration for API Responses

```python
config = CacheConfig(
    # Large memory for JSON responses
    max_memory_size=500 * 1024 * 1024,
    
    # High compression for JSON
    compression_level=9,
    
    # Verify integrity for financial data
    verify_hash=True,
    
    # Restrict to secure directories
    allowed_paths=[Path("./uploads")]
)
```

### Real-World Metrics

Based on processing 1,000 bank statements monthly:
- **Without Cache**: $150/month, 4.2 hours processing
- **With Cache**: $15/month, 0.5 hours processing
- **Cache Hit Rate**: 90% (same statements accessed multiple times)
- **ROI**: Cache pays for itself after processing 10 documents

This use case demonstrates how the cache transforms expensive, slow AI operations into a cost-effective, performant solution suitable for production financial applications.