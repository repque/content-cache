#!/usr/bin/env python3
"""
PDF Transaction Extraction with Caching Example

This example demonstrates how to use the Content Cache with Anthropic's API
to extract financial transactions from PDF documents efficiently.

Requirements:
    pip install content-file-cache anthropic aiohttp aiofiles

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python pdf_transaction_extraction.py

The cache ensures that expensive API calls are made only once per unique PDF,
saving both time and money on subsequent processing.
"""

import asyncio
import json
import base64
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import anthropic

from content_cache import ContentCache, CacheConfig


class PDFTransactionExtractor:
    """Extract transactions from PDF files using Anthropic Claude API with caching."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the extractor with API key and cache configuration."""
        # Get API key from parameter or environment
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY environment variable.")
        
        # Initialize Anthropic client
        self.client = anthropic.Anthropic(api_key=self.api_key)
        
        # Configure cache for optimal API response storage
        self.cache_config = CacheConfig(
            cache_dir=Path("./transaction_cache"),
            max_memory_size=500 * 1024 * 1024,  # 500MB for JSON responses
            verify_hash=True,  # Ensure data integrity for financial data
            compression_level=6,  # JSON compresses very well
            debug=True  # Enable debug logging
        )
        
        # Initialize cache
        self.cache = ContentCache(config=self.cache_config)
        
        # Track statistics
        self.stats = {
            'api_calls': 0,
            'cache_hits': 0,
            'total_cost': 0.0,
            'total_time': 0.0
        }
    
    def extract_transactions_from_pdf(self, pdf_path: Path) -> str:
        """
        Extract transactions from a PDF using Claude API.
        
        This is the expensive operation that benefits from caching.
        Cost: ~$0.015 per page with Claude-3-Opus
        Time: 10-30 seconds per document
        """
        print(f"\n🤖 Calling Anthropic API for {pdf_path.name}...")
        start_time = datetime.now()
        
        # Track API call
        self.stats['api_calls'] += 1
        
        try:
            # Read and encode PDF
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
                pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
            
            # Estimate cost (rough: 1MB ≈ 4 pages)
            file_size_mb = len(pdf_data) / (1024 * 1024)
            estimated_pages = max(1, int(file_size_mb * 4))
            estimated_cost = estimated_pages * 0.015
            self.stats['total_cost'] += estimated_cost
            
            # Call Claude API
            message = self.client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4096,
                temperature=0,  # Deterministic for consistent caching
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """Analyze this financial document and extract ALL transactions.
                                
                                For each transaction, extract:
                                - date (ISO format: YYYY-MM-DD)
                                - description (merchant/payee name)
                                - amount (negative for debits, positive for credits)
                                - type ("debit" or "credit")
                                - category (best guess: groceries, utilities, salary, etc.)
                                
                                Return ONLY a JSON array of transaction objects, no other text.
                                
                                Example:
                                [
                                  {
                                    "date": "2024-01-15",
                                    "description": "WHOLE FOODS MARKET",
                                    "amount": -127.43,
                                    "type": "debit",
                                    "category": "groceries"
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
            
            # Extract response
            response_text = message.content[0].text
            
            # Parse and validate JSON
            transactions = json.loads(response_text)
            if not isinstance(transactions, list):
                raise ValueError("Expected JSON array of transactions")
            
            # Calculate processing time
            elapsed = (datetime.now() - start_time).total_seconds()
            self.stats['total_time'] += elapsed
            
            print(f"✅ Extracted {len(transactions)} transactions")
            print(f"   Cost: ~${estimated_cost:.3f}")
            print(f"   Time: {elapsed:.1f}s")
            
            # Return formatted JSON
            return json.dumps(transactions, indent=2)
            
        except Exception as e:
            print(f"❌ API Error: {str(e)}")
            error_response = {
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "file": pdf_path.name
            }
            return json.dumps(error_response)
    
    async def process_pdf_batch(self, pdf_paths: List[Path]) -> Dict[str, any]:
        """Process multiple PDFs with caching enabled."""
        print(f"\n📊 Processing {len(pdf_paths)} PDF files...")
        print(f"💾 Cache directory: {self.cache_config.cache_dir}\n")
        
        results = {}
        
        for pdf_path in pdf_paths:
            if not pdf_path.exists():
                print(f"⚠️  Skipping {pdf_path.name} - file not found")
                continue
            
            # Get content from cache or process
            start_time = datetime.now()
            
            cache_result = await self.cache.get_content(
                pdf_path,
                self.extract_transactions_from_pdf
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # Track cache hit
            if cache_result.from_cache:
                self.stats['cache_hits'] += 1
            
            # Parse results
            try:
                data = json.loads(cache_result.content)
                
                # Handle both success and error responses
                if isinstance(data, list):
                    results[pdf_path.name] = {
                        'success': True,
                        'transactions': data,
                        'count': len(data),
                        'from_cache': cache_result.from_cache,
                        'processing_time': elapsed,
                        'file_hash': cache_result.content_hash[:16]
                    }
                else:
                    results[pdf_path.name] = {
                        'success': False,
                        'error': data.get('error', 'Unknown error'),
                        'from_cache': cache_result.from_cache
                    }
                
                # Print status
                status = "🔄 CACHED" if cache_result.from_cache else "🆕 PROCESSED"
                print(f"{status} {pdf_path.name}: {elapsed:.3f}s")
                
            except json.JSONDecodeError:
                results[pdf_path.name] = {
                    'success': False,
                    'error': 'Invalid JSON response',
                    'from_cache': cache_result.from_cache
                }
        
        return results
    
    def analyze_results(self, results: Dict[str, any]) -> None:
        """Analyze and display extracted transactions."""
        print("\n📈 Transaction Analysis:")
        
        all_transactions = []
        for filename, data in results.items():
            if data.get('success') and 'transactions' in data:
                all_transactions.extend(data['transactions'])
        
        if not all_transactions:
            print("   No transactions found!")
            return
        
        # Calculate totals
        total_debits = sum(t['amount'] for t in all_transactions if t['amount'] < 0)
        total_credits = sum(t['amount'] for t in all_transactions if t['amount'] > 0)
        
        # Group by category
        by_category = {}
        for trans in all_transactions:
            category = trans.get('category', 'uncategorized')
            amount = abs(trans['amount'])
            by_category[category] = by_category.get(category, 0) + amount
        
        # Display results
        print(f"   Total transactions: {len(all_transactions)}")
        print(f"   Total debits: ${abs(total_debits):,.2f}")
        print(f"   Total credits: ${total_credits:,.2f}")
        print(f"   Net flow: ${(total_credits + total_debits):,.2f}")
        
        print("\n   Top spending categories:")
        for category, amount in sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"   - {category}: ${amount:,.2f}")
    
    def print_statistics(self) -> None:
        """Print cache and API usage statistics."""
        cache_hit_rate = (self.stats['cache_hits'] / max(1, self.stats['api_calls'] + self.stats['cache_hits'])) * 100
        avg_api_time = self.stats['total_time'] / max(1, self.stats['api_calls'])
        
        print("\n📊 Performance Statistics:")
        print(f"   API calls made: {self.stats['api_calls']}")
        print(f"   Cache hits: {self.stats['cache_hits']}")
        print(f"   Cache hit rate: {cache_hit_rate:.1f}%")
        print(f"   Total API cost: ${self.stats['total_cost']:.2f}")
        print(f"   Average API time: {avg_api_time:.1f}s")
        
        if self.stats['cache_hits'] > 0:
            cost_saved = self.stats['cache_hits'] * (self.stats['total_cost'] / max(1, self.stats['api_calls']))
            print(f"   💰 Cost saved by cache: ${cost_saved:.2f}")
    
    async def close(self):
        """Clean up resources."""
        await self.cache.close()


async def main():
    """Example usage with sample PDF files."""
    
    # Create example PDF directory
    pdf_dir = Path("./sample_pdfs")
    pdf_dir.mkdir(exist_ok=True)
    
    # List of PDFs to process (replace with your actual files)
    pdf_files = [
        pdf_dir / "bank_statement_jan_2024.pdf",
        pdf_dir / "bank_statement_feb_2024.pdf",
        pdf_dir / "credit_card_statement_q1_2024.pdf",
    ]
    
    # Filter to existing files
    existing_pdfs = [pdf for pdf in pdf_files if pdf.exists()]
    
    if not existing_pdfs:
        print("⚠️  No PDF files found!")
        print(f"Please add PDF files to: {pdf_dir}")
        print("\nExample files:")
        for pdf in pdf_files:
            print(f"  - {pdf}")
        return
    
    # Initialize extractor
    try:
        extractor = PDFTransactionExtractor()
    except ValueError as e:
        print(f"❌ {e}")
        return
    
    # First run - API calls
    print("="*60)
    print("FIRST RUN - Processing PDFs (API calls)")
    print("="*60)
    
    results1 = await extractor.process_pdf_batch(existing_pdfs)
    extractor.analyze_results(results1)
    extractor.print_statistics()
    
    # Second run - cached
    print("\n" + "="*60)
    print("SECOND RUN - Processing same PDFs (from cache)")
    print("="*60)
    
    # Reset timing for second run
    cache_start = datetime.now()
    results2 = await extractor.process_pdf_batch(existing_pdfs)
    cache_time = (datetime.now() - cache_start).total_seconds()
    
    print(f"\n⚡ Total time for {len(existing_pdfs)} cached PDFs: {cache_time:.3f}s")
    extractor.print_statistics()
    
    # Show cache effectiveness
    cache_stats = await extractor.cache.get_statistics()
    print(f"\n💾 Cache Storage:")
    print(f"   Memory usage: {cache_stats['memory_usage_mb']:.1f} MB")
    print(f"   Unique documents: {cache_stats['unique_hashes']}")
    
    # Cleanup
    await extractor.close()


if __name__ == "__main__":
    print("PDF Transaction Extraction with Caching")
    print("======================================")
    print("\nThis example shows how to use the cache with expensive API calls.")
    print("The same PDF processed multiple times will only call the API once.\n")
    
    asyncio.run(main())