from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..__main__ import running_games
from ..game import GameState


@Client.on_message(filters.command("giveup") & filters.group)
async def giveup_command(client: Client, message: Message):
    """Allows an answerer to give up their turn."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    game = running_games.get(chat_id)
    if not game or game.game_state not in [GameState.PLAYING, GameState.ANSWERING, GameState.ASKING]:
        return await message.reply_text(
            "There is nothing to give up on right now.", quote=True
        )

    is_questioner = game.current_player and user_id == game.current_player.user_id
    is_answerer = game.answerer and user_id == game.answerer.user_id

    if not is_questioner and not is_answerer:
        return await message.reply_text(
            "You are not in a position to give up right now.", quote=True
        )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="✅ Yes, I give up", callback_data=f"confirm_giveup|{chat_id}"
                ),
                InlineKeyboardButton(
                    text="❌ No, I'll play", callback_data=f"cancel_giveup|{chat_id}"
                ),
            ]
        ]
    )

    await message.reply_text(
        f"{message.from_user.mention}, are you sure you want to give up your turn? This will count against your stats.",
        reply_markup=keyboard,
        quote=True,
    )
