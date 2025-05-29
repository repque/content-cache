# Content File Cache Component

A high-performance, multi-format content caching solution designed for efficient file content extraction and retrieval. This component intelligently detects file changes and eliminates redundant processing by serving cached content when files remain unchanged.

## Features

- 🚀 **High Performance**: Sub-millisecond retrieval for cached content
- 📁 **Multi-Format Support**: Handles PDF, Markdown, Text, and extensible to other formats
- 🔍 **Smart Change Detection**: SHA-256 hashing with modification time tracking
- 💾 **Hybrid Storage**: In-memory LRU cache + SQLite persistence + compressed file storage
- 🔌 **Pluggable Processors**: Use custom content extraction functions via callbacks
- 🔒 **Thread-Safe**: Concurrent access support with proper locking mechanisms
- 📊 **Deduplication**: Automatically detects and handles duplicate files
- 🛡️ **Integrity Checks**: Multi-level verification ensures data consistency

## Installation

```bash
pip install content-file-cache
```

Or install from source:

```bash
git clone https://github.com/yourusername/content-file-cache.git
cd content-file-cache
pip install -e .
```

## Simple Usage

For basic usage without downloads:

```python
import asyncio
from pathlib import Path
from content_cache import ContentCache, CacheConfig

# Define your content processor
def process_pdf(file_path: Path) -> str:
    # Your PDF extraction logic here
    return f"Extracted content from {file_path.name}"

async def main():
    # Initialize cache with configuration
    config = CacheConfig(
        cache_dir=Path("./cache_storage"),
        max_memory_size=100 * 1024 * 1024  # 100MB
    )
    cache = ContentCache(config=config)
    
    # Get content (processes if not cached)
    pdf_path = Path("document.pdf")
    result = await cache.get_content(pdf_path, process_pdf)
    
    print(f"Content: {result.content}")
    print(f"From cache: {result.from_cache}")
    
    # Graceful shutdown
    await cache.close()

asyncio.run(main())
```

### Key Benefits of Caching API Calls:

1. **Cost Savings**: Each Claude API call costs ~$0.015 per page. Cache saves money on repeated processing.
2. **Speed**: Cached responses return in <1ms vs 5-30s for API calls
3. **Rate Limit Protection**: Reduce API calls to stay within rate limits
4. **Reliability**: Continue working even if API is temporarily unavailable
5. **Development**: Test your code without burning through API credits

## Usage Examples

### Basic File Processing

```python
# Process different file types
async def process_markdown(file_path: Path) -> str:
    async with aiofiles.open(file_path, 'r') as f:
        return await f.read()

# First access - processes the file
md_content = await cache.get_content(Path("README.md"), process_markdown)
print(f"Processed: {not md_content.from_cache}")  # True

# Second access - uses cache
md_content = await cache.get_content(Path("README.md"), process_markdown)
print(f"From cache: {md_content.from_cache}")  # True
```

### Handling Modified Files

```python
# Cache automatically detects file modifications
config_path = Path("config.json")

# Initial processing
content1 = await cache.get_content(config_path, process_json)

# File gets modified externally...

# Automatic reprocessing on next access
content2 = await cache.get_content(config_path, process_json)
# content2 will contain the updated content
```

### Batch Processing with Deduplication

```python
files = [
    Path("doc1.pdf"),
    Path("doc2.pdf"), 
    Path("doc1_copy.pdf"),  # Duplicate of doc1.pdf
]

# Process files concurrently with batch processing
results = await cache.get_content_batch(files, process_pdf, max_concurrent=5)

for result in results:
    print(f"Hash: {result.content_hash[:8]}... From cache: {result.from_cache}")

# Output shows doc1.pdf and doc1_copy.pdf have same hash
```

### Cache Management

```python
# Get cache statistics
stats = await cache.get_statistics()
print(f"Hit rate: {stats['hit_rate']:.2%}")
print(f"Duplicate groups: {stats['duplicate_groups']}")

# Invalidate specific file
await cache.invalidate(Path("old_file.pdf"))

# Invalidate multiple files
files_to_remove = [Path("old1.pdf"), Path("old2.pdf")]
removed_count = await cache.invalidate_batch(files_to_remove)

# Clear old entries (based on last access time)
removed = await cache.clear_old_entries(days=30)
print(f"Removed {removed} stale entries")

# Get Prometheus metrics
prometheus_metrics = cache.get_metrics_prometheus()
print(prometheus_metrics)
```

## Configuration

