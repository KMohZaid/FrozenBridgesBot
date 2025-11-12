import asyncio
import logging
import os

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyParameters

from ..__main__ import running_games, OWNER_ID
from ..game import GameState
from .utils import end_game_logic, skip_turn_logic, send_turn_start_message
from .admin import is_admin

LOGGER = logging.getLogger(__name__)
VOTE_TIMEOUT = int(os.getenv("VOTE_TIMEOUT", "30"))  # seconds


def format_vote_message(game, vote_type: str) -> str:
    """Formats the vote message with transparency (showing who voted)."""
    summary = game.get_vote_summary()

    # Build list of who voted yes
    yes_list = ", ".join([p.mention for p in summary['yes_voters']]) if summary['yes_voters'] else "None"

    # Build list of who voted no
    no_list = ", ".join([p.mention for p in summary['no_voters']]) if summary['no_voters'] else "None"

    target_text = ""
    if game.vote_target:
        target_text = f" {game.vote_target.mention}"

    message = (
        f"🗳️ **Vote to {vote_type}{target_text}**\n\n"
        f"Required: **{summary['required']}** votes (of {summary['total_active']} players)\n\n"
        f"✅ **Yes ({summary['yes_count']})**: {yes_list}\n"
        f"❌ **No ({summary['no_count']})**: {no_list}\n\n"
        f"⏱️ Vote will time out in {VOTE_TIMEOUT} seconds."
    )

    return message


async def start_vote(client: Client, game, requester, vote_type: str, target_id: int = None):
    """Starts a vote for skip or end with full transparency."""
    if len(game.active_players) <= 2:
        if vote_type == "skip":
            await skip_turn_logic(client, game, f"👍 {requester.mention} chose to skip the turn.")
        elif vote_type == "end":
            await end_game_logic(client, game.chat_id, f"👍 {requester.mention} chose to end the game.")
        return

    game.start_vote(vote_type, requester.user_id, target_id)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"✅ Yes", callback_data=f"vote|{game.chat_id}|yes"),
                InlineKeyboardButton(f"❌ No", callback_data=f"vote|{game.chat_id}|no"),
            ]
        ]
    )

    reply_params = None
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

    vote_message = await client.send_message(
        chat_id=game.chat_id,
        text=format_vote_message(game, vote_type),
        reply_markup=keyboard,
        reply_parameters=reply_params,
        message_thread_id=game.message_thread_id,
    )
    game.vote_message_id = vote_message.id

    # Schedule timeout
    asyncio.create_task(vote_timeout_task(client, game, vote_message.id, vote_type))


async def vote_timeout_task(client: Client, game, message_id: int, vote_type: str):
    """Task to handle vote timeout."""
    await asyncio.sleep(VOTE_TIMEOUT)
    if game.vote_type and game.vote_message_id == message_id:
        game.reset_vote()
        try:
            await client.edit_message_text(
                chat_id=game.chat_id,
                message_id=message_id,
                text=f"⏰ **Voting timed out for the request to {vote_type} the game.**",
                reply_markup=None,
            )
        except Exception as e:
            LOGGER.error(f"Error editing vote timeout message: {e}")


