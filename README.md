# Content File Cache Component

A high-performance, multi-format content caching solution designed for efficient file content extraction and retrieval. This component intelligently detects file changes and eliminates redundant processing by serving cached content when files remain unchanged.

## Features

- **High Performance**: Sub-millisecond retrieval for cached content
- **Multi-Format Support**: Handles PDF, Markdown, Text, and extensible to other formats
- **Smart Change Detection**: SHA-256 hashing with modification time tracking
- **Hybrid Storage**: In-memory LRU cache + SQLite persistence + compressed file storage
- **Pluggable Processors**: Use custom content extraction functions via callbacks
- **Thread-Safe**: Concurrent access support with proper locking mechanisms
- **Deduplication**: Automatically detects and handles duplicate files
- **Integrity Checks**: Multi-level verification ensures data consistency
- **Smart Re-download Detection**: Recognizes identical content in re-downloaded files
- **Comprehensive Metrics**: Built-in performance monitoring with Prometheus export
- **Security Features**: Path validation and traversal attack prevention
- **Batch Processing**: Concurrent processing with configurable limits

## Installation

```bash
pip install content-file-cache
```

Or install from source:

```bash
git clone https://github.com/repque/content-cache.git
cd content-cache
pip install -e .
```

For the PDF processing examples with Anthropic's API, also install:

```bash
pip install anthropic aiohttp aiofiles
```

## Pipeline Integration Guide

This guide shows developers how to integrate the content-file-cache into existing pipelines with minimal code changes.

### At a Glance: 3-Step Integration

```python
# 1. Import
from content_cache import ContentCache

# 2. Use context manager (handles init + cleanup automatically)
async with ContentCache() as cache:
    # 3. Replace expensive operations
    # BEFORE: content = await expensive_llm_call(file_path)
    # AFTER:
    result = await cache.get_content(file_path, expensive_llm_call)
    # Automatic cleanup on exit
```

### Migration Examples: Before & After

#### Pipeline Type 1: Document Processing with LLM APIs

**Scenario**: You have a script that extracts data from PDFs using Claude API

**BEFORE (Expensive - no caching):**
```python
import anthropic
from pathlib import Path

client = anthropic.Anthropic(api_key="your-key")

async def process_invoices(pdf_files: list[Path]):
    for pdf_path in pdf_files:
        # Every run costs $0.075 per PDF
        with open(pdf_path, 'rb') as f:
            pdf_data = base64.b64encode(f.read()).decode()

        message = client.messages.create(
            model="claude-3-opus-20240229",
            messages=[{"role": "user", "content": [...]}]
        )

        result = message.content[0].text
        print(f"Extracted: {result}")
```

**AFTER (With caching - 3 line change):**
```python
import anthropic
from pathlib import Path
from content_cache import ContentCache  # 1. Import

client = anthropic.Anthropic(api_key="your-key")

async def extract_from_pdf(pdf_path: Path) -> str:
    """Your existing extraction logic - unchanged"""
    with open(pdf_path, 'rb') as f:
        pdf_data = base64.b64encode(f.read()).decode()

    message = client.messages.create(
        model="claude-3-opus-20240229",
        messages=[{"role": "user", "content": [...]}]
    )
    return message.content[0].text

async def process_invoices(pdf_files: list[Path]):
    # 2. Use context manager (automatic init + cleanup)
    async with ContentCache() as cache:
        for pdf_path in pdf_files:
            # 3. Use cache - first run processes, subsequent runs <1ms
            result = await cache.get_content(pdf_path, extract_from_pdf)
            print(f"Extracted: {result.content} (cached: {result.from_cache})")
    # Automatic cleanup when exiting context
```

**Benefits:**
- First run: Same as before
- Subsequent runs: Free, <1ms response
- Processing 100 PDFs 50 times: $375 vs $18,750 without cache
- File changes automatically trigger reprocessing

#### Pipeline Type 2: FastAPI Web Service

**Scenario**: API endpoint that processes uploaded documents

**BEFORE (No caching):**
```python
from fastapi import FastAPI, UploadFile
import shutil

app = FastAPI()

@app.post("/api/extract")
async def extract_document(file: UploadFile):
    # Save uploaded file
    upload_path = f"./uploads/{file.filename}"
    with open(upload_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Process every time - even for same file
    content = await expensive_extraction(Path(upload_path))

    return {"content": content}
```

