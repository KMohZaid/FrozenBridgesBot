import os
import re
from pyrogram import Client, filters
from pyrogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                            InlineQuery, InlineQueryResultArticle,
                            InputTextMessageContent)

from ..__main__ import running_games
from ..game import GameState
from .utils import is_user_in_any_active_game # Import the helper function
@Client.on_inline_query()
async def inline_query_handler(client: Client, query: InlineQuery):
    user_id = query.from_user.id
    original_query = query.query
    game = None
    chat_id = None
    action = None
    query_text = original_query # Default to full query if no prefix

    # --- Determine Game and Action from Query Prefix ---
    parts = original_query.split('|', 1)
    if len(parts) >= 1:
        action = parts[0].strip()
        query_text = parts[1].strip() if len(parts) == 2 else ""

        # Find the game where this player is participating
        # TODO: Add support for multiple games per player in the future
        for g in running_games.values():
            p = g.get_player(user_id)
            if p and p.is_active:
                game = g
                chat_id = g.chat_id
                break
    else:
        # If no prefix, game remains None, handled below
        pass

    if not game:
        return await query.answer(
            [],
            switch_pm_text="❌ You are not in any active game. Please use the buttons to start an action.",
            switch_pm_parameter="start",
            cache_time=1,
        )

    player = game.get_player(user_id)
    if not player:
         return await query.answer(
            [],
            switch_pm_text="❌ You are not a player in this game.",
            switch_pm_parameter="start",
            cache_time=1,
        )

    # --- Handle Actions ---

    # --- Action: Writing a question ---
    if action == "ask":
        if not (game.game_state == GameState.PLAYING and game.current_player and user_id == game.current_player.user_id):
            return await query.answer([], switch_pm_text="⛔ It's not your turn to ask a question!", switch_pm_parameter="start", cache_time=1)

        if not query_text:
            return await query.answer([], switch_pm_text="Type your question, then select a player to ask...", switch_pm_parameter="start", is_personal=True, cache_time=1)

        game.question = query_text
        results = []
        for p in game.players:
            if p.user_id != user_id and p.is_active:
                # Build full name using first and last name
                full_name = p.first_name
                if p.last_name:
                    full_name += f" {p.last_name}"

                input_content = InputTextMessageContent(
                    f"❓ I have a question for {p.mention}."
                )
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text="➡️ Send", callback_data=f"send_private_question|{chat_id}|{p.user_id}")]])

                results.append(InlineQueryResultArticle(id=str(p.user_id), title=f"Ask {full_name}", description=f"Your question: '{query_text}'", input_message_content=input_content, reply_markup=reply_markup))

        return await query.answer(results, cache_time=1, is_personal=True)

    # --- Action: Providing an answer ---
    elif action == "answer":
        if not (game.game_state == GameState.ANSWERING and game.answerer and user_id == game.answerer.user_id):
             return await query.answer([], switch_pm_text="⛔ It's not your turn to answer!", switch_pm_parameter="start", cache_time=1)

        # User can type any answer - questioner can reject if not a name
        if not query_text:
            return await query.answer([], switch_pm_text="💡 Type your answer (should be someone's name)!", switch_pm_parameter="start", is_personal=True, cache_time=1)

        # Store the answer
        game.answer = query_text

        input_content = InputTextMessageContent(
            f"**Answer by {game.answerer.mention}:**\n\n> {query_text}\n\n"
            f"{game.current_player.mention}, do you accept this answer?"
        )

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="👍 Accept", callback_data=f"accept_answer|{chat_id}"),
             InlineKeyboardButton(text="👎 Reject", callback_data=f"reject_answer|{chat_id}")]
        ])

        results = [
            InlineQueryResultArticle(
                id="answer_submit",
                title=f"Submit: {query_text}",
                description="Click to submit your answer",
                input_message_content=input_content,
                reply_markup=reply_markup
            )
        ]

        return await query.answer(results, cache_time=1, is_personal=True)

    # --- Fallback ---
    else:
        return await query.answer(
            [],
            switch_pm_text="⛔ It's not your turn to perform an action!",
            switch_pm_parameter="start",
            cache_time=1,
        )
