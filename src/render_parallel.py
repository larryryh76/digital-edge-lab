"""Bounded, ordered scene scheduling with a hard wall-clock deadline."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import threading
import time

class RenderDeadlineExceeded(TimeoutError):
    pass

def run_parallel(items, worker, *, max_workers=2, deadline_seconds=2700):
    """Run independent items concurrently, return results in input order.

    worker(item, cancel_event, deadline_monotonic) must terminate its child
    processes when cancellation is signalled or the shared deadline expires.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    deadline = time.monotonic() + max(1, float(deadline_seconds))
    cancel = threading.Event()
    results = {}
    errors = []
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scene-render")
    futures = {pool.submit(worker, i, item, cancel, deadline): i
               for i, item in enumerate(items)}
    try:
        try:
            completed = as_completed(futures, timeout=max(0.01, deadline-time.monotonic()))
            for future in completed:
                index = futures[future]
                try:
                    results[index] = future.result()
                except BaseException as exc:
                    errors.append((index, exc))
                    cancel.set()
                    for pending in futures:
                        pending.cancel()
                    break
        except FuturesTimeoutError as exc:
            cancel.set()
            raise RenderDeadlineExceeded(
                f"render-phase deadline expired after {deadline_seconds:.1f}s; "
                f"completed {len(results)}/{len(items)} scenes") from exc
        if time.monotonic() >= deadline and len(results) != len(items):
            cancel.set()
            raise RenderDeadlineExceeded(
                f"render-phase deadline expired after {deadline_seconds:.1f}s; "
                f"completed {len(results)}/{len(items)} scenes")
        if errors:
            index, exc = sorted(errors, key=lambda x: x[0])[0]
            raise RuntimeError(f"scene item {index + 1} failed: {exc}") from exc
        if len(results) != len(items):
            cancel.set()
            raise RenderDeadlineExceeded(
                f"render phase ended with {len(results)}/{len(items)} scenes complete")
        return [results[i] for i in range(len(items))]
    except BaseException:
        cancel.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
