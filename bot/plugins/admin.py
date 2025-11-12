from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message

from ..__main__ import running_games, OWNER_ID, bot
from .utils import skip_turn_logic, send_turn_start_message, end_game_logic


async def is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    """Check if a user is an admin in the chat or the bot owner."""
    # Check if bot owner
    if user_id == OWNER_ID:
        return True

    # Check if Telegram group admin
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False


@Client.on_message(filters.command("adminskip") & filters.group)
async def adminskip_command(client: Client, message: Message):
    """Allows an admin to skip a player's turn and make them inactive."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        return await message.reply_text("No game is currently running.")

    if not await is_admin(client, chat_id, message.from_user.id):
        return await message.reply_text("🛡️ Only admins can use this command.")

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif len(message.command) > 1:
        try:
            target_user = await client.get_users(message.command[1])
        except Exception:
            return await message.reply_text("Could not find the specified user.")
    else:
        return await message.reply_text("You need to reply to a user or provide their username/ID to skip them.")

    if not target_user:
        return await message.reply_text("Could not identify the target user.")

    target_player = game.get_player(target_user.id)
    if not target_player or not target_player.is_active:
        return await message.reply_text("This player is not an active player in the game.")

    # Store if they were current player
    was_current = (game.current_player_id == target_player.user_id)

    # Use the new remove_player method
    game.remove_player(target_player.user_id)

    text = f"🛡️ Admin {message.from_user.mention} skipped {target_player.mention}. They are now inactive and can rejoin with /joinbridge."

    if was_current:
        # Current player was skipped - advance turn
        game.clear_turn_state()
        game.next_turn()
        await message.reply_text(text)
        await send_turn_start_message(client, game)
    else:
        await message.reply_text(text)


@Client.on_message(filters.command("adminkick") & filters.group)
async def adminkick_command(client: Client, message: Message):
    """Allows an admin to permanently remove a player from the game."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        return await message.reply_text("No game is currently running.")

    if not await is_admin(client, chat_id, message.from_user.id):
        return await message.reply_text("🛡️ Only admins can use this command.")

    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif len(message.command) > 1:
        try:
            target_user = await client.get_users(message.command[1])
        except Exception:
            return await message.reply_text("Could not find the specified user.")
    else:
        return await message.reply_text("You need to reply to a user or provide their username/ID to kick them.")

    if not target_user:
        return await message.reply_text("Could not identify the target user.")

    target_player = game.get_player(target_user.id)
    if not target_player or not target_player.is_active:
        return await message.reply_text("This player is not an active player in the game.")

    # Store if they were current player
    was_current = (game.current_player_id == target_player.user_id)

    # Remove player
    game.remove_player(target_player.user_id)

    text = f"🛡️ Admin {message.from_user.mention} kicked {target_player.mention} from the game."

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


@Client.on_message(filters.command("settimer") & filters.group)
async def settimer_command(client: Client, message: Message):
    """Allows admins to configure game timers."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        return await message.reply_text("No game is currently running.")

    if not await is_admin(client, chat_id, message.from_user.id):
        return await message.reply_text("🛡️ Only admins can use this command.")

    # Ensure game has timers config
    if not hasattr(game, 'timers'):
        from ..timers import GameTimers
        game.timers = GameTimers()

    # Parse command: /settimer <phase> <minutes>  OR  /settimer reset
    if len(message.command) < 2:
        return await message.reply_text(
            "**Timer Settings**\n\n"
            f"⏰ Asking: {game.timers.asking_timeout // 60} minutes\n"
            f"⏰ Answering: {game.timers.answering_timeout // 60} minutes\n"
            f"⏰ Accept/Reject: {game.timers.accept_reject_timeout // 60} minutes\n"
            f"🎲 Dice Roll: {game.timers.dice_roll_timeout} seconds\n\n"
            "**Usage:**\n"
            "`/settimer asking <minutes>` (1-30 min)\n"
            "`/settimer answering <minutes>` (1-5 min)\n"
            "`/settimer accept <minutes>` (1-5 min)\n"
            "`/settimer reset` (reset to defaults)"
        )

    phase = message.command[1].lower()

    if phase == "reset":
        game.timers.reset_to_defaults()
        return await message.reply_text(
            "✅ Timers reset to defaults:\n"
            "⏰ Asking: 2 minutes\n"
            "⏰ Answering: 3 minutes\n"
            "⏰ Accept/Reject: 2 minutes"
        )

    if len(message.command) < 3:
        return await message.reply_text("Please specify the time in minutes.")

    try:
        minutes = int(message.command[2])
        seconds = minutes * 60
    except ValueError:
        return await message.reply_text("Invalid time value. Please use a number.")

    if phase in ["asking", "ask", "question"]:
        if game.timers.set_asking_timeout(seconds):
            await message.reply_text(f"✅ Asking timer set to {minutes} minute{'s' if minutes != 1 else ''}.")
        else:
            await message.reply_text(f"❌ Asking timer must be between 1 and 30 minutes.")

    elif phase in ["answering", "answer"]:
        if game.timers.set_answering_timeout(seconds):
            await message.reply_text(f"✅ Answering timer set to {minutes} minute{'s' if minutes != 1 else ''}.")
        else:
            await message.reply_text(f"❌ Answering timer must be between 1 and 5 minutes.")

    elif phase in ["accept", "reject", "acceptreject"]:
        if game.timers.set_accept_reject_timeout(seconds):
            await message.reply_text(f"✅ Accept/Reject timer set to {minutes} minute{'s' if minutes != 1 else ''}.")
        else:
            await message.reply_text(f"❌ Accept/Reject timer must be between 1 and 5 minutes.")

    else:
        await message.reply_text("Unknown phase. Use: asking, answering, or accept")


@Client.on_message(filters.command("feedback"))
async def feedback_command(client: Client, message: Message):
    """Allows users to send feedback to the bot owner."""
    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply_text(
            "**Send Feedback**\n\n"
            "Usage: `/feedback <your message>`\n\n"
            "Example: `/feedback The new timer system is great!`"
        )

    feedback_text = message.text.split(maxsplit=1)[1] if len(message.command) >= 2 else message.reply_to_message.text
    user = message.from_user

    # Send feedback to bot owner
    try:
        await client.send_message(
            OWNER_ID,
            f"📢 **Feedback from {user.mention}**\n"
            f"User ID: `{user.id}`\n"
            f"Username: @{user.username if user.username else 'None'}\n"
            f"Group: {message.chat.title if message.chat else 'DM'} (ID: `{message.chat.id}`)\n\n"
            f"**Message:**\n{feedback_text}"
        )
        await message.reply_text("✅ Feedback sent! Thank you for helping improve the bot!")
    except Exception as e:
        await message.reply_text(f"❌ Failed to send feedback: {e}")


@Client.on_message(filters.command("commandlist"))
async def commandlist_command(client: Client, message: Message):
    """Sends the content of the generated command list file."""
    try:
        with open("auto_generated_commands_list.txt", "r") as f:
            commands_text = f.read()

        # Format the output nicely
        formatted_text = "**🌉 Frozen Bridges - All Commands**\n\n"
        formatted_text += commands_text
        formatted_text += "\n💡 **Tip:** Type /help for organized command list!"

        await message.reply_text(formatted_text, quote=True)
    except FileNotFoundError:
        await message.reply_text("Command list file not found. Please restart the bot.", quote=True)
    except Exception as e:
        await message.reply_text(f"An error occurred while reading the command list: {e}", quote=True)
