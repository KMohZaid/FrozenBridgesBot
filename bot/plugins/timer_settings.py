"""
Timer Settings Plugin
Provides interactive menu for configuring group-specific timer settings
"""
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from ..database import get_group_settings, create_group_settings, update_group_setting
from ..__main__ import running_games
from .admin import is_admin
import logging
import os

LOGGER = logging.getLogger(__name__)

# Timer stepping values (in seconds)
TIMER_STEPS = {
    'asking': [30, 45, 60, 90, 120, 180, 240, 300, 360, 420, 480, 540, 600],
    'answering': [30, 45, 60, 90, 120, 180, 240, 300, 360, 420, 480, 540, 600],
    'dice_roll': [15, 30, 45, 60, 90, 120],
    'accept_reject': [30, 60, 90, 120, 150, 180, 240, 300],
    'vote': [10, 15, 20, 30, 45, 60, 90]
}


def format_time(seconds: int) -> str:
    """Formats seconds into a readable time string."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        if remaining_seconds == 0:
            return f"{minutes}m"
        else:
            return f"{minutes}m {remaining_seconds}s"
    else:
        hours = seconds // 3600
        remaining_minutes = (seconds % 3600) // 60
        if remaining_minutes == 0:
            return f"{hours}h"
        else:
            return f"{hours}h {remaining_minutes}m"


def get_timer_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Generates the interactive keyboard for timer settings."""
    keyboard = [
        # Asking timeout
        [
            InlineKeyboardButton("−", callback_data="timer_asking_dec"),
            InlineKeyboardButton(f"⏱️ Asking: {format_time(settings['asking_timeout'])}", callback_data="timer_noop"),
            InlineKeyboardButton("+", callback_data="timer_asking_inc")
        ],
        # Answering timeout
        [
            InlineKeyboardButton("−", callback_data="timer_answering_dec"),
            InlineKeyboardButton(f"💭 Answering: {format_time(settings['answering_timeout'])}", callback_data="timer_noop"),
            InlineKeyboardButton("+", callback_data="timer_answering_inc")
        ],
        # Dice roll timeout
        [
            InlineKeyboardButton("−", callback_data="timer_dice_roll_dec"),
            InlineKeyboardButton(f"🎲 Dice Roll: {format_time(settings['dice_roll_timeout'])}", callback_data="timer_noop"),
            InlineKeyboardButton("+", callback_data="timer_dice_roll_inc")
        ],
        # Accept/Reject timeout
        [
            InlineKeyboardButton("−", callback_data="timer_accept_reject_dec"),
            InlineKeyboardButton(f"✅ Accept/Reject: {format_time(settings['accept_reject_timeout'])}", callback_data="timer_noop"),
            InlineKeyboardButton("+", callback_data="timer_accept_reject_inc")
        ],
        # Vote timeout
        [
            InlineKeyboardButton("−", callback_data="timer_vote_dec"),
            InlineKeyboardButton(f"🗳️ Vote: {format_time(settings['vote_timeout'])}", callback_data="timer_noop"),
            InlineKeyboardButton("+", callback_data="timer_vote_inc")
        ],
        # Reset and Close buttons
        [
            InlineKeyboardButton("🔄 Reset to Defaults", callback_data="timer_reset"),
            InlineKeyboardButton("❌ Close", callback_data="timer_close")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


@Client.on_message(filters.command("settimer") & filters.group)
async def settimer_command(client: Client, message: Message):
    """Shows interactive timer settings menu (Admin only)."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check if user is admin
    if not await is_admin(client, chat_id, user_id):
        await message.reply_text("⚠️ Only group admins can change timer settings.", quote=True)
        return

    # Get or create settings
    settings = get_group_settings(chat_id)
    if not settings:
        settings = create_group_settings(chat_id)
        if not settings:
            await message.reply_text("❌ Error: Could not load settings from database.", quote=True)
            return

    # Send settings menu
    text = """⏱️ **Timer Settings**

Use the +/− buttons to adjust each timer:

• **Asking**: Time to ask a question
• **Answering**: Time to answer a question
• **Dice Roll**: Time to roll the dice
• **Accept/Reject**: Time to accept/reject answer
• **Vote**: Time for voting on decisions

Changes are saved automatically and apply immediately."""

    await message.reply_text(
        text,
        reply_markup=get_timer_keyboard(settings),
        quote=True
    )


@Client.on_callback_query(filters.regex(r"^timer_"))
async def timer_callback_handler(client: Client, callback: CallbackQuery):
    """Handles all timer setting button callbacks."""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data = callback.data

    # Check if user is admin
    if not await is_admin(client, chat_id, user_id):
        await callback.answer("⚠️ Only admins can change settings.", show_alert=True)
        return

    # Handle close button
    if data == "timer_close":
        await callback.message.delete()
        return

    # Handle noop (clicking on the label)
    if data == "timer_noop":
        await callback.answer()
        return

    # Get current settings
    settings = get_group_settings(chat_id)
    if not settings:
        await callback.answer("❌ Error loading settings", show_alert=True)
        return

    # Handle reset button
    if data == "timer_reset":
        # Get defaults from environment
        defaults = {
            'asking_timeout': int(os.getenv("ASKING_TIMEOUT", "300")),
            'answering_timeout': int(os.getenv("ANSWERING_TIMEOUT", "300")),
            'dice_roll_timeout': int(os.getenv("DICE_ROLL_TIMEOUT", "60")),
            'accept_reject_timeout': int(os.getenv("ACCEPT_REJECT_TIMEOUT", "120")),
            'vote_timeout': int(os.getenv("VOTE_TIMEOUT", "30"))
        }

        # Update all settings
        for setting_name, value in defaults.items():
            update_group_setting(chat_id, setting_name, value)
            settings[setting_name] = value

        # Update running game if exists
        if chat_id in running_games:
            game = running_games[chat_id]
            game.timers.asking_timeout = defaults['asking_timeout']
            game.timers.answering_timeout = defaults['answering_timeout']
            game.timers.dice_roll_timeout = defaults['dice_roll_timeout']
            game.timers.accept_reject_timeout = defaults['accept_reject_timeout']
            game.timers.vote_timeout = defaults['vote_timeout']

        await callback.answer("✅ Reset to default timers!", show_alert=True)
        await callback.message.edit_reply_markup(get_timer_keyboard(settings))
        return

    # Parse timer adjustment
    parts = data.split("_")
    if len(parts) < 3:
        await callback.answer()
        return

    timer_type = parts[1]  # asking, answering, dice_roll, accept_reject, vote
    action = parts[2]  # inc or dec

    # Map to database column names
    column_map = {
        'asking': 'asking_timeout',
        'answering': 'answering_timeout',
        'dice': 'dice_roll_timeout',  # Handle "dice_roll" -> "dice"
        'accept': 'accept_reject_timeout',  # Handle "accept_reject" -> "accept"
        'vote': 'vote_timeout'
    }

    # For compound names like "dice_roll" and "accept_reject"
    if timer_type == "dice" and len(parts) == 4:  # timer_dice_roll_inc
        timer_type = "dice_roll"
        action = parts[3]
        column_name = "dice_roll_timeout"
        step_key = "dice_roll"
    elif timer_type == "accept" and len(parts) == 4:  # timer_accept_reject_inc
        timer_type = "accept_reject"
        action = parts[3]
        column_name = "accept_reject_timeout"
        step_key = "accept_reject"
    else:
        column_name = column_map.get(timer_type)
        step_key = timer_type

    if not column_name:
        await callback.answer("❌ Unknown timer type", show_alert=True)
        return

    current_value = settings.get(column_name, 60)
    steps = TIMER_STEPS.get(step_key, [30, 60, 120, 180, 300, 600])

    # Find current position in steps
    try:
        current_index = steps.index(current_value)
    except ValueError:
        # Current value not in steps, find nearest
        current_index = min(range(len(steps)), key=lambda i: abs(steps[i] - current_value))

    # Adjust value
    if action == "inc":
        new_index = min(current_index + 1, len(steps) - 1)
    elif action == "dec":
        new_index = max(current_index - 1, 0)
    else:
        await callback.answer()
        return

    new_value = steps[new_index]

    # Don't update if value hasn't changed
    if new_value == current_value:
        await callback.answer()
        return

    # Update database
    if update_group_setting(chat_id, column_name, new_value):
        settings[column_name] = new_value

        # Update running game if exists
        if chat_id in running_games:
            game = running_games[chat_id]
            if column_name == 'asking_timeout':
                game.timers.asking_timeout = new_value
            elif column_name == 'answering_timeout':
                game.timers.answering_timeout = new_value
            elif column_name == 'dice_roll_timeout':
                game.timers.dice_roll_timeout = new_value
            elif column_name == 'accept_reject_timeout':
                game.timers.accept_reject_timeout = new_value
            elif column_name == 'vote_timeout':
                game.timers.vote_timeout = new_value

        await callback.answer(f"✅ Updated to {format_time(new_value)}")
        await callback.message.edit_reply_markup(get_timer_keyboard(settings))
    else:
        await callback.answer("❌ Failed to update setting", show_alert=True)
