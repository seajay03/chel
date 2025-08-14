from __future__ import annotations

"""Configuration constants for Coach Rosterbator."""

from typing import Set

# Guild and channel IDs
GUILD_ID: int = 1199032891074683023
LINEUP_CHANNEL_ID: int = 1404021808822226974
GENERAL_CHANNEL_ID: int = 1228418184403615796
COACH_LOG_CHANNEL_ID: int = 1199032896862822598

# Manager role IDs
MANAGER_ROLE_IDS: Set[int] = {
    1199032891099840670,  # Owner
    1199032891099840669,  # GM
    1199032891099840666,  # Management
    1404726528444731413,  # Captain
    1228392356550807653,  # Alternate Captain
}

# Timezone for all scheduling
TIMEZONE: str = "America/Toronto"
