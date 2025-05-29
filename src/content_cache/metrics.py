"""
Metrics and monitoring for content cache
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CacheMetrics:
    """
    Comprehensive metrics for cache performance monitoring.
    
    Intent:
    Provides detailed performance and operational metrics for cache monitoring,
    alerting, and optimization. Tracks both performance indicators (hit rates,
    response times) and operational metrics (storage usage, error rates).
    
    Key design decisions:
    - Combines counters, gauges, and computed metrics for complete picture
    - Tracks error types separately for targeted troubleshooting
    - Provides both dict and Prometheus export formats for flexibility
    - Calculates derived metrics (hit rate, averages) on demand
    
    These metrics enable:
    - Performance monitoring and alerting
    - Capacity planning and optimization
    - Troubleshooting and root cause analysis
    - SLA monitoring and reporting
    """
    # Basic counters
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    bloom_filter_hits: int = 0

    # Performance metrics
    total_response_time: float = 0.0
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None

    # Storage metrics
    memory_usage_bytes: int = 0
    disk_usage_bytes: int = 0
    total_entries: int = 0

    # Error tracking
    errors: dict[str, int] = field(default_factory=dict)

    # Timestamps
    started_at: datetime = field(default_factory=datetime.now)
    last_reset_at: datetime = field(default_factory=datetime.now)

    @property
    def hit_rate(self) -> float:
        """
        Calculate cache hit rate.
        
        Intent:
        Provides the most important cache performance metric - what percentage
        of requests are served from cache vs requiring expensive processing.
        This is a key indicator of cache effectiveness and configuration quality.
        
        Returns:
            Hit rate as a decimal (0.0 to 1.0), 0.0 if no requests yet
        """
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests

    @property
    def avg_response_time(self) -> float:
        """
        Calculate average response time.
        
        Intent:
        Provides insight into overall cache performance by averaging response
        times across all requests. This includes both fast cache hits and
        slower cache misses, giving a realistic picture of user experience.
        
        Returns:
            Average response time in seconds, 0.0 if no requests yet
        """
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time / self.total_requests

    def record_request(self, response_time: float, cache_hit: bool) -> None:
        """
        Record a single request.
        
        Intent:
        Captures the essential metrics for each cache operation: timing and
        hit/miss status. Also maintains running statistics (min/max response
        times) for performance monitoring.
        
        This method is called for every cache operation to build comprehensive
        performance statistics over time.
        
        Args:
            response_time: Time taken to serve the request (seconds)
            cache_hit: Whether request was served from cache
        """
        self.total_requests += 1
        self.total_response_time += response_time

        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

        # Update min/max response times
        if self.min_response_time is None or response_time < self.min_response_time:
            self.min_response_time = response_time
        if self.max_response_time is None or response_time > self.max_response_time:
            self.max_response_time = response_time

    def record_error(self, error_type: str) -> None:
        """
        Record an error occurrence.
        
        Intent:
        Tracks error patterns to help with troubleshooting and reliability
        monitoring. Grouping by error type enables targeted investigation
        and helps identify systemic issues vs random failures.
        
        Args:
            error_type: Type of error that occurred (typically exception class name)
        """
        self.errors[error_type] = self.errors.get(error_type, 0) + 1

    def to_dict(self) -> dict:
        """
        Convert metrics to dictionary for export.
        
        Intent:
        Provides a structured data format suitable for JSON export, logging,
        or integration with monitoring systems. Converts raw metrics into
        human-readable units (milliseconds for time, megabytes for storage).
        
        Returns:
            Dictionary containing all metrics in export-friendly format
        """
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": self.hit_rate,
            "bloom_filter_hits": self.bloom_filter_hits,
            "avg_response_time_ms": self.avg_response_time * 1000,
            "min_response_time_ms": self.min_response_time * 1000 if self.min_response_time else None,
            "max_response_time_ms": self.max_response_time * 1000 if self.max_response_time else None,
            "memory_usage_mb": self.memory_usage_bytes / (1024 * 1024),
            "disk_usage_mb": self.disk_usage_bytes / (1024 * 1024),
            "total_entries": self.total_entries,
            "errors": dict(self.errors),
            "uptime_seconds": (datetime.now() - self.started_at).total_seconds(),
        }

    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Intent:
        Enables integration with Prometheus monitoring systems using the
        standard exposition format. Includes proper metric types (counter,
        gauge, summary) and help text for operational clarity.
        
        Prometheus format is the de facto standard for cloud-native monitoring,
        making this essential for production observability.
        
        Returns:
            String in Prometheus exposition format
        """
        lines = [
            "# HELP cache_requests_total Total number of cache requests",
            "# TYPE cache_requests_total counter",
            f"cache_requests_total {self.total_requests}",
            "",
            "# HELP cache_hits_total Total number of cache hits",
            "# TYPE cache_hits_total counter",
            f"cache_hits_total {self.cache_hits}",
            "",
            "# HELP cache_hit_rate Cache hit rate",
            "# TYPE cache_hit_rate gauge",
            f"cache_hit_rate {self.hit_rate}",
            "",
            "# HELP cache_response_time_seconds Response time in seconds",
            "# TYPE cache_response_time_seconds summary",
            f"cache_response_time_seconds_sum {self.total_response_time}",
            f"cache_response_time_seconds_count {self.total_requests}",
            "",
            "# HELP cache_memory_usage_bytes Memory usage in bytes",
            "# TYPE cache_memory_usage_bytes gauge",
            f"cache_memory_usage_bytes {self.memory_usage_bytes}",
            "",
            "# HELP cache_disk_usage_bytes Disk usage in bytes",
            "# TYPE cache_disk_usage_bytes gauge",
            f"cache_disk_usage_bytes {self.disk_usage_bytes}",
        ]

        # Add error metrics
        for error_type, count in self.errors.items():
            lines.extend([
                "",
                f"# HELP cache_errors_total Total errors of type {error_type}",
                "# TYPE cache_errors_total counter",
                f'cache_errors_total{{type="{error_type}"}} {count}',
            ])

        return "\n".join(lines)

    def reset(self) -> None:
        """
        Reset all metrics.
        
        Intent:
        Provides a clean slate for metrics collection, useful for testing
        or when starting fresh measurement periods. Preserves the started_at
        timestamp while updating the reset timestamp.
        
        Typically used in testing scenarios or for periodic metric reporting
        where you want to measure specific time windows.
        """
        self.total_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.bloom_filter_hits = 0
        self.total_response_time = 0.0
        self.min_response_time = None
        self.max_response_time = None
        self.errors.clear()
        self.last_reset_at = datetime.now()


