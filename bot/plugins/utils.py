from pyrogram import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..game import Game, GameState
from ..__main__ import running_games # Import running_games here

async def is_user_in_any_active_game(user_id: int) -> bool:
    """Checks if a user is an active player in any currently running game."""
    for game in running_games.values():
        player = game.get_player(user_id)
        if player and player.is_active:
            return True
    return False

async def send_player_list_with_ask_button(client: Client, game: Game, additional_text: str = ""):
    """Sends or edits the player list message with scoreboard and Ask button.

    Uses edit when possible to reduce message spam. Only tags players in the
    initial message - subsequent edits update the scoreboard without mentions.

    Args:
        client: Pyrogram client instance.
        game: Game object containing current state.
        additional_text: Optional text to append (e.g., timer info).
    """
    # Build the message text
    message_text = game.get_status_message()
    if additional_text:
        message_text += f"\n\n{additional_text}"

    # Create keyboard with Ask button (only if game is in PLAYING state and has current player)
    keyboard = None
    if game.game_state == GameState.PLAYING and game.current_player:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❓ Ask a Player",
                        switch_inline_query_current_chat="ask | ",
                    )
                ]
            ]
        )

    # Try to edit existing message, otherwise send new one
    if game.player_list_message_id:
        try:
            await client.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.player_list_message_id,
                text=message_text,
                reply_markup=keyboard,
            )
            return  # Successfully edited
        except Exception:
            # Message was deleted or doesn't exist, will send new one below
            pass

    # Send new player list message (first time or if edit failed)
    new_message = await client.send_message(
        chat_id=game.chat_id,
        text=message_text,
        reply_markup=keyboard,
        message_thread_id=game.message_thread_id,
    )
    game.player_list_message_id = new_message.id

async def send_turn_start_message(client: Client, game: Game):
    """Sends lightweight turn notification that replies to the player list.

    Updates the main player list via edit, then sends a small notification
    message that replies to it to inform about the new turn without spamming tags.
    """
    if not game.current_player:
        # Handle game over or no active players
        await send_player_list_with_ask_button(client, game)
        return

    # First, update the player list (edit in place)
    await send_player_list_with_ask_button(client, game)

    # Get timer duration
    from ..timers import GameTimers
    if not hasattr(game, 'timers'):
        game.timers = GameTimers(game.chat_id)
    asking_time = game.timers.asking_timeout
    time_display = f"{asking_time // 60} minute{'s' if asking_time >= 120 else ''}" if asking_time >= 60 else f"{asking_time} seconds"

    # Send lightweight turn notification that replies to player list
    turn_message = (
        f"👑 **Next Turn:** {game.current_player.mention}\n\n"
        f"💡 Ask a question that can be answered with someone's NAME!\n"
        f"⏱️ You have {time_display} to ask your question."
    )

    # Create Ask button
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❓ Ask a Player",
                    switch_inline_query_current_chat="ask | ",
                )
            ]
        ]
    )

    # Send as reply to player list (if it exists)
    from pyrogram.types import ReplyParameters

    reply_params = None
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

    await client.send_message(
        chat_id=game.chat_id,
        text=turn_message,
        reply_parameters=reply_params,
        reply_markup=keyboard,
        message_thread_id=game.message_thread_id,
    )

    # Start asking timer
    from ..timers import start_timer
    start_timer(game, "asking", client)

async def end_game_logic(client: Client, chat_id: int, text: str):
    """Logic to properly end a game and clean up."""
    if chat_id in running_games:
        game = running_games[chat_id]

        # 1. Cancel active timer to prevent orphaned tasks
        from ..timers import cancel_timer
        cancel_timer(game)

        # 2. Change game state to ENDED so timer checks fail
        game.game_state = GameState.ENDED

        # 3. Clean up vote state
        game.reset_vote()

        # 4. Build final game summary
        import time

        # Calculate game duration
        duration_text = "Unknown"
        if game.start_time:
            duration_seconds = int(time.time() - game.start_time)
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60

            if hours > 0:
                duration_text = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                duration_text = f"{minutes}m {seconds}s"
            else:
                duration_text = f"{seconds}s"

        # Build final scoreboard (all players sorted by points)
        all_players_list = sorted(game.players, key=lambda p: p.game_answer_count, reverse=True)

        if all_players_list:
            scoreboard_lines = []
            for i, player in enumerate(all_players_list, 1):
                medal = ""
                if i == 1:
                    medal = "🥇 "
                elif i == 2:
                    medal = "🥈 "
                elif i == 3:
                    medal = "🥉 "

                status = "" if player.is_active else " (Left)"
                scoreboard_lines.append(
                    f"{medal}{i}. {player.mention} - {player.game_answer_count} points{status}"
                )

            scoreboard = "\n".join(scoreboard_lines)
            final_message = (
                f"**{text}**\n\n"
                f"🌉 The bridge has melted. The game is over.\n\n"
                f"📊 **Final Scoreboard:**\n{scoreboard}\n\n"
                f"⏱️ **Game Duration:** {duration_text}"
            )
        else:
            final_message = f"**{text}**\n\n🌉 The bridge has melted. The game is over."

        # 5. Remove from running games
        del running_games[chat_id]

        # 6. Send end message with stats
        message_thread_id = game.message_thread_id
        await client.send_message(chat_id, final_message, message_thread_id=message_thread_id)
async def skip_turn_logic(client: Client, game, text: str):
    """Logic to skip a player's turn and advance the game."""
    from pyrogram.types import ReplyParameters

    # Reply to player list if it exists
    reply_params = None
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

    await client.send_message(
        chat_id=game.chat_id,
        text=text,
        reply_parameters=reply_params,
        message_thread_id=game.message_thread_id,
    )
    game.game_state = GameState.PLAYING
    game.next_turn()
    game.answerer_id = None
    game.question = None
    game.answer = None
    if game.vote_type:
        game.reset_vote()
    await send_turn_start_message(client, game)

