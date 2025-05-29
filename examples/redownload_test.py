#!/usr/bin/env python3
"""
Test: Re-download Same Content Recognition

This test demonstrates that the cache can now recognize when a file has been
re-downloaded with the same content and will serve from cache instead of
reprocessing.
"""

import asyncio
import time
import shutil
from pathlib import Path
from content_cache import ContentCache, CacheConfig


async def expensive_processor(file_path: Path) -> str:
    """Simulate expensive processing."""
    print(f"💰 EXPENSIVE: Processing {file_path.name} (this should only happen once!)")
    await asyncio.sleep(1)  # Simulate 1 second processing time
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    return f"PROCESSED: {content} (word count: {len(content.split())})"


async def test_redownload_recognition():
    """Test that re-downloaded identical files are recognized from cache."""
    
    # Setup
    test_dir = Path("./redownload_test")
    test_dir.mkdir(exist_ok=True)
    
    original_file = test_dir / "document.txt"
    download_location = test_dir / "download.txt"  # Simulate download location
    
    # Create test content
    test_content = "This is a test document with some content for processing."
    original_file.write_text(test_content)
    
    # Configure cache
    config = CacheConfig(
        cache_dir=test_dir / "cache",
        verify_hash=True,  # Enable hash verification for content comparison
        max_memory_size=10 * 1024 * 1024  # 10MB
    )
    cache = ContentCache(config=config)
    
    print("🧪 Testing Re-download Recognition\n")
    
    # Step 1: Process original file
    print("📝 Step 1: Process original file")
    start = time.time()
    result1 = await cache.get_content(original_file, expensive_processor)
    time1 = time.time() - start
    
    print(f"   ✅ Processed in {time1:.3f}s")
    print(f"   📄 From cache: {result1.from_cache}")
    print(f"   🔗 Hash: {result1.content_hash[:16]}...")
    print(f"   📝 Content preview: {result1.content[:50]}...\n")
    
    # Step 2: Access same file again (should be from cache)
    print("📝 Step 2: Access same file again")
    start = time.time()
    result2 = await cache.get_content(original_file, expensive_processor)
    time2 = time.time() - start
    
    print(f"   ✅ Retrieved in {time2:.3f}s")
    print(f"   📄 From cache: {result2.from_cache}")
    print(f"   🚀 Speedup: {time1/time2:.0f}x\n")
    
    # Step 3: Simulate re-downloading the SAME content to SAME location
    print("📝 Step 3: Simulate re-downloading same content")
    print("   🔄 Copying file to simulate download (same content, new mtime)...")
    
    # Copy to simulate download (this updates modification time)
    shutil.copy2(original_file, download_location)
    time.sleep(0.1)  # Ensure different mtime
    download_location.replace(original_file)  # Replace original with "downloaded" version
    
    print(f"   ✅ File 'downloaded' with new modification time")
    
    # Step 4: Process the "re-downloaded" file
    print("📝 Step 4: Process re-downloaded file (same content)")
    start = time.time()
    result3 = await cache.get_content(original_file, expensive_processor)
    time3 = time.time() - start
    
    print(f"   ✅ Retrieved in {time3:.3f}s")
    print(f"   📄 From cache: {result3.from_cache}")
    print(f"   🔗 Hash match: {result3.content_hash == result1.content_hash}")
    
    if result3.from_cache:
        print(f"   🎉 SUCCESS: Cache recognized identical content!")
        print(f"   🚀 Speedup vs processing: {time1/time3:.0f}x")
    else:
        print(f"   ❌ ISSUE: File was reprocessed despite identical content")
    
    # Step 5: Test with actually different content
    print("\n📝 Step 5: Test with actually different content")
    different_content = "This is DIFFERENT content that should trigger reprocessing."
    original_file.write_text(different_content)
    
    start = time.time()
    result4 = await cache.get_content(original_file, expensive_processor)
    time4 = time.time() - start
    
    print(f"   ✅ Processed in {time4:.3f}s")
    print(f"   📄 From cache: {result4.from_cache}")
    print(f"   🔗 Hash changed: {result4.content_hash != result1.content_hash}")
    print(f"   📝 Content preview: {result4.content[:50]}...")
    
    if not result4.from_cache:
        print(f"   ✅ CORRECT: Cache detected content change and reprocessed")
    else:
        print(f"   ❌ ISSUE: Cache didn't detect content change")
    
    # Cache statistics
    print("\n📊 Final Cache Statistics:")
    stats = await cache.get_statistics()
    print(f"   Total requests: {stats['total_requests']}")
    print(f"   Cache hits: {stats['cache_hits']}")
    print(f"   Hit rate: {stats['hit_rate']:.1%}")
    
    # Cleanup
    await cache.close()
    shutil.rmtree(test_dir)
    
    print("\n🎯 Test completed!")


if __name__ == "__main__":
    asyncio.run(test_redownload_recognition())