**AFTER (With caching):**
```python
from fastapi import FastAPI, UploadFile
from content_cache import ContentCache, CacheConfig
from pathlib import Path
import shutil

app = FastAPI()
cache = None

@app.on_event("startup")
async def startup():
    global cache
    # Initialize cache (manual management for long-lived service)
    cache = ContentCache(config=CacheConfig(
        allowed_paths=[Path("./uploads")]  # Security
    ))
    await cache.initialize()

@app.on_event("shutdown")
async def shutdown():
    # Explicit cleanup on service shutdown
    if cache:
        await cache.close()

@app.post("/api/extract")
async def extract_document(file: UploadFile):
    upload_path = Path(f"./uploads/{file.filename}")
    with open(upload_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Cache handles deduplication across users
    result = await cache.get_content(upload_path, expensive_extraction)

    return {
        "content": result.content,
        "from_cache": result.from_cache,
        "cost_saved": result.from_cache  # True = $0.075 saved
    }
```

**Benefits:**
- Multiple users uploading same document: Process once
- Re-uploads of same file: Instant response from cache
- Development testing: No API charges after first run
- Security: `allowed_paths` prevents directory traversal

#### Pipeline Type 3: Distributed Task Queue (Celery with Redis)

**Scenario**: Multiple Celery workers processing documents

**BEFORE (Each worker processes independently):**
```python
from celery import Celery

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
def process_document(file_path: str):
    # Worker 1 processes doc.pdf at 10:00 AM
    # Worker 2 processes same doc.pdf at 10:01 AM (duplicate work!)
    result = expensive_extraction(Path(file_path))
    return result
```

**AFTER (Shared Redis cache - no duplicate work):**
```python
from celery import Celery
from content_cache import ContentCache
from content_cache.redis_storage import RedisStorage
from redis.asyncio import Redis
from pathlib import Path

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
async def process_document(file_path: str):
    # Create cache with Redis backend (shared across workers)
    redis = Redis.from_url("redis://localhost:6379/0")

    # Use context manager for automatic cleanup
    async with ContentCache(storage=RedisStorage(redis)) as cache:
        # Worker 1 processes at 10:00 AM (cache miss)
        # Worker 2 at 10:01 AM (cache hit - instant!)
        result = await cache.get_content(Path(file_path), expensive_extraction)
        return result.content
    # Redis connection and cache automatically closed
```

**Benefits:**
- Workers share cache: No duplicate API calls
- Distributed deduplication: Same file processed once across all workers
- Cost savings scale with worker count
- Persistent cache: Survives worker restarts

### Step-by-Step Integration Workflow

#### Step 1: Identify Expensive Operations

Look for operations that should be cached:
- LLM API calls (Claude, GPT-4, etc.) - $0.01-$0.10 per request
- OCR services (Textract, Vision) - $0.001-$0.05 per page
- Document parsing with external APIs
- Any per-file processing cost

#### Step 2: Extract Processor Function

Create a standalone async function for your expensive operation:

```python
# Your existing inline code:
content = client.messages.create(model="...", messages=[...])

# Extract to function:
async def extract_with_claude(file_path: Path) -> str:
    """Expensive Claude API call - will be cached."""
    with open(file_path, 'rb') as f:
        data = base64.b64encode(f.read()).decode()

    message = client.messages.create(
        model="claude-3-opus-20240229",
        messages=[{"role": "user", "content": [...]}]
    )
    return message.content[0].text
```

#### Step 3: Choose Storage Backend

**Use SQLite (default)** for:
- Single-process applications
- CLI tools
- Development environments
- Single web server instances

```python
cache = ContentCache()  # Simple!
```

**Use Redis** for:
- Multi-worker deployments (Celery, Ray)
- Multiple server instances
- Distributed systems
- Shared cache across processes

```python
from redis.asyncio import Redis
from content_cache.redis_storage import RedisStorage

redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
cache = ContentCache(storage=RedisStorage(redis))
```

#### Step 4: Integrate Cache Calls

Replace direct function calls with cache-wrapped calls:

```python
# BEFORE: Direct call
content = await extract_with_claude(file_path)

# AFTER: Cache-wrapped
result = await cache.get_content(file_path, extract_with_claude)
content = result.content
```

#### Step 5: Use Context Manager for Resource Management

**Always use `async with` for automatic cleanup** (recommended):

```python
# Best practice: Context manager handles init + cleanup
async with ContentCache() as cache:
    result = await cache.get_content(file_path, processor)
# Automatic cleanup on exit (even if exceptions occur)
```

