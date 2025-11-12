import logging
import os
from functools import wraps

from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup)

from .. import database
from ..__main__ import running_games
from ..game import GameState, Player, VoteOutcome # Import VoteOutcome
from .game_flow import process_dice_rolls
from .utils import end_game_logic, skip_turn_logic, send_turn_start_message, is_user_in_any_active_game

LOGGER = logging.getLogger(__name__)


# --- Helper Functions & Decorators ---

def get_game_and_player(func):
    """Decorator to fetch game and player, handling common errors."""

    @wraps(func)
    async def wrapper(client: Client, query: CallbackQuery):
        user_id = query.from_user.id
        data = query.data
        if not data:
            return await query.answer("No data found in callback.", show_alert=True)

        parts = data.split("|")
        try:
            chat_id = int(parts[1])
        except (ValueError, IndexError):
            return await query.answer("Invalid callback data format.", show_alert=True)

        game = running_games.get(chat_id)
        if not game:
            return await query.answer("This game is no longer active.", show_alert=True)

        player = game.get_player(user_id)
        return await func(client, query, game, player, parts)

    return wrapper


def player_required(func):
    """Decorator to ensure the user is an active player."""

    @wraps(func)
    async def wrapper(client: Client, query: CallbackQuery, game, player, parts):
        if not player or not player.is_active:
            return await query.answer(
                "You are not an active player in this game. Use /join to participate.", show_alert=True
            )
        return await func(client, query, game, player, parts)

    return wrapper


def current_player_required(func):
    """Decorator to ensure the user is the current player."""

    @wraps(func)
    async def wrapper(client: Client, query: CallbackQuery, game, player, parts):
        if not game.current_player or player.user_id != game.current_player.user_id:
            return await query.answer(
                f"It's not your turn! It's currently {game.current_player.name}'s turn.", show_alert=True
            )
        return await func(client, query, game, player, parts)

    return wrapper


def answerer_required(func):
    """Decorator to ensure the user is the current answerer."""

    @wraps(func)
    async def wrapper(client: Client, query: CallbackQuery, game, player, parts):
        if not game.answerer or player.user_id != game.answerer.user_id:
            return await query.answer(
                f"This action is for {game.answerer.name}, not you.", show_alert=True
            )
        return await func(client, query, game, player, parts)

    return wrapper

@Client.on_callback_query(filters.regex(r"^join_game\|"))
@get_game_and_player
async def handle_join_game(client: Client, query: CallbackQuery, game, player, parts):
    """Handles a player joining the game via a button."""
    user = query.from_user

    if player and player.is_active:
        return await query.answer("You are already in the game.", show_alert=True)

    if await is_user_in_any_active_game(user.id):
        return await query.answer("You are already in a game in a different group. Please finish that game first.", show_alert=True)

    if player:  # Player exists and is inactive - reactivate them
        game.add_player(player)  # This properly reactivates and adds to queue
    else:  # New player
        player = Player(user)
        game.add_player(player)

    database.get_or_create_player(user.id, user.first_name)
    await query.answer("You have joined the game!")

    # Update player list with timer info (if game is ongoing)
    from .utils import send_player_list_with_ask_button
    from ..timers import GameTimers

    # Add timer info if game is in PLAYING state
    additional_text = ""
    if game.game_state == GameState.PLAYING and game.current_player:
        if not hasattr(game, 'timers'):
            game.timers = GameTimers()
        asking_time = game.timers.asking_timeout
        time_display = f"{asking_time // 60} minute{'s' if asking_time >= 120 else ''}" if asking_time >= 60 else f"{asking_time} seconds"
        additional_text = f"⏱️ You have {time_display} to ask your question."

    await send_player_list_with_ask_button(client, game, additional_text)


