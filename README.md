# Content File Cache Component

A high-performance, multi-format content caching solution designed for efficient file content extraction and retrieval. This component intelligently detects file changes and eliminates redundant processing by serving cached content when files remain unchanged.

## Features

- 🚀 **High Performance**: Sub-millisecond retrieval for cached content
- 📁 **Multi-Format Support**: Handles PDF, Markdown, Text, and extensible to other formats
- 🔍 **Smart Change Detection**: SHA-256 hashing with modification time tracking
- **Hybrid Storage**: In-memory LRU cache + SQLite persistence + compressed file storage
- 🔌 **Pluggable Processors**: Use custom content extraction functions via callbacks
- 🔒 **Thread-Safe**: Concurrent access support with proper locking mechanisms
- **Deduplication**: Automatically detects and handles duplicate files
- 🛡️ **Integrity Checks**: Multi-level verification ensures data consistency
- **Smart Re-download Detection**: Recognizes identical content in re-downloaded files
- 📈 **Comprehensive Metrics**: Built-in performance monitoring with Prometheus export
- 🔐 **Security Features**: Path validation and traversal attack prevention
- ⚡ **Batch Processing**: Concurrent processing with configurable limits

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
