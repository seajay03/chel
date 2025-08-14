from __future__ import annotations

"""Data models for games and practice lobbies."""

from dataclasses import dataclass, field
from typing import Dict, Optional, List

POSITIONS: List[str] = ["C", "LW", "RW", "LD", "RD", "G", "UTIL", "UTIL2"]

@dataclass
class Game:
    """Representation of a scheduled league game."""

    id: str
    dt_iso: str
    opponent: str
    status: str = "upcoming"
    roster: Dict[str, Optional[str]] = field(
        default_factory=lambda: {pos: None for pos in POSITIONS}
    )
    confirmed: Dict[str, bool] = field(
        default_factory=lambda: {pos: False for pos in POSITIONS}
    )
    posted_requests: Dict[str, Optional[int]] = field(
        default_factory=lambda: {pos: None for pos in POSITIONS}
    )
    flags: Dict[str, object] = field(
        default_factory=lambda: {
            "locked": False,
            "canceled": False,
            "dm_6pm": False,
            "claims_6am": False,
            "aggressive_2h": False,
            "util_promoted_1h": False,
            "t30_done": False,
            "final_call": False,
            "last_panic_ts": 0.0,
        }
    )
    lineup_message_id: Optional[int] = None
    thread_id: Optional[int] = None


@dataclass
class PracticeLobby:
    """Representation of an ad-hoc practice lobby."""

    id: str
    creator_id: int
    channel_id: int
    message_id: Optional[int]
    thread_id: Optional[int]
    opponent: str
    start_in_min: int
    roster: Dict[str, Optional[str]] = field(
        default_factory=lambda: {pos: None for pos in POSITIONS[:6]}
    )
    flags: Dict[str, bool] = field(
        default_factory=lambda: {
            "announced": False,
            "canceled": False,
            "started": False,
        }
    )


def game_from_dict(data: Dict[str, object]) -> Game:
    """Create a :class:`Game` from a dictionary."""

    return Game(**data)


def practice_from_dict(data: Dict[str, object]) -> PracticeLobby:
    """Create a :class:`PracticeLobby` from a dictionary."""

    return PracticeLobby(**data)