**Only use manual cleanup for long-lived services**:

```python
# For services that run continuously (FastAPI, etc.)
cache = ContentCache()
await cache.initialize()

# ... use cache across many requests ...

# Cleanup on service shutdown
await cache.close()
```

### Configuration Selection Guide

**Minimal Configuration (Good for most cases):**
```python
cache = ContentCache()  # Uses sensible defaults
```

**Production Configuration:**
```python
config = CacheConfig(
    cache_dir=Path("./cache_storage"),
    max_memory_size=500 * 1024 * 1024,  # 500MB
    verify_hash=True,                    # Data integrity
    allowed_paths=[Path("/safe/uploads")],  # Security
    compression_level=6,                 # Balance speed/size
)
cache = ContentCache(config=config)
```

**High-Concurrency Configuration:**
```python
config = CacheConfig(
    db_pool_size=20,  # More concurrent DB connections
    max_memory_size=1024 * 1024 * 1024,  # 1GB memory cache
    bloom_filter_size=10000000,  # Large filter for better perf
)
```

### Common Patterns

**Note**: All patterns below use `async with` context manager for automatic resource management. This ensures proper initialization and cleanup, even when exceptions occur.

#### Pattern 1: Service Class with Cache

```python
class DocumentService:
    def __init__(self, use_redis: bool = False):
        if use_redis:
            redis = Redis.from_url(os.getenv("REDIS_URL"))
            self.cache = ContentCache(storage=RedisStorage(redis))
        else:
            self.cache = ContentCache()

    async def process(self, file_path: Path) -> str:
        result = await self.cache.get_content(file_path, self._extract)
        return result.content

    async def _extract(self, file_path: Path) -> str:
        # Your extraction logic
        pass

    async def close(self):
        await self.cache.close()
```

#### Pattern 2: Batch Processing with Progress Tracking

```python
async def process_batch(files: list[Path]):
    async with ContentCache() as cache:
        for i, file_path in enumerate(files, 1):
            result = await cache.get_content(file_path, processor)

            status = "CACHED" if result.from_cache else "PROCESSED"
            print(f"[{i}/{len(files)}] {file_path.name} - {status}")

        # Show statistics
        stats = await cache.get_statistics()
        print(f"\nCache hit rate: {stats['hit_rate']:.1%}")
        print(f"API calls saved: {stats['cache_hits']}")
    # Automatic cleanup
```

#### Pattern 3: Error Handling and Fallback

```python
async def robust_extraction(file_path: Path):
    async with ContentCache() as cache:
        try:
            result = await cache.get_content(file_path, expensive_processor)
            return result.content
        except CacheProcessingError as e:
            # Processor failed - handle gracefully
            logger.error(f"Processing failed: {e}")
            return None
        except CachePermissionError:
            # File outside allowed paths
            logger.warning(f"Access denied: {file_path}")
            return None
    # Context manager ensures cleanup even if exceptions occur
```

#### Pattern 4: Conditional Caching

```python
async def smart_process(file_path: Path, force_refresh: bool = False):
    async with ContentCache() as cache:
        if force_refresh:
            # Invalidate cache and reprocess
            await cache.invalidate(file_path)

        result = await cache.get_content(file_path, processor)
        return result.content
    # Automatic cleanup
```

### Quick Troubleshooting

**Issue**: "Cache always misses even for unchanged files"
```python
# Solution: Ensure file_path is consistent (absolute vs relative)
file_path = Path("doc.pdf").resolve()  # Use absolute path
```

**Issue**: "Permission denied errors"
```python
# Solution: Add file location to allowed_paths
config = CacheConfig(
    allowed_paths=[Path("/your/upload/directory")]
)
```

**Issue**: "High memory usage"
```python
# Solution: Reduce memory cache size
config = CacheConfig(
    max_memory_size=50 * 1024 * 1024  # 50MB instead of default 100MB
)
```

**Issue**: "Redis connection errors in multi-worker setup"
```python
# Solution: Use connection pooling
redis = Redis.from_url(
    "redis://localhost:6379/0",
    max_connections=50  # Pool for multiple workers
)
```

### Next Steps

Once integrated, consider:

1. **Monitor Performance**: Track cache hit rates
```python
stats = await cache.get_statistics()
logger.info(f"Cache efficiency: {stats['hit_rate']:.1%}")
```

