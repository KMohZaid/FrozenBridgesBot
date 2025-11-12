from pyrogram import Client, filters
from pyrogram.types import Message, ReplyParameters
from ..__main__ import running_games
from ..game import GameState
from .utils import send_player_list_with_ask_button


@Client.on_message(filters.command("playerlist") & filters.group)
async def playerlist_command(client: Client, message: Message):
    """Sends a reference to the main player list message."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        await message.reply_text(
            "❌ There's no active game in this group.\n\n"
            "Use /startbridge to create a new game!",
            quote=True
        )
        return

    # If player list message exists, send a reference to it
    if game.player_list_message_id:
        reply_params = ReplyParameters(message_id=game.player_list_message_id)

        await client.send_message(
            chat_id=chat_id,
            text="📋 Check the player list above ⬆️",
            reply_parameters=reply_params,
            message_thread_id=game.message_thread_id,
        )
    else:
        # No player list exists yet, create one
        await message.reply_text(
            "❌ Player list not found. The game may not have started yet.",
            quote=True
        )

