"""Small cachetools wrapper for short-lived read helpers."""

from collections.abc import Callable
from threading import RLock
from typing import ParamSpec, TypeVar, cast

from cachetools import TTLCache, cached
from cachetools.keys import hashkey

P = ParamSpec("P")
R = TypeVar("R")


def ttl_cache(*, seconds: int = 90, maxsize: int = 128, skip_first_args: int = 0) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Cache hashable function calls in this process for a short TTL."""

    def key(*args, **kwargs):
        return hashkey(*args[skip_first_args:], **kwargs)

    decorator = cached(TTLCache(maxsize=maxsize, ttl=seconds), key=key, lock=RLock())
    return cast(Callable[[Callable[P, R]], Callable[P, R]], decorator)