2. **Set Up Metrics**: Export to Prometheus
```python
metrics = cache.get_metrics_prometheus()
# Push to monitoring system
```

3. **Schedule Cleanup**: Remove stale entries
```python
# Remove entries not accessed in 30 days
removed = await cache.clear_old_entries(days=30)
```

4. **Security Review**: Validate allowed paths
```python
config = CacheConfig(
    allowed_paths=[Path("/safe/uploads")],  # Whitelist only
)
```

## Simple Usage

For basic usage without downloads:

```python
import asyncio
from pathlib import Path
from content_cache import ContentCache, CacheConfig

# Define your content processor (must be async)
async def process_pdf(file_path: Path) -> str:
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

## Real-World Example: Transaction Extraction with Anthropic API

Here's a production-ready example that shows how to use the cache with expensive API calls:

```python
import asyncio
import json
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import anthropic

from content_cache import ContentCache, CacheConfig


class TransactionExtractor:
    """Extract financial transactions from PDFs using Anthropic's Claude API."""
    
    def __init__(self, api_key: str, cache_dir: Path = Path("./transaction_cache")):
        # Initialize Anthropic client
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # Configure cache for API responses
        config = CacheConfig(
            cache_dir=cache_dir,
            max_memory_size=500 * 1024 * 1024,  # 500MB
            verify_hash=True,  # Ensure data integrity
            compression_level=6,  # JSON compresses well
            # Optional: restrict to specific directories for security
            allowed_paths=[Path("./uploads"), Path("./documents")]
        )
        
        self.cache = ContentCache(config=config)
        self.stats = {
            'api_calls_made': 0,
            'api_calls_saved': 0,
            'total_cost_saved': 0.0
        }
    
    async def extract_transactions(self, pdf_path: Path) -> str:
        """Extract transactions from PDF using Claude API.
        
        This is the expensive operation we want to cache.
        Cost: ~$0.015 per page with Claude-3-Opus
        """
        print(f"\nCalling Anthropic API for {pdf_path.name}...")
        self.stats['api_calls_made'] += 1
        
        # Read and encode PDF
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
            pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
        
        # Calculate approximate cost
        file_size_mb = len(pdf_data) / (1024 * 1024)
        estimated_pages = max(1, int(file_size_mb * 4))
        estimated_cost = estimated_pages * 0.015
        
        # Call Claude API
        try:
            message = self.client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4096,
                temperature=0,  # Deterministic for caching
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """Analyze this financial document and extract ALL transactions.
                                
                                For each transaction, extract:
                                - date (ISO format: YYYY-MM-DD)
                                - description
                                - amount (as float, negative for debits)
                                - type ("debit" or "credit")
                                - category (best guess: groceries, utilities, salary, etc.)
                                - merchant (if identifiable)
                                
                                Return ONLY a JSON array of transactions, no other text.
                                
                                Example format:
                                [
                                  {
                                    "date": "2024-01-15",
                                    "description": "WHOLE FOODS MARKET",
                                    "amount": -127.43,
                                    "type": "debit",
                                    "category": "groceries",
                                    "merchant": "Whole Foods"
                                  }
                                ]"""
                            },
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_base64
                                }
                            }
                        ]
                    }
                ]
            )
            
            result = message.content[0].text
            
            # Validate JSON
            transactions = json.loads(result)
            
            print(f"Extracted {len(transactions)} transactions (cost: ~${estimated_cost:.3f})")
            return json.dumps(transactions, indent=2)
            
        except Exception as e:
            print(f"API Error: {str(e)}")
            return json.dumps({"error": str(e), "timestamp": datetime.now().isoformat()})
    
    async def process_statements(self, pdf_paths: List[Path], max_concurrent: int = 2) -> Dict[str, any]:
        """Process multiple bank statements with caching.
        
        Args:
            pdf_paths: List of PDF files to process
            max_concurrent: Max concurrent API calls (respect rate limits)
        """
        print(f"\nProcessing {len(pdf_paths)} PDF files...")
        print(f"Cache enabled at: {self.cache.config.cache_dir}\n")
        
        results = {}
        
        # Process files
        for pdf_path in pdf_paths:
            # This will use cache if available, otherwise call extract_transactions
            start_time = asyncio.get_event_loop().time()
            
            cache_result = await self.cache.get_content(
                pdf_path,
                self.extract_transactions
            )
            
            elapsed = asyncio.get_event_loop().time() - start_time
            
            # Track savings
            if cache_result.from_cache:
                self.stats['api_calls_saved'] += 1
                # Estimate cost saved
                file_size = pdf_path.stat().st_size / (1024 * 1024)
                pages = max(1, int(file_size * 4))
                self.stats['total_cost_saved'] += pages * 0.015
            
            # Parse results
            try:
                transactions = json.loads(cache_result.content)
                results[pdf_path.name] = {
                    'transactions': transactions,
                    'count': len(transactions) if isinstance(transactions, list) else 0,
                    'from_cache': cache_result.from_cache,
                    'processing_time': elapsed,
                    'file_hash': cache_result.content_hash[:16]
                }
                
                status = "CACHED" if cache_result.from_cache else "PROCESSED"
                print(f"{status} {pdf_path.name}: {results[pdf_path.name]['count']} transactions ({elapsed:.2f}s)")
                
            except json.JSONDecodeError:
                results[pdf_path.name] = {
                    'error': 'Failed to parse response',
                    'from_cache': cache_result.from_cache
                }
        
        # Print statistics
        print(f"\nCache Performance:")
        print(f"   - API calls made: {self.stats['api_calls_made']}")
        print(f"   - API calls saved: {self.stats['api_calls_saved']}")
        print(f"   - Estimated cost saved: ${self.stats['total_cost_saved']:.2f}")
        
        cache_stats = await self.cache.get_statistics()
        print(f"   - Cache hit rate: {cache_stats['hit_rate']:.1%}")
        print(f"   - Memory usage: {cache_stats['memory_usage_mb']:.1f} MB")
        
        return results
    
    async def close(self):
        """Clean up resources."""
        await self.cache.close()