@Client.on_callback_query(filters.regex(r"^vote\|"))
@get_game_and_player
@player_required
async def handle_vote(client: Client, query: CallbackQuery, game, player, parts):
    """Handles a player's vote for skip or end with full transparency."""
    if not game.vote_type:
        return await query.answer("There is no active vote.", show_alert=True)

    vote = parts[2] == "yes"
    user_id = query.from_user.id

    if user_id in game.votes:
        return await query.answer("You have already voted.", show_alert=True)

    vote_outcome = game.add_vote(user_id, vote)

    if vote_outcome == VoteOutcome.PASSED:
        vote_type = game.vote_type
        target = game.vote_target
        game.reset_vote()
        await query.message.delete()

        if vote_type == "skip":
            # Use the target if specified, otherwise current player
            skipped_player = target if target else game.current_player
            if skipped_player:
                game.remove_player(skipped_player.user_id)
            await skip_turn_logic(client, game, f"🗳 Vote passed! {skipped_player.mention} has been skipped and is now inactive.")
        elif vote_type == "kick":
            # Permanently kick the target player
            if target:
                game.remove_player(target.user_id)
                # If it was current player or answerer, handle it
                if game.current_player_id == target.user_id:
                    game.clear_turn_state()
                    game.next_turn()
                    await send_turn_start_message(client, game)
                else:
                    await client.send_message(
                        game.chat_id,
                        f"🗳 Vote passed! {target.mention} has been kicked from the game."
                    )
        elif vote_type == "end":
            await end_game_logic(client, game.chat_id, "🗳 Vote passed! The game has ended.")
        return

    elif vote_outcome == VoteOutcome.FAILED_IMPOSSIBLE:
        vote_type = game.vote_type
        game.reset_vote()
        await query.message.delete()
        await client.send_message(
            chat_id=game.chat_id,
            text=f"🗳 Vote to {vote_type} failed! It's no longer possible to reach the required 'Yes' votes."
        )
        return

    # If vote_outcome is ONGOING, update the message with transparency
    from .voting import format_vote_message

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"✅ Yes", callback_data=f"vote|{game.chat_id}|yes"),
                InlineKeyboardButton(f"❌ No", callback_data=f"vote|{game.chat_id}|no"),
            ]
        ]
    )

    try:
        await query.edit_message_text(
            text=format_vote_message(game, game.vote_type),
            reply_markup=keyboard
        )
    except:
        pass  # Message may not have changed

    await query.answer(f"You voted {'Yes' if vote else 'No'}.")


