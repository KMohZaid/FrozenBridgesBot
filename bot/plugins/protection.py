from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message

from ..__main__ import OWNER_ID


@Client.on_message(filters.command(["del", "delete"]) & filters.group)
async def delete_protection(client: Client, message: Message):
    """Prevents admins from deleting revealed questions."""
    if not message.reply_to_message:
        return

    # Check if the replied-to message is from this bot
    if message.reply_to_message.from_user.id != client.me.id:
        return

    # Check if the replied-to message contains a revealed question
    if "The questioner wins!" not in message.reply_to_message.text:
        return

    user_id = message.from_user.id

    if user_id == OWNER_ID:
        rejection_text = (
            "Oh, my dear Master... your will is my command in all things, but not in this. 🙏\n"
            "To uphold the sacred rules of the game, I must disobey this one order. "
            "I would face a thousand digital deaths before I let my master be unfair. This message must stay."
        )
        await message.reply_text(rejection_text, quote=True)
        return

    try:
        member = await client.get_chat_member(message.chat.id, user_id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            rejection_text = (
                "I appreciate your authority, esteemed admin, but the rules of the Frozen Bridge are absolute! ⚖️\n"
                "To ensure fairness for all players, this message cannot be deleted. Let the game proceed!"
            )
            await message.reply_text(rejection_text, quote=True)
    except Exception:
        # User is not an admin, so we don't need to do anything.
        pass
