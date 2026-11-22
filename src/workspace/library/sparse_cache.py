"""Bounded process-local BM25 cache; authorization remains a database check."""
from collections import OrderedDict
import os
import sys
from threading import RLock
from src.retrieval.bm25 import BM25Retriever


def _size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(_size(key, seen) + _size(item, seen) for key, item in value.items())
    elif isinstance(value, (list, tuple, set)):
        size += sum(_size(item, seen) for item in value)
    elif hasattr(value, '__dict__'):
        size += _size(vars(value), seen)
    return size


class SparseCache:
    def __init__(self, budget):
        self.budget = max(0, budget)
        self.bytes = 0
        self.entries = OrderedDict()
        self.lock = RLock()

    def get_or_build(self, owner, revisions, corpus):
        key = (str(owner), tuple(sorted(str(item) for item in revisions)), 'word-v1')
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key][0]
            index = BM25Retriever()
            index.fit(corpus)
            size = _size((key, index))
            if size <= self.budget:
                while self.entries and self.bytes + size > self.budget:
                    _, (_, old_size) = self.entries.popitem(last=False)
                    self.bytes -= old_size
                self.entries[key] = (index, size)
                self.bytes += size
            return index

    def invalidate_owner(self, owner):
        with self.lock:
            for key in list(self.entries):
                if key[0] == str(owner):
                    _, size = self.entries.pop(key)
                    self.bytes -= size


def _budget():
    try:
        return max(0, int(os.getenv('WORKSPACE_BM25_CACHE_MB', '32'))) * 1024 * 1024
    except ValueError:
        return 32 * 1024 * 1024


SPARSE_CACHE = SparseCache(_budget())
