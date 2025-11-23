# Content File Cache

High-performance caching for expensive file operations. Eliminate redundant LLM API calls, OCR processing, and document extraction with intelligent content-addressable caching.

**Transform this:**
- Claude API call: ~$0.075 per PDF, 5-30s latency
- Processing 100 PDFs 50 times: **$3,750 cost**

**Into this:**
- First run: $0.075, 5-30s (processes once)
- Subsequent runs: **$0, <1ms** (cached)
- Processing 100 PDFs 50 times: **$75 cost** (98% savings)

## Quick Start

```bash
pip install content-file-cache
```

```python
import asyncio
from pathlib import Path
from content_cache import ContentCache

async def expensive_operation(file_path: Path) -> str:
    # Your expensive LLM/OCR/processing logic here
    return f"Processed content from {file_path.name}"

async def main():
    async with ContentCache() as cache:
        # First call: processes file
        result = await cache.get_content(Path("document.pdf"), expensive_operation)
        print(f"From cache: {result.from_cache}")  # False

        # Second call: instant cache hit
        result = await cache.get_content(Path("document.pdf"), expensive_operation)
        print(f"From cache: {result.from_cache}")  # True

asyncio.run(main())
```

## Key Features

- **Sub-millisecond cache hits** - In-memory LRU + SQLite + compressed blob storage
- **Automatic change detection** - SHA-256 + mtime tracking, reprocesses when files change
- **Distributed caching** - Redis backend for multi-worker deployments (Celery, Ray, etc.)
- **Smart deduplication** - Identical content cached once, even across different file paths
- **Production-ready** - Integrity checks, security (path validation), Prometheus metrics
- **Zero-config** - Works out of box, customizable for advanced use cases

## Distributed Caching (Redis)

Share cache across multiple workers to prevent duplicate processing:

```bash
pip install content-file-cache[redis]
```

```python
from redis.asyncio import Redis
from content_cache import ContentCache
from content_cache.redis_storage import RedisStorage

async def celery_task(file_path: str):
    redis = Redis.from_url("redis://localhost:6379/0")

    async with ContentCache(storage=RedisStorage(redis)) as cache:
        # All workers share this cache
        result = await cache.get_content(Path(file_path), expensive_operation)
        return result.content
```

## Configuration

```python
from content_cache import ContentCache, CacheConfig
from pathlib import Path

config = CacheConfig(
    cache_dir=Path("./cache_storage"),
    max_memory_size=500 * 1024 * 1024,      # 500MB LRU cache
    verify_hash=True,                        # Integrity verification
    allowed_paths=[Path("./safe/uploads")], # Security
    compression_level=6,                     # 0-9 (higher = smaller)
)

async with ContentCache(config=config) as cache:
    result = await cache.get_content(file_path, processor)
```

## Examples

Check out `examples/` directory for complete examples:
- `simple_usage.py` - Basic file processing
- `pdf_transaction_extraction.py` - Real-world Anthropic API caching
- `redis_example.py` - Multi-worker distributed caching

```bash
python examples/simple_usage.py
```

## API Reference

**ContentCache**
- `async get_content(file_path, processor)` - Get cached content or process
- `async get_content_batch(files, processor, max_concurrent=5)` - Batch processing
- `async invalidate(file_path)` - Remove from cache
- `async get_statistics()` - Performance metrics
- `get_metrics_prometheus()` - Prometheus format metrics

**CachedContent** (return value)
- `content: str` - Extracted content
- `from_cache: bool` - Whether served from cache
- `content_hash: str` - SHA-256 hash
- `file_size: int` - Original file size

## License

Apache License - see [LICENSE](LICENSE) file for details.

## Support

- Email: repque@gmail.com
- Issues: [GitHub Issues](https://github.com/repque/content-file-cache/issues)