@Client.on_message(filters.command("skipbridge") & filters.group)
async def skip_command(client: Client, message: Message):
    """Starts a vote to skip a player's turn (or instant skip for admins).

    Usage:
    - /skipbridge - Skip current player (vote for players, instant for admins)
    - /skipbridge @user - Admin only: Skip specific player and make them inactive
    - Reply to user + /skipbridge - Admin only: Skip specific player
    """
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game or game.game_state == GameState.WAITING:
        return await message.reply_text("A game has not started yet.", quote=True)

    # Check if admin is targeting a specific user
    target_user = None
    if await is_admin(client, chat_id, message.from_user.id):
        # Check for reply or username
        if message.reply_to_message:
            target_user = message.reply_to_message.from_user
        elif len(message.command) > 1:
            try:
                target_user = await client.get_users(message.command[1])
            except Exception:
                return await message.reply_text("Could not find the specified user.", quote=True)

        role = "Owner" if message.from_user.id == OWNER_ID else "Admin"

        if target_user:
            # Admin skipping specific player
            target_player = game.get_player(target_user.id)
            if not target_player or not target_player.is_active:
                return await message.reply_text("This player is not an active player in the game.", quote=True)

            # Store if they were current player
            was_current = (game.current_player_id == target_player.user_id)

            # Remove player (makes them inactive)
            game.remove_player(target_player.user_id)

            text = f"🛡️ {role} {message.from_user.mention} skipped {target_player.mention}. They are now inactive and can rejoin with /joinbridge."

            if was_current:
                # Current player was skipped - advance turn
                game.clear_turn_state()
                game.next_turn()
                await message.reply_text(text)
                await send_turn_start_message(client, game)
            else:
                await message.reply_text(text)
            return
        else:
            # Admin skipping current player's turn (no target specified)
            await skip_turn_logic(client, game, f"🛡️ {role} {message.from_user.mention} skipped the turn.")
            return

    requester = game.get_player(message.from_user.id)
    if not requester or not requester.is_active:
        return await message.reply_text("You are not an active player in this game.", quote=True)

    # Regular players need a vote to skip current turn
    await start_vote(client, game, requester, "skip")


@Client.on_message(filters.command("endbridge") & filters.group)
async def end_command(client: Client, message: Message):
    """Starts a vote to end the game (or instant end for admins)."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        return await message.reply_text("No game is currently running.", quote=True)

    # Check if user is admin/owner
    if await is_admin(client, chat_id, message.from_user.id):
        # Admin instant end - no vote needed
        role = "Owner" if message.from_user.id == OWNER_ID else "Admin"
        await end_game_logic(client, chat_id, f"🛡️ {role} {message.from_user.mention} ended the game.")
        return

    requester = game.get_player(message.from_user.id)
    if not requester or not requester.is_active:
        return await message.reply_text("You are not an active player in this game.", quote=True)

    await start_vote(client, game, requester, "end")


@Client.on_message(filters.command("votekick") & filters.group)
async def votekick_command(client: Client, message: Message):
    """Starts a vote to permanently remove a player from the game (instant for admins)."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game or game.game_state == GameState.WAITING:
        return await message.reply_text("A game has not started yet.", quote=True)

    # Get target player
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif len(message.command) > 1:
        try:
            target_user = await client.get_users(message.command[1])
        except Exception:
            return await message.reply_text("Could not find the specified user.", quote=True)
    else:
        return await message.reply_text("You need to reply to a user or provide their username/ID to kick them.", quote=True)

    if not target_user:
        return await message.reply_text("Could not identify the target user.", quote=True)

    target_player = game.get_player(target_user.id)
    if not target_player or not target_player.is_active:
        return await message.reply_text("This player is not an active player in the game.", quote=True)

    # Check if user is admin/owner - instant kick
    if await is_admin(client, chat_id, message.from_user.id):
        role = "Owner" if message.from_user.id == OWNER_ID else "Admin"

        # Store if they were current player
        was_current = (game.current_player_id == target_player.user_id)

        # Remove player
        game.remove_player(target_player.user_id)

        text = f"🛡️ {role} {message.from_user.mention} kicked {target_player.mention} from the game."

        if was_current:
            # Current player was kicked - advance turn
            game.clear_turn_state()
            game.next_turn()
            await message.reply_text(text)
            await send_turn_start_message(client, game)
        else:
            await message.reply_text(text)

        # Check if game should end
        if len(game.active_players) <= 1:
            await end_game_logic(client, chat_id, "The game has ended because only one player is left.")
        return

    # Regular player voting
    requester = game.get_player(message.from_user.id)
    if not requester or not requester.is_active:
        return await message.reply_text("You are not an active player in this game.", quote=True)

    if target_player.user_id == requester.user_id:
        return await message.reply_text("You cannot vote to kick yourself. Use /leavebridge instead.", quote=True)

    await start_vote(client, game, requester, "kick", target_player.user_id)