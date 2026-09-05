"""Deterministic identifier generation.

IDs are sequence-based per run so that two identical runs over identical input
produce identical IDs. Reproducibility is a product requirement, not a nicety.
"""

from __future__ import annotations

import itertools
from typing import Iterator


class SequenceIdFactory:
    """Produces PREFIX-00001 style ids from an in-process counter."""

    def __init__(self, prefix: str, width: int = 5, start: int = 1) -> None:
        self.prefix = prefix
        self.width = width
        self._counter: Iterator[int] = itertools.count(start)

    def next(self) -> str:
        return f"{self.prefix}-{next(self._counter):0{self.width}d}"


def run_id(sequence: int) -> str:
    return f"RUN-{sequence:05d}"
