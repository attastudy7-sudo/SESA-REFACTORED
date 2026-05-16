"""
Redis caching utilities for video fetching.
Uses Redis to cache YouTube API responses and reduce API calls.
"""

import json
import os
from functools import wraps
import redis
from flask import current_app

_redis_client = None


def get_redis_client():
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        redis_url = current_app.config.get('REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def cache_key(prefix: str, *args) -> str:
    """Generate a cache key from prefix and args."""
    parts = [prefix] + [str(arg).replace(':', '_').replace(' ', '_') for arg in args]
    return ':'.join(parts)


def cached(ttl: int = 3600, key_prefix: str = 'video'):
    """
    Decorator to cache function results in Redis.
    
    Args:
        ttl: Time to live in seconds (default 1 hour)
        key_prefix: Prefix for the cache key
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                redis_client = get_redis_client()
                
                # Generate cache key from function name and arguments
                cache_key_str = key_prefix + ':' + func.__name__ + ':' + ':'.join(
                    str(arg) for arg in args if isinstance(arg, (str, int, float))
                )
                
                # Try to get cached result
                cached_result = redis_client.get(cache_key_str)
                if cached_result:
                    return json.loads(cached_result)
                
                # Call the original function
                result = func(*args, **kwargs)
                
                # Cache the result
                if result is not None:
                    redis_client.setex(cache_key_str, ttl, json.dumps(result))
                
                return result
                
            except redis.RedisError as e:
                # If Redis is unavailable, just return uncached result
                current_app.logger.warning(f"Redis unavailable, skipping cache: {e}")
                return func(*args, **kwargs)
            except Exception as e:
                # On any error, fall back to non-cached call
                current_app.logger.warning(f"Cache error: {e}")
                return func(*args, **kwargs)
        return wrapper
    return decorator


def invalidate_cache(pattern: str = 'video:*') -> int:
    """
    Invalidate cache keys matching a pattern.
    Returns the number of keys deleted.
    """
    try:
        redis_client = get_redis_client()
        keys = redis_client.keys(pattern)
        if keys:
            return redis_client.delete(*keys)
        return 0
    except redis.RedisError:
        return 0


def cache_video_metadata(video_id: str, metadata: dict, ttl: int = 86400) -> None:
    """Cache video metadata (title, thumbnail, etc.) for 24 hours."""
    try:
        redis_client = get_redis_client()
        key = f"video:meta:{video_id}"
        redis_client.setex(key, ttl, json.dumps(metadata))
    except redis.RedisError:
        pass


def get_cached_video_metadata(video_id: str) -> dict | None:
    """Get cached video metadata if available."""
    try:
        redis_client = get_redis_client()
        key = f"video:meta:{video_id}"
        cached = redis_client.get(key)
        return json.loads(cached) if cached else None
    except redis.RedisError:
        return None