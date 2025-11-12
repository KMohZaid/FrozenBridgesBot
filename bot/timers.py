"""
Timer management system for Frozen Bridges game.

Handles all game phase timers with countdown warnings.
"""

import asyncio
import logging
import os
import random
from typing import Optional
from datetime import datetime, timedelta

from pyrogram import Client
from pyrogram.types import ReplyParameters

from . import database
from .game import GameState
from .timer_config import GameTimers

# NOTE: Do not import from .plugins.utils or .plugins.game_flow at module level!
# This creates a circular import. Import them inside functions instead (late import).

LOGGER = logging.getLogger(__name__)


def calculate_warning_times(timeout: int) -> list:
    """Calculate warning times based on timeout duration.

    Returns warnings at:
    - Every minute (if timeout >= 60)
    - 30 seconds
    - 10 seconds
    """
    warnings = []

    # Add warnings for every minute
    minutes = timeout // 60
    for i in range(minutes, 0, -1):
        warnings.append(i * 60)

    # Add 30 second warning if timeout allows it
    if timeout > 30:
        warnings.append(30)

    # Add 10 second warning if timeout allows it
    if timeout > 10:
        warnings.append(10)

    # Remove duplicates and sort in descending order
    warnings = sorted(list(set(warnings)), reverse=True)
    return warnings


async def send_timer_warning(client: Client, game, mention: str, phase: str, seconds_left: int):
    """Sends a timer warning message and deletes the previous one."""
    if seconds_left >= 60:
        time_text = f"{seconds_left // 60} minute{'s' if seconds_left >= 120 else ''}"
    else:
        time_text = f"{seconds_left} seconds"

    emoji = "⏰" if seconds_left >= 30 else "⚠️"

    # Delete old warning message if exists
    if game.last_timer_warning_message_id:
        try:
            await client.delete_messages(game.chat_id, game.last_timer_warning_message_id)
        except Exception:
            pass  # Ignore if already deleted

    # Reply to player list if it exists
    reply_params = None
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

    # Send new warning and store its ID
    msg = await client.send_message(
        chat_id=game.chat_id,
        text=f"{emoji} {mention} - {time_text} left to {phase}!",
        reply_parameters=reply_params,
        message_thread_id=game.message_thread_id,
    )
    game.last_timer_warning_message_id = msg.id


async def asking_timer_task(client: Client, game, timeout: int):
    """Timer for asking phase with countdown warnings at every minute, 30sec, and 10sec."""
    # Late import to avoid circular dependency
    from .plugins.utils import end_game_logic, send_turn_start_message

    LOGGER.info(f"Starting asking timer for {timeout} seconds")

    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=timeout)

    # Calculate warning times (every minute + 30s + 10s)
    warnings = calculate_warning_times(timeout)

    try:
        while datetime.now() < end_time:
            if game.game_state != GameState.PLAYING or not game.current_player:
                LOGGER.info("Asking timer cancelled - state changed")
                return

            # Check if we should send a warning
            remaining = (end_time - datetime.now()).total_seconds()

            for warn_time in warnings[:]:
                if remaining <= warn_time and remaining > warn_time - 1:
                    # Check if current player still exists before warning
                    if game.current_player:
                        await send_timer_warning(
                            client,
                            game,
                            game.current_player.mention,
                            "ask your question",
                            warn_time
                        )
                    warnings.remove(warn_time)
                    break

            await asyncio.sleep(1)

        # Timeout reached
        if game.game_state == GameState.PLAYING and game.current_player:
            # Store player info before marking inactive
            timed_out_player = game.current_player
            timed_out_mention = timed_out_player.mention
            timed_out_user_id = timed_out_player.user_id

            LOGGER.info(f"Asking timer expired for player {timed_out_user_id}")

            # Mark player as inactive due to AFK
            game.remove_player(timed_out_user_id)

            # Send timeout message
            reply_params = None
            if game.player_list_message_id:
                reply_params = ReplyParameters(message_id=game.player_list_message_id)

            await client.send_message(
                chat_id=game.chat_id,
                text=f"⏱️ Time's up! {timed_out_mention} was AFK and has been marked inactive.",
                reply_parameters=reply_params,
                message_thread_id=game.message_thread_id,
            )

            # Check if game should end (1 or fewer active players)
            if len(game.active_players) <= 1:
                await end_game_logic(client, game.chat_id, "The game has ended because only one player is left.")
                return

            # Advance to next player
            game.next_turn()

            # Send the new turn start message with updated player list
            await send_turn_start_message(client, game)

    except asyncio.CancelledError:
        LOGGER.info("Asking timer cancelled")
        raise


