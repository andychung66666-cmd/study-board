from dataclasses import dataclass
from typing import Protocol

from talkboard.db import Segment, Talk


@dataclass(frozen=True)
class SummaryResult:
    engine: str
    model: str
    body: dict


class Summariser(Protocol):
    def summarise(self, talk: Talk, segments: list[Segment]) -> SummaryResult: ...
