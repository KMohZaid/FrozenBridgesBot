import logging
import random

from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

from .. import database
from ..__main__ import running_games
from ..game import GameState
from ..taunt_messages import get_taunt
from .utils import send_turn_start_message

LOGGER = logging.getLogger(__name__)


async def process_dice_rolls(client: Client, game):
    """Processes dice rolls and reveals the outcome without repeating roll values.

    Individual roll notifications were already sent, so this just shows
    the final result (question revealed or hidden) and the answer.
    """
    # Prevent duplicate processing from race condition
    if game.game_state != GameState.ROLLING:
        LOGGER.warning("process_dice_rolls called but game is not in ROLLING state")
        return

    # Validate both players still exist
    if not game.current_player or not game.answerer:
        LOGGER.error("process_dice_rolls called but player(s) missing")
        return

    chat_id = game.chat_id
    current_player = game.current_player
    answerer = game.answerer

    cp_roll = game.current_player_roll
    a_roll = game.answerer_roll

    if cp_roll > a_roll:
        # Question revealed
        taunt = get_taunt("revealed")
        result_text = f"🎲 **The question was revealed!**\n\n"
        if taunt:
            result_text += f"{taunt}\n\n"
        result_text += (
            f'❓ **Question:**\n> {game.question}\n\n'
            f'💬 **Answer:**\n> {game.answer}'
        )
        database.update_player_stat(current_player.user_id, "times_revealed_question")
        database.update_player_stat(answerer.user_id, "times_exposed")
        await client.send_message(chat_id, result_text)
        await end_turn_and_advance(client, game)
    elif a_roll > cp_roll:
        # Question stays secret
        taunt = get_taunt("hidden")
        result_text = f"🎲 **The question was NOT revealed!** 🤫\n\n"
        if taunt:
            result_text += f"{taunt}\n\n"
        result_text += (
            f"The answer was **{game.answer}**\n\n"
            f"🕵️ Can you figure out what the secret question was?"
        )
        database.update_player_stat(current_player.user_id, "times_failed_to_reveal")
        database.update_player_stat(answerer.user_id, "times_lucky")
        await client.send_message(chat_id, result_text)
        await end_turn_and_advance(client, game)
    else:
        # Tie
        taunt = get_taunt("tie")
        result_text = "🎲 **It's a tie!** Please roll again."
        if taunt:
            result_text += f"\n\n{taunt}"
        game.current_player_roll = None
        game.answerer_roll = None
        await client.send_message(chat_id, result_text)



@Client.on_message(filters.dice & filters.group)
async def dice_handler(client: Client, message: Message):
    """Handles dice rolls from players."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game or game.game_state != GameState.ROLLING:
        return

    # Validate players exist before accessing their IDs
    if not game.current_player or not game.answerer:
        LOGGER.warning("Dice rolled but current_player or answerer is None")
        return

    user_id = message.from_user.id
    current_player_id = game.current_player.user_id
    answerer_id = game.answerer.user_id

    if user_id not in [current_player_id, answerer_id]:
        return

    roll_value = message.dice.value

    if user_id == current_player_id:
        if game.current_player_roll is not None:
            await message.reply_text("You have already rolled.", quote=True)
            return
        game.current_player_roll = roll_value

        # Add taunt for special rolls
        response = f"{game.current_player.mention} rolled a **{roll_value}**."
        if roll_value == 1:
            taunt = get_taunt("roll_one")
            if taunt:
                response += f"\n{taunt}"
        elif roll_value == 6:
            taunt = get_taunt("roll_six")
            if taunt:
                response += f"\n{taunt}"

        await message.reply_text(response, quote=True)

    elif user_id == answerer_id:
        if game.answerer_roll is not None:
            await message.reply_text("You have already rolled.", quote=True)
            return
        game.answerer_roll = roll_value

        # Add taunt for special rolls
        response = f"{game.answerer.mention} rolled a **{roll_value}**."
        if roll_value == 1:
            taunt = get_taunt("roll_one")
            if taunt:
                response += f"\n{taunt}"
        elif roll_value == 6:
            taunt = get_taunt("roll_six")
            if taunt:
                response += f"\n{taunt}"

        await message.reply_text(response, quote=True)

    if game.current_player_roll is not None and game.answerer_roll is not None:
        await process_dice_rolls(client, game)


async def end_turn_and_advance(client: Client, game):
    """Ends the current turn and advances to the next player."""
    LOGGER.info(f"Ending turn for player {game.current_player.user_id if game.current_player else 'None'}.")
    current_player = game.current_player
    answerer = game.answerer

    # Update stats in database (points were already awarded during difficulty rating)
    if current_player:
        database.update_player_stat(current_player.user_id, "total_questions_asked")
    if answerer:
        database.update_player_stat(answerer.user_id, "total_answers_given")

    # Reset for the next turn
    game.current_player_roll = None
    game.answerer_roll = None
    game.answerer_id = None
    game.question = None
    game.answer = None
    game.game_state = GameState.PLAYING
    game.next_turn()

    LOGGER.info(f"Next turn started. Current player is now {game.current_player.user_id if game.current_player else 'None'}.")
    await send_turn_start_message(client, game)