async def answering_timer_task(client: Client, game, timeout: int):
    """Timer for answering phase with countdown warnings at every minute, 30sec, and 10sec."""
    # Late import to avoid circular dependency
    from .plugins.utils import end_game_logic, send_turn_start_message

    LOGGER.info(f"Starting answering timer for {timeout} seconds")

    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=timeout)

    # Calculate warning times (every minute + 30s + 10s)
    warnings = calculate_warning_times(timeout)

    try:
        while datetime.now() < end_time:
            if game.game_state != GameState.ANSWERING or not game.answerer:
                LOGGER.info("Answering timer cancelled - state changed")
                return

            # Check if we should send a warning
            remaining = (end_time - datetime.now()).total_seconds()

            for warn_time in warnings[:]:
                if remaining <= warn_time and remaining > warn_time - 1:
                    # Check if answerer still exists before warning
                    if game.answerer:
                        await send_timer_warning(
                            client,
                            game,
                            game.answerer.mention,
                            "answer the question",
                            warn_time
                        )
                    warnings.remove(warn_time)
                    break

            await asyncio.sleep(1)

        # Timeout reached
        if game.game_state == GameState.ANSWERING and game.answerer:
            # Store player info before marking inactive
            timed_out_answerer = game.answerer
            timed_out_mention = timed_out_answerer.mention
            timed_out_user_id = timed_out_answerer.user_id

            LOGGER.info(f"Answering timer expired for player {timed_out_user_id}")

            # Mark player as inactive due to AFK
            game.remove_player(timed_out_user_id)

            # Send timeout message
            reply_params = None
            if game.player_list_message_id:
                reply_params = ReplyParameters(message_id=game.player_list_message_id)

            await client.send_message(
                chat_id=game.chat_id,
                text=f"⏱️ Time's up! {timed_out_mention} was AFK and has been marked inactive.",
                reply_parameters=reply_params,
                message_thread_id=game.message_thread_id,
            )

            # Check if game should end (1 or fewer active players)
            if len(game.active_players) <= 1:
                await end_game_logic(client, game.chat_id, "The game has ended because only one player is left.")
                return

            # Advance to next player
            game.next_turn()

            # Send the new turn start message with updated player list
            await send_turn_start_message(client, game)

    except asyncio.CancelledError:
        LOGGER.info("Answering timer cancelled")
        raise


async def dice_roll_timer_task(client: Client, game, timeout: int):
    """Timer for dice rolling phase with auto-roll."""
    # Late import to avoid circular dependency
    from .plugins.game_flow import process_dice_rolls

    LOGGER.info(f"Starting dice roll timer for {timeout} seconds")

    await asyncio.sleep(timeout)

    if game.game_state != GameState.ROLLING:
        return

    # Validate players still exist
    if not game.current_player or not game.answerer:
        LOGGER.warning("Dice roll timer expired but player(s) missing")
        return

    # Auto-roll for any player who hasn't rolled
    reply_params = None
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

    if game.current_player_roll is None:
        game.current_player_roll = random.randint(1, 6)
        await client.send_message(
            chat_id=game.chat_id,
            text=f"🎲 {game.current_player.mention} didn't roll - auto-rolled: **{game.current_player_roll}**",
            reply_parameters=reply_params,
            message_thread_id=game.message_thread_id,
        )

    if game.answerer_roll is None:
        game.answerer_roll = random.randint(1, 6)
        await client.send_message(
            chat_id=game.chat_id,
            text=f"🎲 {game.answerer.mention} didn't roll - auto-rolled: **{game.answerer_roll}**",
            reply_parameters=reply_params,
            message_thread_id=game.message_thread_id,
        )

    # Process the dice rolls
    await process_dice_rolls(client, game)


