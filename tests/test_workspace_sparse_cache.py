from src.workspace.library.sparse_cache import SparseCache


def test_cache_separates_owners_and_revisions_and_supports_invalidation():
    corpus = [{'id': 'one', 'text': 'research evidence', 'metadata': {}}]
    cache = SparseCache(100000)
    one = cache.get_or_build('owner', ['revision'], corpus)
    assert cache.get_or_build('owner', ['revision'], corpus) is one
    assert cache.get_or_build('other', ['revision'], corpus) is not one
    assert cache.get_or_build('owner', ['new-revision'], corpus) is not one
    cache.invalidate_owner('owner')
    assert all(key[0] == 'other' for key in cache.entries)


def test_cache_evicts_to_budget_and_zero_disables_retention():
    corpus = [{'id': 'one', 'text': 'research evidence', 'metadata': {}}]
    measured = SparseCache(100000)
    measured.get_or_build('a', ['r'], corpus)
    cache = SparseCache(measured.bytes)
    cache.get_or_build('a', ['r'], corpus)
    cache.get_or_build('b', ['r'], corpus)
    assert cache.bytes <= cache.budget and len(cache.entries) == 1
    disabled = SparseCache(0)
    disabled.get_or_build('a', ['r'], corpus)
    assert not disabled.entries and disabled.bytes == 0