```python
from content_cache import ContentCache, CacheConfig

# Method 1: Direct configuration
config = CacheConfig(
    cache_dir=Path("./cache_storage"),
    max_memory_size=100 * 1024 * 1024,  # 100MB
    verify_hash=True,
    db_pool_size=10,
    compression_level=6,
    bloom_filter_size=1000000,
    debug=False,
    allowed_paths=[Path("/safe/directory")]  # Security: restrict file access
)
cache = ContentCache(config=config)

# Method 2: Environment variables (see Environment Configuration section)
# Set CACHE_DIR=/path/to/cache, MAX_MEMORY_SIZE=104857600, etc.
config = CacheConfig()  # Reads from environment
cache = ContentCache(config=config)
```

## Advanced Usage

### Environment Configuration

All configuration can be set via environment variables:

```bash
export CACHE_DIR="/path/to/cache"
export MAX_MEMORY_SIZE="104857600"  # 100MB
export VERIFY_HASH="true"
export DB_POOL_SIZE="10"
export COMPRESSION_LEVEL="6"
export BLOOM_FILTER_SIZE="1000000"
export DEBUG="false"
```

### Security Configuration

```python
# Restrict cache to specific directories for security
config = CacheConfig(
    allowed_paths=[
        Path("/safe/documents"),
        Path("/uploads")
    ]
)
cache = ContentCache(config=config)

# This will raise CachePermissionError
try:
    await cache.get_content(Path("/etc/passwd"), process_text)
except CachePermissionError:
    print("Access denied to file outside allowed paths")
```

### Batch Processing

```python
# Process multiple files efficiently
files = [Path(f"doc{i}.pdf") for i in range(100)]
results = await cache.get_content_batch(
    files, 
    process_pdf, 
    max_concurrent=10  # Limit concurrent processing
)
```

## API Reference

### ContentCache

#### Methods

- `async get_content(file_path, process_callback) -> CachedContent`
  - Retrieves content from cache or processes file
  - Returns `CachedContent` object with content and metadata

- `async invalidate(file_path) -> bool`
  - Removes specific file from cache
  - Returns True if entry was removed

- `async clear_old_entries(days) -> int`
  - Removes entries not accessed within specified days
  - Returns number of entries removed

- `async get_statistics() -> dict`
  - Returns cache performance statistics

- `async invalidate_batch(file_paths) -> int`
  - Removes multiple files from cache
  - Returns number of entries invalidated

- `async get_content_batch(file_paths, process_callback, max_concurrent) -> List[CachedContent]`
  - Processes multiple files efficiently with controlled concurrency
  - Returns list of results in same order as input

- `get_metrics_prometheus() -> str`
  - Returns cache metrics in Prometheus format

- `async close() -> None`
  - Performs graceful shutdown and resource cleanup

### CacheConfig

#### Attributes

- `cache_dir: Path` - Directory for cache storage (default: "./cache_storage")
- `max_memory_size: int` - Memory cache limit in bytes (default: 100MB)
- `verify_hash: bool` - Enable content hash verification (default: True)
- `db_pool_size: int` - SQLite connection pool size (default: 10)
- `compression_level: int` - Compression level 0-9 (default: 6)
- `bloom_filter_size: int` - Bloom filter capacity (default: 1,000,000)
- `debug: bool` - Enable debug logging (default: False)
- `allowed_paths: List[Path]` - Restrict file access to these paths (default: no restriction)

### CachedContent

#### Attributes

- `content: str` - The extracted content
- `from_cache: bool` - Whether content was served from cache
- `content_hash: str` - SHA-256 hash of file content
- `extraction_timestamp: datetime` - When content was extracted
- `file_size: int` - Original file size in bytes

## Performance

Benchmark results on typical workload:

| Operation | Time | Notes |
|-----------|------|-------|
| Cache hit | <1ms | In-memory retrieval |
| Cache miss (PDF) | 50-200ms | Depends on file size |
| Hash computation | 5-20ms | For 10MB file |
| Duplicate detection | <1ms | Hash lookup |

## Comparison with Redis

Wondering how this compares to Redis? See our detailed [Redis Comparison Guide](docs/REDIS_COMPARISON.md) for:
- Architecture differences
- Performance characteristics  
- Use case analysis
- When to use each solution

## More Examples

Check out the `examples/` directory for complete, runnable examples:

- **`simple_usage.py`** - Basic usage with text file processing
- **`pdf_transaction_extraction.py`** - Real-world example using Anthropic's API to extract transactions from bank statements

```bash
# Run the simple example
python examples/simple_usage.py

# Run the PDF processing example (requires Anthropic API key)
export ANTHROPIC_API_KEY="your-api-key"
python examples/pdf_transaction_extraction.py
```

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the Apache License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with performance insights from production workloads
- Inspired by modern caching strategies in distributed systems
- Special thanks to the open-source community

## Support

- 📧 Email: repque@gmail.com
- 🐛 Issues: [GitHub Issues](https://github.com/repque/content-file-cache/issues)
