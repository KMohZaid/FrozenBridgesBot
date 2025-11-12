import logging
from enum import Enum
from typing import Dict, List, Optional
import math # Import math

from pyrogram.types import User

LOGGER = logging.getLogger(__name__)


class Player:
    """Represents a player in the Frozen Bridge game."""

    def __init__(self, user: User):
        self.user_id: int = user.id
        self.username: str = user.username
        self.first_name: str = user.first_name
        self.last_name: str = user.last_name if user.last_name else ""
        self.name: str = user.first_name
        self.mention: str = user.mention
        self.is_active: bool = True
        self.game_answer_count: int = 0

    def __repr__(self) -> str:
        return f"Player(id={self.user_id}, username='{self.username}', active={self.is_active})"


class GameState(Enum):
    WAITING = "WAITING"
    PLAYING = "PLAYING"
    VOTING = "VOTING"
    ASKING = "ASKING"
    ANSWERING = "ANSWERING"
    ROLLING = "ROLLING"
    ENDED = "ENDED"

class VoteOutcome(Enum):
    PASSED = 1
    FAILED_IMPOSSIBLE = 2
    ONGOING = 3

class Game:
    """Manages the state and logic of a single Frozen Bridge game."""

    def __init__(self, chat_id: int):
        self.chat_id: int = chat_id
        # NEW: Use dictionary for all players and queue for active players
        self.all_players: Dict[int, Player] = {}  # user_id -> Player
        self.active_player_queue: List[int] = []  # List of active user_ids in turn order
        self.game_state: GameState = GameState.WAITING

        # Store player IDs instead of Player objects
        self.current_player_id: Optional[int] = None
        self.answerer_id: Optional[int] = None

        # Game state
        self.question: Optional[str] = None
        self.answer: Optional[str] = None
        self.current_player_roll: Optional[int] = None
        self.answerer_roll: Optional[int] = None
        self.question_change_requests_used: int = 0  # Track question change requests this turn
        self.question_change_answerer_id: Optional[int] = None  # Track answerer for change requests

        # Message tracking
        self.lobby_message_id: Optional[int] = None
        self.player_list_message_id: Optional[int] = None
        self.answering_message_id: Optional[int] = None  # Track answering phase message
        self.last_timer_warning_message_id: Optional[int] = None  # Track last timer warning to delete

        # Voting attributes
        self.vote_type: Optional[str] = None  # 'skip', 'end', 'kick'
        self.votes: Dict[int, bool] = {}  # user_id -> True (yes) or False (no)
        self.vote_starter_id: Optional[int] = None
        self.vote_target_id: Optional[int] = None  # NEW: Who is being voted on
        self.vote_message_id: Optional[int] = None

        # Timer tracking (for Sprint 3)
        self.active_timer = None

        # Game duration tracking
        self.start_time: Optional[float] = None  # Timestamp when game started

    @property
    def players(self) -> List[Player]:
        """Returns all players (for backward compatibility)."""
        return list(self.all_players.values())

    @property
    def active_players(self) -> List[Player]:
        """Returns a list of active players in turn order."""
        return [self.all_players[uid] for uid in self.active_player_queue if uid in self.all_players]

    @property
    def current_player(self) -> Optional[Player]:
        """Returns the current player object."""
        if self.current_player_id and self.current_player_id in self.all_players:
            return self.all_players[self.current_player_id]
        return None

    @property
    def answerer(self) -> Optional[Player]:
        """Returns the answerer object."""
        if self.answerer_id and self.answerer_id in self.all_players:
            return self.all_players[self.answerer_id]
        return None

    @property
    def vote_starter(self) -> Optional[Player]:
        """Returns the vote starter object."""
        if self.vote_starter_id and self.vote_starter_id in self.all_players:
            return self.all_players[self.vote_starter_id]
        return None

    @property
    def vote_target(self) -> Optional[Player]:
        """Returns the vote target object."""
        if self.vote_target_id and self.vote_target_id in self.all_players:
            return self.all_players[self.vote_target_id]
        return None

    def add_player(self, player: Player):
        """Adds a player to the game or reactivates them if they previously left.

        Args:
            player: Player object to add. If player with same user_id exists,
                   they will be reactivated instead of creating a duplicate.
        """
        if player.user_id in self.all_players:
            # Player already exists - reactivate them
            existing_player = self.all_players[player.user_id]
            existing_player.is_active = True
            if player.user_id not in self.active_player_queue:
                self.active_player_queue.append(player.user_id)
            LOGGER.info(f"Reactivated player {player.user_id}")
        else:
            # New player
            self.all_players[player.user_id] = player
            self.active_player_queue.append(player.user_id)
            LOGGER.info(f"Added new player {player.user_id}")

    def remove_player(self, user_id: int):
        """Marks a player as inactive without deleting their data.

        Player remains in all_players dict to preserve stats, but is removed
        from active_player_queue so they won't get turns.

        Args:
            user_id: Telegram user ID of the player to deactivate.
        """
        if user_id in self.all_players:
            player = self.all_players[user_id]
            player.is_active = False
            if user_id in self.active_player_queue:
                self.active_player_queue.remove(user_id)
            LOGGER.info(f"Removed player {user_id} from active queue")

    def get_player(self, user_id: int) -> Optional[Player]:
        """Retrieves a player object by their user ID."""
        return self.all_players.get(user_id)

    def start_game(self):
        """Starts the game if there are enough players."""
        if len(self.active_player_queue) < 2:
            return False
        import time
        self.start_time = time.time()
        self.game_state = GameState.PLAYING
        self.next_turn()
        return True

    def clear_turn_state(self):
        """Clears all turn-specific state variables and resets to PLAYING state.

        Note: Doesn't cancel active_timer to prevent self-cancellation when called
        from within a timer timeout handler. Timer checks game state and exits naturally.
        """
        LOGGER.info("Clearing turn state")
        self.question = None
        self.answer = None
        self.answerer_id = None
        self.current_player_roll = None
        self.answerer_roll = None
        self.question_change_requests_used = 0  # Reset question change requests
        self.question_change_answerer_id = None  # Reset answerer tracking
        self.answering_message_id = None  # Reset answering message tracking
        self.last_timer_warning_message_id = None  # Reset timer warning tracking
        self.game_state = GameState.PLAYING

        # Don't cancel the timer here - timers check game state and exit naturally
        # Cancellation happens in start_timer() when starting a new timer
        # This prevents self-cancellation when called from within a timer timeout
        # Just clear the reference
        self.active_timer = None

    def next_turn(self):
        """Advances to the next player in the turn queue using circular rotation.

        The active_player_queue acts as a circular buffer. After finding the
        current player's position, it moves to the next index (wrapping around
        to index 0 if at the end). Also clears all turn-specific state.

        Special cases:
            - If current_player_id is None (first turn), starts at index 0
            - If current player left game, resets to index 0
        """
        LOGGER.info(f"next_turn called. Current player ID: {self.current_player_id}")
        LOGGER.info(f"Active player queue: {self.active_player_queue}")

        if not self.active_player_queue:
            self.current_player_id = None
            LOGGER.warning("next_turn: No active players in queue.")
            return

        if self.current_player_id is None:
            # First turn - set to first player in queue
            self.current_player_id = self.active_player_queue[0]
            LOGGER.info(f"next_turn: First turn, current player is {self.current_player_id}")
        else:
            # Find current player in queue and move to next
            try:
                current_idx = self.active_player_queue.index(self.current_player_id)
                next_idx = (current_idx + 1) % len(self.active_player_queue)
                self.current_player_id = self.active_player_queue[next_idx]
                LOGGER.info(f"next_turn: Advanced to next player {self.current_player_id} at index {next_idx}")
            except ValueError:
                # Current player not in queue (left game) - start from beginning
                self.current_player_id = self.active_player_queue[0]
                LOGGER.warning(f"next_turn: Current player not in queue, reset to first player {self.current_player_id}")

        # Clear turn-specific state
        self.clear_turn_state()

    def get_lobby_message(self) -> str:
        """Generates the message for the game lobby."""
        header = "🌉 **Frozen Bridges Lobby** 🌉\n\n"
        
        if not self.players:
            player_list = "No players have joined yet."
        else:
            player_lines = [f"{i+1}. {p.mention}" for i, p in enumerate(self.players)]
            player_list = "\n".join(player_lines)

        player_count_footer = f"\n\n👥 **Players**: {len(self.players)}. Need at least 2 to start."

        return f"{header}**Players:**\n{player_list}{player_count_footer}"

    def get_status_message(self) -> str:
        """Generates the main player list message with scoreboard and game state.

        Returns:
            Formatted message string containing:
                - Game header
                - Scoreboard with all active players and their points
                - Current turn indicator (👑 icon)
                - Current game state description
                - Vote status if applicable
        """
        header = "🌉 **Frozen Bridges Game** 🌉\n\n"
        state_info = ""

        active_players_now = self.active_players

        if not active_players_now:
            return "The game has ended as no players are left."

        player_lines = []
        for i, p in enumerate(active_players_now):
            status_icon = "👑 (Current Turn)" if self.current_player and p.user_id == self.current_player.user_id else ""
            player_lines.append(
                f"{i+1}. {p.mention} - {p.game_answer_count} points {status_icon}"
            )

        player_list = "\n".join(player_lines)
        scoreboard = f"📊 **Scoreboard**:\n{player_list}\n\n"

        if self.game_state == GameState.WAITING:
            state_info = f"👥 Game is waiting for players. Need at least 2 to start."
        elif self.game_state == GameState.ROLLING:
            state_info = f"🎲 Time to roll! {self.current_player.mention} and {self.answerer.mention}, please send a 🎲 to roll the dice."
        elif self.game_state in [GameState.PLAYING, GameState.ASKING, GameState.ANSWERING]:
            if self.current_player:
                state_info = (
                    f"▶️ It's {self.current_player.mention}'s turn to ask a question."
                )
            else:
                state_info = "⚠️ Game over! No active players left."

        return f"{header}{scoreboard}{state_info}"

    def start_vote(self, vote_type: str, starter_id: int, target_id: Optional[int] = None):
        """Initializes a new vote (votes happen in background without blocking gameplay)."""
        self.vote_type = vote_type
        self.vote_starter_id = starter_id
        self.vote_target_id = target_id
        self.votes = {starter_id: True}  # The starter always votes 'yes'

    def get_required_votes(self) -> int:
        """Calculates required votes using (P/2)+1 formula."""
        active_count = len(self.active_players)
        required = (active_count // 2) + 1
        LOGGER.info(f"Required votes: {required} (from {active_count} active players)")
        return required

    def add_vote(self, user_id: int, vote: bool) -> 'VoteOutcome':
        """Adds a user's vote and checks if the threshold is met, or if it's impossible to reach.

        NEW FORMULA: Required votes = (Active Players / 2) + 1
        - 2 players: 2 votes (100%)
        - 3 players: 2 votes (67%)
        - 4 players: 3 votes (75%)
        - 5 players: 3 votes (60%)
        """
        if user_id in self.votes:
            return VoteOutcome.ONGOING  # User has already voted, vote still ongoing

        self.votes[user_id] = vote

        active_player_count = len(self.active_players)
        yes_votes = sum(1 for v in self.votes.values() if v)
        required_yes_votes = self.get_required_votes()

        LOGGER.info(f"Vote status: Yes={yes_votes}, Required={required_yes_votes}, Active Players={active_player_count}")

        # Check if vote passed
        if yes_votes >= required_yes_votes:
            LOGGER.info("Vote passed: Yes votes met threshold.")
            return VoteOutcome.PASSED

        # Check if it's impossible to reach the required yes votes
        # Count how many players haven't voted yet
        total_votes_cast = len(self.votes)
        players_yet_to_vote = active_player_count - total_votes_cast

        # Even if all remaining players vote yes, can we reach the threshold?
        if yes_votes + players_yet_to_vote < required_yes_votes:
            LOGGER.info("Vote failed: Impossible to reach yes threshold.")
            return VoteOutcome.FAILED_IMPOSSIBLE

        LOGGER.info("Vote still in progress: Not yet passed, and still possible to pass.")
        return VoteOutcome.ONGOING

    def get_vote_summary(self) -> dict:
        """Returns a summary of the current vote for display."""
        yes_voters = [self.all_players[uid] for uid, vote in self.votes.items() if vote and uid in self.all_players]
        no_voters = [self.all_players[uid] for uid, vote in self.votes.items() if not vote and uid in self.all_players]

        return {
            'yes_count': len(yes_voters),
            'no_count': len(no_voters),
            'yes_voters': yes_voters,
            'no_voters': no_voters,
            'required': self.get_required_votes(),
            'total_active': len(self.active_players)
        }

    def reset_vote(self):
        """Resets voting attributes (doesn't change game state)."""
        self.vote_type = None
        self.votes = {}
        self.vote_starter_id = None
        self.vote_target_id = None
        self.vote_message_id = None

    def handle_player_leave(self, user_id: int):
        """Handles all state changes when a player leaves mid-game.

        Deactivates the player and handles special cases:
            - If current player leaves: clears turn state (caller should advance turn)
            - If answerer leaves: resets to PLAYING state so new answerer can be chosen

        Args:
            user_id: Telegram user ID of the leaving player.
        """
        is_current = (user_id == self.current_player_id)
        is_answerer = (user_id == self.answerer_id)

        # Remove from active queue
        self.remove_player(user_id)

        if is_current:
            # Current player left - clear state and advance turn
            LOGGER.info(f"Current player {user_id} left, clearing state and advancing")
            self.clear_turn_state()
            # next_turn will be called by the leave handler
        elif is_answerer:
            # Answerer left - reset to asking state
            LOGGER.info(f"Answerer {user_id} left, resetting to asking state")
            self.answerer_id = None
            self.answer = None
            self.game_state = GameState.PLAYING

    # State validation functions
    def validate_can_ask_question(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Validates if a user can ask a question.

        Args:
            user_id: Telegram user ID attempting to ask a question.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if self.game_state != GameState.PLAYING:
            return False, f"Not in asking phase (current state: {self.game_state.value})"

        if self.current_player_id != user_id:
            return False, "Not your turn"

        if self.question is not None:
            return False, "Question already asked this turn"

        return True, None

    def validate_can_answer(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Validates if a user can answer the current question.

        Args:
            user_id: Telegram user ID attempting to answer.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if self.game_state != GameState.ANSWERING:
            return False, f"Not in answering phase (current state: {self.game_state.value})"

        if self.answerer_id != user_id:
            return False, "You are not the answerer"

        if self.answer is not None:
            return False, "Answer already provided"

        return True, None

    def validate_can_roll_dice(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Validates if a user can roll dice.

        Args:
            user_id: Telegram user ID attempting to roll.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if self.game_state != GameState.ROLLING:
            return False, f"Not in rolling phase (current state: {self.game_state.value})"

        if user_id != self.current_player_id and user_id != self.answerer_id:
            return False, "You are not involved in this turn"

        if user_id == self.current_player_id and self.current_player_roll is not None:
            return False, "You already rolled"

        if user_id == self.answerer_id and self.answerer_roll is not None:
            return False, "You already rolled"

        return True, None

    def __repr__(self) -> str:
        return f"Game(chat_id={self.chat_id}, players={len(self.players)}, state='{self.game_state.value}')"