async def accept_reject_timer_task(client: Client, game, timeout: int):
    """Timer for accept/reject phase with countdown warnings and auto-accept."""
    # Late import to avoid circular dependency
    from .plugins.utils import send_turn_start_message

    LOGGER.info(f"Starting accept/reject timer for {timeout} seconds")

    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=timeout)

    # Calculate warning times (every minute + 30s + 10s)
    warnings = calculate_warning_times(timeout)

    try:
        while datetime.now() < end_time:
            if game.game_state != GameState.ROLLING:
                LOGGER.info("Accept/reject timer cancelled - state changed")
                return

            # Check if we should send a warning
            remaining = (end_time - datetime.now()).total_seconds()

            for warn_time in warnings[:]:
                if remaining <= warn_time and remaining > warn_time - 1:
                    # Check if current player still exists before warning
                    if game.current_player:
                        await send_timer_warning(
                            client,
                            game,
                            game.current_player.mention,
                            "accept or reject the answer",
                            warn_time
                        )
                    warnings.remove(warn_time)
                    break

            await asyncio.sleep(1)

        # Timeout reached - auto-accept
        if game.game_state == GameState.ROLLING and game.current_player:
            LOGGER.info(f"Accept/reject timer expired - auto-accepting")
            reply_params = None
            if game.player_list_message_id:
                reply_params = ReplyParameters(message_id=game.player_list_message_id)

            await client.send_message(
                chat_id=game.chat_id,
                text=f"⏱️ Time's up! {game.current_player.mention} didn't respond. Answer auto-accepted!",
                reply_parameters=reply_params,
                message_thread_id=game.message_thread_id,
            )

            # Auto-accept: give points to answerer
            if game.answerer:
                game.answerer.game_answer_count += 1

            # End turn and advance
            if game.current_player:
                database.update_stats(game.current_player.user_id, questions_asked=1)
            if game.answerer:
                database.update_stats(game.answerer.user_id, questions_answered=1)

            game.clear_turn_state()
            game.next_turn()
            await send_turn_start_message(client, game)

    except asyncio.CancelledError:
        LOGGER.info("Accept/reject timer cancelled")
        raise


def start_timer(game, timer_type: str, client: Client) -> Optional[asyncio.Task]:
    """Starts a timer task and stores it in the game object."""
    # Cancel any existing timer
    if game.active_timer:
        try:
            game.active_timer.cancel()
        except:
            pass

    # Get timers config (create if doesn't exist)
    if not hasattr(game, 'timers'):
        game.timers = GameTimers(game.chat_id)

    # Create appropriate timer task
    if timer_type == "asking":
        task = asyncio.create_task(asking_timer_task(client, game, game.timers.asking_timeout))
    elif timer_type == "answering":
        task = asyncio.create_task(answering_timer_task(client, game, game.timers.answering_timeout))
    elif timer_type == "dice_roll":
        task = asyncio.create_task(dice_roll_timer_task(client, game, game.timers.dice_roll_timeout))
    elif timer_type == "accept_reject":
        task = asyncio.create_task(accept_reject_timer_task(client, game, game.timers.accept_reject_timeout))
    else:
        LOGGER.error(f"Unknown timer type: {timer_type}")
        return None

    game.active_timer = task
    LOGGER.info(f"Started {timer_type} timer")
    return task


def cancel_timer(game):
    """Cancels the active timer for a game."""
    if game.active_timer:
        try:
            game.active_timer.cancel()
            LOGGER.info("Timer cancelled")
        except:
            pass
        game.active_timer = None