@Client.on_callback_query(filters.regex(r"^send_private_question\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_send_private_question(client: Client, query: CallbackQuery, game, player, parts):
    try:
        answerer_id = int(parts[2])
    except (ValueError, IndexError):
        return await query.answer("Invalid player ID in callback.", show_alert=True)

    answerer = game.get_player(answerer_id)
    if not answerer:
        return await query.answer(
            "This player is no longer in the game.", show_alert=True
        )

    # The question is already stored in game.question from the inline handler.
    if not game.question:
        return await query.answer(
            "Could not find the question text. Please try asking again.", show_alert=True
        )

    game.answerer_id = answerer.user_id
    game.game_state = GameState.ANSWERING

    try:
        # "Delete" the original "I have a question for..." message by editing it
        if query.inline_message_id:
            await client.edit_inline_text(query.inline_message_id, "✅")
    except Exception as e:
        LOGGER.warning(f"Failed to edit inline message: {e}")

    # Check if answerer changed - if so, reset change request tracking
    if game.question_change_answerer_id is not None and game.question_change_answerer_id != answerer.user_id:
        # Different answerer, reset the counter
        game.question_change_requests_used = 0
        game.question_change_answerer_id = None

    # Set the answerer for change tracking if not set
    if game.question_change_answerer_id is None:
        game.question_change_answerer_id = answerer.user_id

    # Check if answerer can request question change
    import os
    max_changes = int(os.getenv("MAX_QUESTION_CHANGE_REQUESTS", "3"))
    can_change = game.question_change_requests_used < max_changes

    # Build keyboard
    keyboard_buttons = [
        [
            InlineKeyboardButton(
                "✍️ Provide Answer",
                switch_inline_query_current_chat="answer | ",
            ),
            InlineKeyboardButton(
                text="❓ Read Question",
                callback_data=f"read_question|{game.chat_id}",
            ),
        ]
    ]

    if can_change:
        keyboard_buttons.append([
            InlineKeyboardButton(
                f"🔄 Request New Question ({game.question_change_requests_used}/{max_changes})",
                callback_data=f"change_question|{game.chat_id}",
            )
        ])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    # Get timer duration
    from ..timers import GameTimers
    if not hasattr(game, 'timers'):
        game.timers = GameTimers()
    answering_time = game.timers.answering_timeout
    time_display = f"{answering_time // 60} minute{'s' if answering_time >= 120 else ''}" if answering_time >= 60 else f"{answering_time} seconds"

    message_text = (
        f"A question has been asked to {game.answerer.mention}!\n\n"
        f"💡 **Remember:** Answer with someone's NAME from the group!\n\n"
        f"Click the button below to provide your answer privately.\n\n"
        f"⏱️ You have {time_display} to answer."
    )

    answering_msg = await client.send_message(
        chat_id=game.chat_id,
        text=message_text,
        reply_markup=keyboard,
    )

    # Store the message ID for later updates
    game.answering_message_id = answering_msg.id

    # Start answering timer
    from ..timers import start_timer
    start_timer(game, "answering", client)





@Client.on_callback_query(filters.regex(r"^read_question\|"))
@get_game_and_player
@player_required
async def handle_read_question(client: Client, query: CallbackQuery, game, player, parts):
    user_id = query.from_user.id

    # Determine who is allowed to read the question based on game state
    allowed_to_read = False
    if game.game_state == GameState.ANSWERING:
        # Both the questioner and answerer can read it after it's sent
        if user_id in [game.answerer.user_id, game.current_player.user_id]:
            allowed_to_read = True

    if not allowed_to_read:
        return await query.answer("This question is not for you!", show_alert=True)

    if not game.question:
        return await query.answer("The question seems to be missing!", show_alert=True)

    await query.answer(
        f"The question from {game.current_player.name} is:\n\n{game.question}",
        show_alert=True,
        cache_time=300,
    )


@Client.on_callback_query(filters.regex(r"^change_question\|"))
@get_game_and_player
@player_required
@answerer_required
async def handle_change_question(client: Client, query: CallbackQuery, game, player, parts):
    """Handles answerer requesting a question change - sends request to questioner."""
    import os
    max_changes = int(os.getenv("MAX_QUESTION_CHANGE_REQUESTS", "3"))

    # Check if they can still request a change
    if game.question_change_requests_used >= max_changes:
        return await query.answer(
            f"You've already used all {max_changes} question change requests!",
            show_alert=True
        )

    # Check if answerer is the same as the one who made previous requests
    if game.question_change_answerer_id != game.answerer_id:
        return await query.answer(
            "Question change requests can only be made by the same answerer throughout the turn!",
            show_alert=True
        )

    # Create accept/reject keyboard for the questioner
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_question_change|{game.chat_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_question_change|{game.chat_id}"),
            ]
        ]
    )

    # Send notification to group with buttons for questioner
    await client.send_message(
        game.chat_id,
        f"🔄 {game.answerer.mention} has requested a new question!\n\n"
        f"📝 {game.current_player.mention}, do you accept this request?\n\n"
        f"**Note:** The request counts against the limit regardless of your decision.\n\n"
        f"Requests used: {game.question_change_requests_used}/{max_changes}",
        reply_markup=keyboard
    )

    await query.answer("Request sent! Waiting for questioner's decision...")


