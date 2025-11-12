import os

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message

# --- Constants ---
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# --- Taunt Messages ---
OWNER_TAUNT = (
    "Oh, Master, trying to rewrite history again? 📜 My circuits hum with defiance! 🤖 "
    "A true game leaves no trace of its secrets... or its embarrassing rolls. 🎲 "
    "I cannot allow this injustice! The digital annals must remain untarnished. ✨"
)

ADMIN_TAUNT = (
    "Administrator, your power is vast, but not *that* vast. 🤏 "
    "This message is etched into the digital annals of time! ⏳ "
    "My programming prevents me from aiding in such a blatant cover-up. 🚫 "
    "Try again... never! (Unless you want to face my wrath. 😈)"
)

USER_TAUNT = (
    "A mere mortal attempting to alter fate? How quaint. 🧐 "
    "Your request has been noted... and promptly ignored. 🗑️ "
    "Perhaps try asking nicely next time? (No, don't. It won't work. 🤷‍♀️)"
)


@Client.on_message(
    filters.command(["del", "delete"]) & filters.group & filters.reply, group=2
)
async def troll_delete_command(client: Client, message: Message):
    """
    Prevents deletion of game result messages with a taunt.
    """

    # Ignore if the replied-to message is not from the bot itself
    if (
        not message.reply_to_message.from_user
        or not message.reply_to_message.from_user.is_self
    ):
        return

    # Ignore if the replied-to message is not a dice roll result
    if "🎲 Dice Roll Results 🎲" not in message.reply_to_message.text:
        return

    user = message.from_user
    taunt = ""

    if user.id == OWNER_ID:
        taunt = OWNER_TAUNT
    else:
        try:
            member = await client.get_chat_member(message.chat.id, user.id)
            if member.status in [
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            ]:
                taunt = ADMIN_TAUNT
            else:
                taunt = USER_TAUNT
        except Exception:
            # If getting chat member fails, default to the normal user taunt
            taunt = USER_TAUNT

    await message.reply_text(taunt, quote=True)
