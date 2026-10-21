"""Shared by the integration tests."""

import threading

WORKERS = 16


def race(work, workers: int = WORKERS) -> list:
    """Run `work(index)` in many threads released at the same instant; return all results."""
    barrier = threading.Barrier(workers)
    results: list = [None] * workers

    def run(index: int) -> None:
        barrier.wait()
        results[index] = work(index)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results