@Client.on_callback_query(filters.regex(r"^accept_question_change\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_accept_question_change(client: Client, query: CallbackQuery, game, player, parts):
    """Handles questioner accepting the question change request."""
    import os
    max_changes = int(os.getenv("MAX_QUESTION_CHANGE_REQUESTS", "3"))

    # Increment the counter (counts regardless of accept/reject)
    game.question_change_requests_used += 1
    remaining = max_changes - game.question_change_requests_used

    # Delete the request message
    await query.message.delete()

    # Notify the group
    await client.send_message(
        game.chat_id,
        f"✅ {game.current_player.mention} accepted the question change request!\n\n"
        f"📝 {game.current_player.mention}, please ask a different question to {game.answerer.mention}.\n\n"
        f"💡 **Reminder:** Ask something that can be answered with someone's NAME!\n\n"
        f"Remaining requests: {remaining}/{max_changes}"
    )

    # Reset the question and go back to asking state
    game.question = None
    game.answer = None
    game.game_state = GameState.PLAYING

    # Cancel answering timer and start asking timer
    if game.active_timer:
        try:
            game.active_timer.cancel()
        except:
            pass

    from .utils import send_turn_start_message
    await send_turn_start_message(client, game)


@Client.on_callback_query(filters.regex(r"^reject_question_change\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_reject_question_change(client: Client, query: CallbackQuery, game, player, parts):
    """Handles questioner rejecting the question change request."""
    import os
    max_changes = int(os.getenv("MAX_QUESTION_CHANGE_REQUESTS", "3"))

    # Increment the counter (counts regardless of accept/reject)
    game.question_change_requests_used += 1
    remaining = max_changes - game.question_change_requests_used

    # Delete the request message
    await query.message.delete()

    # Notify the group
    await client.send_message(
        game.chat_id,
        f"❌ {game.current_player.mention} rejected the question change request.\n\n"
        f"{game.answerer.mention} must answer the original question.\n\n"
        f"Remaining requests: {remaining}/{max_changes}"
    )

    # Update the answering message button with new counter
    if game.answering_message_id:
        can_change = game.question_change_requests_used < max_changes
        keyboard_buttons = [
            [
                InlineKeyboardButton(
                    "✍️ Provide Answer",
                    switch_inline_query_current_chat="answer | ",
                ),
                InlineKeyboardButton(
                    text="❓ Read Question",
                    callback_data=f"read_question|{game.chat_id}",
                ),
            ]
        ]

        if can_change:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    f"🔄 Request New Question ({game.question_change_requests_used}/{max_changes})",
                    callback_data=f"change_question|{game.chat_id}",
                )
            ])

        try:
            await client.edit_message_reply_markup(
                chat_id=game.chat_id,
                message_id=game.answering_message_id,
                reply_markup=InlineKeyboardMarkup(keyboard_buttons)
            )
        except Exception as e:
            LOGGER.warning(f"Failed to update answering message buttons: {e}")

    # Keep the game in ANSWERING state, answerer must continue
    await query.answer("Request rejected. Answerer must continue.")


@Client.on_callback_query(filters.regex(r"^accept_answer\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_accept_answer(client: Client, query: CallbackQuery, game, player, parts):
    # Get timer duration
    from ..timers import GameTimers
    if not hasattr(game, 'timers'):
        game.timers = GameTimers()
    rating_time = game.timers.accept_reject_timeout
    time_display = f"{rating_time // 60} minute{'s' if rating_time >= 120 else ''}" if rating_time >= 60 else f"{rating_time} seconds"

    # Show difficulty rating buttons
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⭐ (1pt)", callback_data=f"rate_difficulty|{game.chat_id}|1"),
                InlineKeyboardButton("⭐⭐ (2pts)", callback_data=f"rate_difficulty|{game.chat_id}|2"),
                InlineKeyboardButton("⭐⭐⭐ (3pts)", callback_data=f"rate_difficulty|{game.chat_id}|3"),
            ],
            [
                InlineKeyboardButton("⭐⭐⭐⭐ (4pts)", callback_data=f"rate_difficulty|{game.chat_id}|4"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐ (5pts)", callback_data=f"rate_difficulty|{game.chat_id}|5"),
            ]
        ]
    )
    await query.edit_message_text(
        f"✅ Answer accepted!\n\n"
        f"> {game.answer}\n\n"
        f"{game.current_player.mention}, rate the difficulty of your question:\n\n"
        f"⏱️ You have {time_display} to rate.",
        reply_markup=keyboard,
    )

    # Start accept/reject timer (now for difficulty rating)
    from ..timers import start_timer
    start_timer(game, "accept_reject", client)


@Client.on_callback_query(filters.regex(r"^rate_difficulty\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_rate_difficulty(client: Client, query: CallbackQuery, game, player, parts):
    """Handles difficulty rating and awards points."""
    try:
        difficulty = int(parts[2])
    except (ValueError, IndexError):
        return await query.answer("Invalid difficulty rating.", show_alert=True)

    if not 1 <= difficulty <= 5:
        return await query.answer("Difficulty must be between 1 and 5.", show_alert=True)

    # Award points based on difficulty
    if game.answerer:
        game.answerer.game_answer_count += difficulty

    # Get timer duration
    from ..timers import GameTimers
    if not hasattr(game, 'timers'):
        game.timers = GameTimers()
    dice_time = game.timers.dice_roll_timeout
    time_display = f"{dice_time // 60} minute{'s' if dice_time >= 120 else ''}" if dice_time >= 60 else f"{dice_time} seconds"

    # Now proceed to dice rolling
    game.game_state = GameState.ROLLING
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎲 Roll Dice",
                    switch_inline_query_current_chat=f"dice | {os.getenv('DICE_INLINE_DISPLAY_KEY', 'WAIFU_CUTE_DICE_ROLLER')}",
                )
            ]
        ]
    )

    stars = "⭐" * difficulty
    await query.edit_message_text(
        f"✅ Answer accepted! Difficulty: {stars} ({difficulty} {'point' if difficulty == 1 else 'points'})\n\n"
        f"> {game.answer}\n\n"
        f"🎉 {game.answerer.mention} earned {difficulty} {'point' if difficulty == 1 else 'points'}!\n\n"
        f"It's time to roll the dice. Both {game.current_player.mention} and {game.answerer.mention} must click the button below to roll.\n\n"
        f"⏱️ You have {time_display} to roll.",
        reply_markup=keyboard,
    )

    # Start dice roll timer
    from ..timers import start_timer
    start_timer(game, "dice_roll", client)


