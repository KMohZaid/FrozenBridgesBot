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
    """
    Unified function to send player list message with Ask button.
    This ensures consistent formatting across all places where the player list is shown.

    Args:
        client: Pyrogram client
        game: Game object
        additional_text: Optional text to append (e.g., timer info)
    """
    # Delete old player list message if it exists
    if game.player_list_message_id:
        try:
            await client.delete_messages(game.chat_id, game.player_list_message_id)
        except Exception:
            pass  # Ignore if message is already deleted

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

    # Send new player list message
    new_message = await client.send_message(
        chat_id=game.chat_id,
        text=message_text,
        reply_markup=keyboard,
    )
    game.player_list_message_id = new_message.id

async def send_turn_start_message(client: Client, game: Game):
    """Sends the status message at the start of a new turn with an 'Ask' button and timer."""
    if not game.current_player:
        # Handle game over or no active players
        await send_player_list_with_ask_button(client, game)
        return

    # Get timer duration
    from ..timers import GameTimers
    if not hasattr(game, 'timers'):
        game.timers = GameTimers()
    asking_time = game.timers.asking_timeout
    time_display = f"{asking_time // 60} minute{'s' if asking_time >= 120 else ''}" if asking_time >= 60 else f"{asking_time} seconds"

    # Send player list with timer info
    await send_player_list_with_ask_button(
        client,
        game,
        additional_text=(
            f"💡 **Remember:** Ask a question that can be answered with someone's NAME!\n\n"
            f"⏱️ You have {time_display} to ask your question."
        )
    )

    # Start asking timer
    from ..timers import start_timer
    start_timer(game, "asking", client)

async def end_game_logic(client: Client, chat_id: int, text: str):
    """Logic to properly end a game and clean up."""
    if chat_id in running_games:
        del running_games[chat_id]
        await client.send_message(
            chat_id, f"**{text}**\n\n🌉 The bridge has melted. The game is over."
        )
async def skip_turn_logic(client: Client, game, text: str):
    """Logic to skip a player's turn and advance the game."""
    await client.send_message(game.chat_id, text)
    game.game_state = GameState.PLAYING
    game.next_turn()
    game.answerer_id = None
    game.question = None
    game.answer = None
    if game.vote_type:
        game.reset_vote()
    await send_turn_start_message(client, game)

