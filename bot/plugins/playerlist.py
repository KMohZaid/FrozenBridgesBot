from pyrogram import Client, filters
from pyrogram.types import Message
from ..__main__ import running_games
from ..game import GameState
from .utils import send_player_list_with_ask_button


@Client.on_message(filters.command("playerlist") & filters.group)
async def playerlist_command(client: Client, message: Message):
    """Updates the existing player list message with current timer info."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        await message.reply_text(
            "❌ There's no active game in this group.\n\n"
            "Use /startbridge to create a new game!",
            quote=True
        )
        return

    # Build timer info based on current game state
    additional_text = ""
    if game.game_state == GameState.PLAYING and game.current_player:
        from ..timers import GameTimers
        if not hasattr(game, 'timers'):
            game.timers = GameTimers(game.chat_id)
        asking_time = game.timers.asking_timeout
        time_display = f"{asking_time // 60} minute{'s' if asking_time >= 120 else ''}" if asking_time >= 60 else f"{asking_time} seconds"
        additional_text = (
            f"💡 **Remember:** Ask a question that can be answered with someone's NAME!\n\n"
            f"⏱️ You have {time_display} to ask your question."
        )
    elif game.game_state == GameState.ANSWERING and game.answerer:
        from ..timers import GameTimers
        if not hasattr(game, 'timers'):
            game.timers = GameTimers(game.chat_id)
        answering_time = game.timers.answering_timeout
        time_display = f"{answering_time // 60} minute{'s' if answering_time >= 120 else ''}" if answering_time >= 60 else f"{answering_time} seconds"
        additional_text = f"⏱️ {game.answerer.mention} has {time_display} to answer."
    elif game.game_state == GameState.ROLLING:
        from ..timers import GameTimers
        if not hasattr(game, 'timers'):
            game.timers = GameTimers(game.chat_id)
        dice_time = game.timers.dice_roll_timeout
        time_display = f"{dice_time // 60} minute{'s' if dice_time >= 120 else ''}" if dice_time >= 60 else f"{dice_time} seconds"
        additional_text = f"🎲 Rolling dice! {time_display} remaining."

    # Use unified player list function - this will edit the existing message if it exists
    await send_player_list_with_ask_button(client, game, additional_text)