# Example usage
async def main():
    # Initialize extractor
    extractor = TransactionExtractor(
        api_key="your-anthropic-api-key",
        cache_dir=Path("./transaction_cache")
    )
    
    # Process bank statements
    pdf_files = [
        Path("./statements/checking_jan_2024.pdf"),
        Path("./statements/checking_feb_2024.pdf"),
        Path("./statements/credit_card_jan_2024.pdf"),
    ]
    
    # First run - will call API
    print("=== FIRST RUN (API CALLS) ===")
    results = await extractor.process_statements(pdf_files)
    
    # Second run - will use cache (instant!)
    print("\n\n=== SECOND RUN (CACHED) ===")
    results = await extractor.process_statements(pdf_files)
    
    await extractor.close()


if __name__ == "__main__":
    asyncio.run(main())
```
### Key Benefits of Caching API Calls:

1. **Cost Savings**: Each Claude API call costs ~$0.015 per page. Cache saves money on repeated processing.
2. **Speed**: Cached responses return in <1ms vs 5-30s for API calls
3. **Rate Limit Protection**: Reduce API calls to stay within rate limits
4. **Reliability**: Continue working even if API is temporarily unavailable
5. **Development**: Test your code without burning through API credits
6. **Smart Re-download Detection**: Cache recognizes when re-downloaded files have identical content and serves from cache

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

## Advanced Configuration

### Environment Variables

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

### Performance Tuning

```python
from content_cache import ContentCache, CacheConfig

# High-performance configuration
config = CacheConfig(
    cache_dir=Path("./cache"),
    max_memory_size=500 * 1024 * 1024,  # 500MB for large datasets
    verify_hash=True,  # Enable for data integrity
    db_pool_size=20,  # Increase for high concurrency
    compression_level=9,  # Max compression for storage efficiency
    bloom_filter_size=10000000,  # Large bloom filter for better performance
    debug=False  # Disable for production
)
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

## More Examples

Check out the `examples/` directory for complete, runnable examples:

- **`simple_usage.py`** - Basic usage with text file processing
- **`pdf_transaction_extraction.py`** - Real-world example using Anthropic's API to extract transactions from bank statements
- **`redownload_test.py`** - Demonstrates smart re-download detection

```bash
# Run the simple example
python examples/simple_usage.py

# Run the PDF processing example (requires Anthropic API key)
export ANTHROPIC_API_KEY="your-api-key"
python examples/pdf_transaction_extraction.py

# Test re-download detection
python examples/redownload_test.py
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


## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the Apache License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with performance insights from production workloads
- Inspired by modern caching strategies in distributed systems
- Special thanks to the open-source community

## Support

- Email: repque@gmail.com
- Issues: [GitHub Issues](https://github.com/repque/content-file-cache/issues)
