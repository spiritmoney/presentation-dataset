"""Parallel file processing for fast compliant runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    items: list[T],
    fn: Callable[[T], R],
    *,
    max_workers: int = 16,
) -> list[R]:
    if not items:
        return []
    if max_workers <= 1 or len(items) == 1:
        return [fn(item) for item in items]

    results: list[R | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
    return [r for r in results if r is not None]