class MetricsCollector:
    """
    Context manager for collecting request metrics.
    
    Intent:
    Provides automatic timing and error tracking for cache operations using
    the context manager pattern. This ensures that all requests are properly
    measured without requiring manual instrumentation throughout the codebase.
    
    Key benefits:
    - Automatic timing from entry to exit
    - Exception handling and error categorization
    - Clean separation of instrumentation from business logic
    - Guaranteed cleanup even when exceptions occur
    
    Usage pattern enables consistent metrics collection across all cache
    operations with minimal code overhead.
    """
    def __init__(self, metrics: CacheMetrics):
        self.metrics = metrics
        self.start_time: Optional[float] = None
        self.cache_hit: bool = False

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            response_time = time.time() - self.start_time
            self.metrics.record_request(response_time, self.cache_hit)

        if exc_type is not None:
            self.metrics.record_error(exc_type.__name__)

        return False  # Don't suppress exceptions

    def mark_cache_hit(self) -> None:
        """
        Mark this request as a cache hit.
        
        Intent:
        Allows the cache logic to indicate when a request was served from cache
        rather than requiring expensive processing. This is called when cached
        content is found and validated.
        
        The default assumption is cache miss (expensive operation), so this
        method is only called when we successfully serve from cache.
        """
        self.cache_hit = True
