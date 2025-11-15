"""
Example demonstrating RedisStorage usage for distributed caching.

This example shows how to use RedisStorage for multi-process deployments
where cache sharing eliminates duplicate processing.
"""
import asyncio
from pathlib import Path

# Optional import - will fail gracefully if redis not installed
try:
    from redis.asyncio import Redis
    from content_cache import ContentCache, RedisStorage
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("Redis not installed. Install with: pip install content-file-cache[redis]")


async def process_pdf(file_path: Path) -> str:
    """
    Simulated expensive PDF processing.

    In real usage, this would call Claude API or similar.
    """
    print(f"Processing {file_path.name}... (expensive operation)")
    await asyncio.sleep(0.1)  # Simulate processing time
    return f"Extracted content from {file_path.name}"


async def example_single_process():
    """
    Example: Single process with Redis (for persistence across restarts)
    """
    if not REDIS_AVAILABLE:
        return

    # Create Redis client
    redis_client = Redis(host='localhost', port=6379, decode_responses=True)

    # Create cache with Redis storage
    async with ContentCache(storage=RedisStorage(redis_client)) as cache:
        test_file = Path("invoice.pdf")

        # First access: processes file
        result1 = await cache.get_content(test_file, process_pdf)
        print(f"First access: from_cache={result1.from_cache}")

        # Second access: cache hit
        result2 = await cache.get_content(test_file, process_pdf)
        print(f"Second access: from_cache={result2.from_cache}")

        # Get statistics
        stats = await cache.get_statistics()
        print(f"Cache stats: {stats}")


async def example_multi_process_worker(worker_id: int):
    """
    Example: Multi-process worker sharing Redis cache
    """
    if not REDIS_AVAILABLE:
        return

    redis_client = Redis(host='localhost', port=6379, decode_responses=True)

    async with ContentCache(storage=RedisStorage(redis_client)) as cache:
        files = [Path(f"document_{i}.pdf") for i in range(5)]

        for file in files:
            result = await cache.get_content(file, process_pdf)
            print(f"Worker {worker_id}: {file.name} - from_cache={result.from_cache}")


async def example_namespace_isolation():
    """
    Example: Multiple applications sharing Redis with namespace isolation
    """
    if not REDIS_AVAILABLE:
        return

    redis_client = Redis(host='localhost', port=6379, decode_responses=True)

    # App 1 cache
    app1_cache = ContentCache(
        storage=RedisStorage(redis_client, key_prefix="app1_cache")
    )

    # App 2 cache
    app2_cache = ContentCache(
        storage=RedisStorage(redis_client, key_prefix="app2_cache")
    )

    await app1_cache.initialize()
    await app2_cache.initialize()

    test_file = Path("shared_document.pdf")

    # Cache in app1
    result1 = await app1_cache.get_content(test_file, process_pdf)
    print(f"App1: from_cache={result1.from_cache}")

    # App2 doesn't see app1's cache (different namespace)
    result2 = await app2_cache.get_content(test_file, process_pdf)
    print(f"App2: from_cache={result2.from_cache}")  # Will be False

    await app1_cache.close()
    await app2_cache.close()


async def example_hybrid_local_and_redis():
    """
    Example: Configuration-based choice between local and Redis
    """
    import os

    if not REDIS_AVAILABLE:
        # Fallback to local SQLite storage
        from content_cache import ContentCache
        cache = ContentCache()  # Uses default SQLiteStorage
        print("Using local SQLiteStorage (Redis not available)")
    else:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = Redis.from_url(redis_url, decode_responses=True)
        cache = ContentCache(storage=RedisStorage(redis_client))
        print(f"Using Redis at {redis_url}")

    await cache.initialize()

    test_file = Path("document.pdf")
    result = await cache.get_content(test_file, process_pdf)
    print(f"Processed {test_file.name}")

    await cache.close()


if __name__ == "__main__":
    print("=== Redis Storage Examples ===\n")

    if REDIS_AVAILABLE:
        print("1. Single process with persistence")
        asyncio.run(example_single_process())

        print("\n2. Namespace isolation")
        asyncio.run(example_namespace_isolation())

        print("\n3. Configuration-based storage selection")
        asyncio.run(example_hybrid_local_and_redis())

        print("\n4. Multi-process workers (run multiple instances simultaneously)")
        print("   Run: python redis_example.py & python redis_example.py &")
        asyncio.run(example_multi_process_worker(worker_id=1))
    else:
        print("Install Redis support: pip install 'content-file-cache[redis]'")
        print("Or: pip install redis")
