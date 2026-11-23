"""CACHE - simple in-memory cache (stands in for Redis / ElastiCache).

To switch to Redis later, keep the same get/set/delete methods and
replace the dictionary with a redis.Redis(...) client.
"""
import threading
import time


class SimpleCache:
    def __init__(self, ttl_seconds=60):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item and item[1] > time.time():
                return item[0]
            self._store.pop(key, None)
            return None

    def set(self, key, value):
        with self._lock:
            self._store[key] = (value, time.time() + self.ttl)

    def delete(self, key):  # cache invalidation
        with self._lock:
            self._store.pop(key, None)


cache = SimpleCache()
