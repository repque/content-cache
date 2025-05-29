#!/usr/bin/env python3
"""
Simple Content Cache Usage Example

This example demonstrates basic usage of the Content Cache component
for processing text files with a simulated expensive operation.
"""

import asyncio
import time
from pathlib import Path
from content_cache import ContentCache, CacheConfig


def process_text_file(file_path: Path) -> str:
    """
    Simulate an expensive text processing operation.
    In real use, this might be:
    - API calls (OpenAI, Anthropic, etc.)
    - Complex NLP processing
    - OCR operations
    - Data extraction/parsing
    """
    print(f"💤 Simulating expensive processing for {file_path.name}...")
    time.sleep(2)  # Simulate 2 second processing time
    
    # Read and "process" the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Simulate some processing result
    word_count = len(content.split())
    line_count = len(content.splitlines())
    
    result = f"Processed {file_path.name}:\n"
    result += f"- Words: {word_count}\n"
    result += f"- Lines: {line_count}\n"
    result += f"- Size: {len(content)} bytes\n"
    result += f"- Preview: {content[:100]}..."
    
    return result


async def main():
    """Demonstrate cache usage with simple text files."""
    
    # Create test files
    test_dir = Path("./test_files")
    test_dir.mkdir(exist_ok=True)
    
    # Create some test files if they don't exist
    test_files = []
    for i in range(3):
        file_path = test_dir / f"document_{i+1}.txt"
        if not file_path.exists():
            file_path.write_text(f"This is test document {i+1}.\n" * 50)
        test_files.append(file_path)
    
    # Configure cache
    config = CacheConfig(
        cache_dir=Path("./simple_cache"),
        max_memory_size=10 * 1024 * 1024,  # 10MB
        verify_hash=True
    )
    
    # Initialize cache
    cache = ContentCache(config=config)
    
    print("Content Cache Simple Example")
    print("="*40)
    
    # First pass - process all files
    print("\n📝 First pass - Processing files:")
    first_pass_start = time.time()
    
    for file_path in test_files:
        start = time.time()
        result = await cache.get_content(file_path, process_text_file)
        elapsed = time.time() - start
        
        print(f"\n✅ {file_path.name}:")
        print(f"   From cache: {result.from_cache}")
        print(f"   Time: {elapsed:.3f}s")
        print(f"   Hash: {result.content_hash[:16]}...")
    
    first_pass_time = time.time() - first_pass_start
    print(f"\n⏱️  Total time: {first_pass_time:.3f}s")
    
    # Second pass - all from cache
    print("\n📝 Second pass - Same files (should be cached):")
    second_pass_start = time.time()
    
    for file_path in test_files:
        start = time.time()
        result = await cache.get_content(file_path, process_text_file)
        elapsed = time.time() - start
        
        print(f"\n✅ {file_path.name}:")
        print(f"   From cache: {result.from_cache}")
        print(f"   Time: {elapsed:.3f}s")
    
    second_pass_time = time.time() - second_pass_start
    print(f"\n⏱️  Total time: {second_pass_time:.3f}s")
    print(f"🚀 Speedup: {first_pass_time/second_pass_time:.1f}x")
    
    # Show cache statistics
    stats = await cache.get_statistics()
    print(f"\n📊 Cache Statistics:")
    print(f"   Hit rate: {stats['hit_rate']:.1%}")
    print(f"   Total requests: {stats['total_requests']}")
    print(f"   Cache hits: {stats['cache_hits']}")
    
    # Modify a file and see cache invalidation
    print("\n📝 Modifying a file...")
    test_files[0].write_text("This file has been modified!\n" * 50)
    
    result = await cache.get_content(test_files[0], process_text_file)
    print(f"\n✅ {test_files[0].name} after modification:")
    print(f"   From cache: {result.from_cache} (should be False)")
    print(f"   Content preview: {result.content[:100]}...")
    
    # Cleanup
    await cache.close()
    
    print("\n✅ Example completed!")


if __name__ == "__main__":
    asyncio.run(main())