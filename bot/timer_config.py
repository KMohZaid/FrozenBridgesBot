"""
Timer configuration class for Frozen Bridges game.

This module contains only the GameTimers configuration class to avoid
circular import dependencies with the timers module.
"""

import logging
import os

from . import database

LOGGER = logging.getLogger(__name__)


class GameTimers:
    """Configurable timer settings for a game."""

    def __init__(self, chat_id: int = None):
        """Initialize timers from database or environment variables.

        Args:
            chat_id: Group chat ID to load settings from database. If None, uses env defaults.
        """
        # Try to load from database first
        if chat_id:
            settings = database.get_group_settings(chat_id)
            if settings:
                self.asking_timeout = settings['asking_timeout']
                self.answering_timeout = settings['answering_timeout']
                self.dice_roll_timeout = settings['dice_roll_timeout']
                self.accept_reject_timeout = settings['accept_reject_timeout']
            else:
                # Fallback to environment variables
                self.asking_timeout = int(os.getenv("ASKING_TIMEOUT", "180"))
                self.answering_timeout = int(os.getenv("ANSWERING_TIMEOUT", "300"))
                self.dice_roll_timeout = int(os.getenv("DICE_ROLL_TIMEOUT", "60"))
                self.accept_reject_timeout = int(os.getenv("ACCEPT_REJECT_TIMEOUT", "120"))
        else:
            # No chat_id provided, use env defaults
            self.asking_timeout = int(os.getenv("ASKING_TIMEOUT", "180"))
            self.answering_timeout = int(os.getenv("ANSWERING_TIMEOUT", "300"))
            self.dice_roll_timeout = int(os.getenv("DICE_ROLL_TIMEOUT", "60"))
            self.accept_reject_timeout = int(os.getenv("ACCEPT_REJECT_TIMEOUT", "120"))

        # Maximum allowed values (for admin configuration) - loaded from environment variables
        self.max_asking = int(os.getenv("MAX_ASKING_TIMEOUT", "1800"))  # 30 minutes max
        self.max_answering = int(os.getenv("MAX_ANSWERING_TIMEOUT", "600"))  # 10 minutes max
        self.max_accept_reject = int(os.getenv("MAX_ACCEPT_REJECT_TIMEOUT", "300"))  # 5 minutes max

    def set_asking_timeout(self, seconds: int) -> bool:
        """Set asking timeout. Returns True if valid."""
        if 60 <= seconds <= self.max_asking:
            self.asking_timeout = seconds
            return True
        return False

    def set_answering_timeout(self, seconds: int) -> bool:
        """Set answering timeout. Returns True if valid."""
        if 60 <= seconds <= self.max_answering:
            self.answering_timeout = seconds
            return True
        return False

    def set_accept_reject_timeout(self, seconds: int) -> bool:
        """Set accept/reject timeout. Returns True if valid."""
        if 60 <= seconds <= self.max_accept_reject:
            self.accept_reject_timeout = seconds
            return True
        return False

    def reset_to_defaults(self):
        """Reset all timers to default values from environment variables."""
        self.asking_timeout = int(os.getenv("ASKING_TIMEOUT", "180"))
        self.answering_timeout = int(os.getenv("ANSWERING_TIMEOUT", "300"))
        self.dice_roll_timeout = int(os.getenv("DICE_ROLL_TIMEOUT", "60"))
        self.accept_reject_timeout = int(os.getenv("ACCEPT_REJECT_TIMEOUT", "120"))
