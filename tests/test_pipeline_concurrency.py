from __future__ import annotations

import asyncio

import pytest

from shortlister.scoring.pipeline import _gather_bounded


@pytest.mark.asyncio
async def test_gather_bounded_caps_in_flight_and_processes_all() -> None:
    rows = list(range(50))
    in_flight = 0
    max_in_flight = 0
    processed: list[int] = []

    async def worker(row: int) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.005)  # force overlap
        in_flight -= 1
        processed.append(row)

    await _gather_bounded(rows, worker, concurrency=4, stage_label="Test")

    assert sorted(processed) == rows          # nothing dropped
    assert max_in_flight <= 4                  # cap respected
    assert max_in_flight > 1                   # genuinely concurrent


@pytest.mark.asyncio
async def test_gather_bounded_concurrency_one_is_serial() -> None:
    in_flight = 0
    max_in_flight = 0

    async def worker(_row: int) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.001)
        in_flight -= 1

    await _gather_bounded(list(range(10)), worker, concurrency=1, stage_label="Test")

    assert max_in_flight == 1  # concurrency=1 behaves exactly like the old sequential loop


@pytest.mark.asyncio
async def test_gather_bounded_empty_is_noop() -> None:
    async def worker(_row: int) -> None:  # pragma: no cover - must never run
        raise AssertionError("worker should not be called for empty input")

    await _gather_bounded([], worker, concurrency=4, stage_label="Test")