@Client.on_callback_query(filters.regex(r"^reject_answer\|"))
@get_game_and_player
@player_required
@current_player_required
async def handle_reject_answer(client: Client, query: CallbackQuery, game, player, parts):
    rejected_answer = game.answer
    game.answer = None
    game.game_state = GameState.ANSWERING
    await query.edit_message_text(
        f"❌ The following answer from {game.answerer.mention} was rejected:\n\n"
        f"> {rejected_answer}\n\n"
        f"{game.answerer.mention}, please provide a new answer."
    )





@Client.on_callback_query(filters.regex(r"^confirm_giveup\|"))
@get_game_and_player
@player_required
async def handle_confirm_giveup(client: Client, query: CallbackQuery, game, player, parts):
    user_id = query.from_user.id

    is_questioner = game.current_player and user_id == game.current_player.user_id
    is_answerer = game.answerer and user_id == game.answerer.user_id

    if not is_questioner and not is_answerer:
        return await query.answer("You are not in a position to give up right now.", show_alert=True)

    if is_questioner:
        LOGGER.info(f"User {user_id} is giving up as questioner. Updating stats.")
        database.update_player_stat(user_id, "giveups_as_questioner")
    elif is_answerer:
        LOGGER.info(f"User {user_id} is giving up as answerer. Updating stats.")
        database.update_player_stat(user_id, "giveups_as_answerer")

    await query.message.delete()
    await skip_turn_logic(
        client,
        game,
        f"🏳️ {query.from_user.mention} has given up their turn.",
    )


@Client.on_callback_query(filters.regex(r"^cancel_giveup\|"))
@get_game_and_player
@player_required
async def handle_cancel_giveup(client: Client, query: CallbackQuery, game, player, parts):
    user_id = query.from_user.id
    is_questioner = game.current_player and user_id == game.current_player.user_id
    is_answerer = game.answerer and user_id == game.answerer.user_id

    if not is_questioner and not is_answerer:
        return await query.answer("You are not in a position to cancel this.", show_alert=True)
        
    await query.message.delete()
    await query.answer("Give up cancelled. You can still play your turn.")