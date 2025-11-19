from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

from .. import database
from ..__main__ import running_games
from ..game import Game, Player, GameState
from .utils import send_turn_start_message, end_game_logic, is_user_in_any_active_game
from .playerlist import playerlist_command # Import playerlist_command


def get_lobby_keyboard(chat_id: int):
    """Creates the inline keyboard for the lobby."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Join Game", callback_data=f"lobby_join|{chat_id}"),
                InlineKeyboardButton("❌ Leave Game", callback_data=f"lobby_leave|{chat_id}"),
            ],
            [InlineKeyboardButton("▶️ Start Game", callback_data=f"lobby_start|{chat_id}")],
        ]
    )


@Client.on_message(filters.command("startbridge") & filters.group)
async def start_bridge_command(client: Client, message: Message):
    """Starts a new game lobby."""
    chat_id = message.chat.id
    if chat_id in running_games:
        await message.reply_text("A game is already in progress or in a lobby in this chat!")
        return

    if await is_user_in_any_active_game(message.from_user.id):
        await message.reply_text("You are already in a game in a different group. Please finish that game first.", quote=True)
        return

    # Auto-create group settings if they don't exist
    settings = database.get_group_settings(chat_id)
    if not settings:
        database.create_group_settings(chat_id)

    # Detect topic thread if message is in a topic
    message_thread_id = getattr(message, 'message_thread_id', None)

    game = Game(chat_id, message_thread_id)
    running_games[chat_id] = game

    # Add the person who started the game
    player = Player(message.from_user)
    game.add_player(player)
    database.get_or_create_player(message.from_user.id, message.from_user.first_name)

    lobby_message = await message.reply_text(
        text=game.get_lobby_message(),
        reply_markup=get_lobby_keyboard(chat_id),
    )
    game.lobby_message_id = lobby_message.id


@Client.on_callback_query(filters.regex(r"^lobby_"))
async def handle_lobby_callbacks(client: Client, query: CallbackQuery):
    """Handles all callbacks related to the game lobby (join, leave, start)."""
    action, chat_id_str = query.data.split("|")
    chat_id = int(chat_id_str)

    game = running_games.get(chat_id)
    if not game or game.lobby_message_id != query.message.id:
        return await query.answer("This lobby is no longer active.", show_alert=True)

    user = query.from_user

    if action == "lobby_join":
        if game.get_player(user.id):
            return await query.answer("You are already in the lobby.", show_alert=True)
        
        if await is_user_in_any_active_game(user.id):
            return await query.answer("You are already in a game in a different group. Please finish that game first.", show_alert=True)
        
        player = Player(user)
        game.add_player(player)
        database.get_or_create_player(user.id, user.first_name)
        await query.answer("You have joined the lobby!")

    elif action == "lobby_leave":
        if not game.get_player(user.id):
            return await query.answer("You are not in the lobby.", show_alert=True)
            
        game.remove_player(user.id)
        await query.answer("You have left the lobby.")

    elif action == "lobby_start":
        if len(game.players) < 2:
            return await query.answer("Need at least 2 players to start!", show_alert=True)
        
        if not game.start_game():
             return await query.answer("Failed to start the game.", show_alert=True)

        # Game started successfully
        await query.message.delete()
        await send_turn_start_message(client, game)
        return # No need to update lobby message

    # Update the lobby message text
    try:
        await query.edit_message_text(
            text=game.get_lobby_message(),
            reply_markup=get_lobby_keyboard(chat_id),
        )
    except:
        pass # Ignore if message is not modified


@Client.on_message(filters.command("joinbridge") & filters.group)
async def joinbridge_command(client: Client, message: Message):
    """Allows a player to join an ongoing game or lobby."""
    chat_id = message.chat.id
    user = message.from_user
    game = running_games.get(chat_id)

    if not game:
        await message.reply_text("There is no game to join.")
        return

    # Check if user is active in ANOTHER game
    for g in running_games.values():
        if g.chat_id != chat_id:
            p = g.get_player(user.id)
            if p and p.is_active:
                await message.reply_text("You are already in a game in a different group. Please finish that game first.", quote=True)
                return

    player = game.get_player(user.id)

    if player:
        if player.is_active:
            await message.reply_text("You are already in the game.")
            return
        else: # Is inactive, so reactivate
            game.add_player(player)  # This properly reactivates and adds to queue
            await message.reply_text("You have rejoined the game!")
    else: # Not in game at all, so add
        new_player = Player(user)
        game.add_player(new_player)
        database.get_or_create_player(user.id, user.first_name)
        await message.reply_text("You have joined the game!")

    # Update lobby message if in WAITING state, otherwise show player list
    if game.game_state == GameState.WAITING:
        # Update the lobby message
        if game.lobby_message_id:
            try:
                await client.edit_message_text(
                    chat_id=chat_id,
                    message_id=game.lobby_message_id,
                    text=game.get_lobby_message(),
                    reply_markup=get_lobby_keyboard(chat_id),
                )
            except:
                pass  # Ignore if can't edit
    else:
        await playerlist_command(client, message)


@Client.on_message(filters.command(["leavebridge", "enoughbridge"]) & filters.group)
async def leave_command(client: Client, message: Message):
    """Allows a player to leave an ongoing game."""
    chat_id = message.chat.id
    game = running_games.get(chat_id)

    if not game:
        await message.reply_text("There is no active game to leave.")
        return

    player = game.get_player(message.from_user.id)

    if not player or not player.is_active:
        await message.reply_text("You are not currently in the game.")
        return

    # Store if they were current player before removing
    was_current_player = (game.current_player_id == player.user_id)

    # Use the new handle_player_leave method
    game.handle_player_leave(player.user_id)

    await message.reply_text(f"{player.mention} has left the game.")

    # Check if game should end
    if len(game.active_players) <= 1:
        await end_game_logic(client, chat_id, "The game has ended because only one player is left.")
        return

    # If the leaver was the current player, advance the turn
    if was_current_player:
        game.next_turn()
        await send_turn_start_message(client, game)
    else:
        # Update player list with timer info (turn is still ongoing)
        from .utils import send_player_list_with_ask_button
        from ..timers import GameTimers

        # Add timer info if game is in PLAYING state
        additional_text = ""
        if game.game_state == GameState.PLAYING and game.current_player:
            if not hasattr(game, 'timers'):
                game.timers = GameTimers(game.chat_id)
            asking_time = game.timers.asking_timeout
            time_display = f"{asking_time // 60} minute{'s' if asking_time >= 120 else ''}" if asking_time >= 60 else f"{asking_time} seconds"
            additional_text = f"⏱️ You have {time_display} to ask your question."

        await send_player_list_with_ask_button(client, game, additional_text)


@Client.on_message(filters.command("guide"))
async def guide_command(client: Client, message: Message):
    """Provides a simple guide on how to play the game."""
    guide_text = """**🌉 How to Play Frozen Bridges 🎲**

**The Concept:**
Ask secret questions that can be answered with someone's name from the group. Will the truth stay hidden or be revealed? Dice will decide!

**How It Works:**

1️⃣ **Your Turn**
   • Click "❓ Ask a Player" button
   • Pick who to ask & type your question
   • **Important:** Ask something answered with a NAME!
   • Example: "Who would you trust with your life?"

2️⃣ **They Answer**
   • They select someone's name from the group
   • They can be honest or lie - it's a secret!
   • Can request new question up to 3 times (🔄 button)

3️⃣ **You Rate It**
   • Rate difficulty: ⭐ (easy) to ⭐⭐⭐⭐⭐ (hard)
   • They get points based on your rating

4️⃣ **Dice Time!** 🎲
   • Both of you roll dice
   • **You roll higher** → Question revealed to all! 😱
   • **They roll higher** → Question stays secret! 🤫
   • **Tie** → Roll again!

5️⃣ **Next Player's Turn**

**Quick Tips:**
• Use /stats to see your score
• Use /skipbridge to vote skip someone
• Type /help for all commands

Good luck revealing secrets! 🎯"""
    await message.reply_text(guide_text, quote=True)


@Client.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Shows the help message with all commands."""
    help_text = """**🌉 Frozen Bridges Commands**

**🎮 Game Management:**
/startbridge - Create a new game lobby
/joinbridge - Join an ongoing game
/leavebridge - Leave current game (alias: /enoughbridge)
/playerlist - View all players & game status

**⚡ During Game:**
/giveup - Give up your turn (counted in stats)
/del or /delete - Delete bot messages (reply to message)
/choose option1, option2, ... - Randomly choose from a list
/alphabet - Get a random letter from A-Z

**🗳️ Voting:**
/skipbridge - Vote to skip someone's turn
/endbridge - Vote to end the game
/votekick @user - Vote to kick a player

**📊 Statistics:**
/stats - View your game statistics
/stats @user - View someone else's stats
/mystats - View your stats (alias)
/leaderboard - View top players

**📖 Info & Help:**
/guide - Learn how to play the game
/help - Show this command list
/bridgeplan - See planned features
/commandlist - See all available commands
/feedback <message> - Send feedback to bot owner

**🛡️ Admin Only:**
/adminskip - Skip a player's turn (reply/mention)
/adminkick - Kick a player from game (reply/mention)
/forcebridge - Force add player to game (reply to user)
/settimer - Interactive timer settings menu with reset

**💡 Tips:**
• Use inline buttons for easier gameplay
• Questions must be answerable with someone's NAME
• Answerer can request new question (up to 3 times)
• Be active or you'll be marked AFK!

Type /guide for detailed gameplay instructions! 🎲"""
    await message.reply_text(help_text, quote=True)


@Client.on_message(filters.command("bridgeplan"))
async def bridgeplan_command(client: Client, message: Message):
    """Shows the planned features for the bot."""
    plan_text = """📝 **Development Roadmap** 📝

✅ **Recently Implemented:**
• Interactive timer settings menu with +/- buttons
• Database-backed per-group timer configuration
• Timer controls (30s - 10min range)
• Admin instant skip/end (no vote needed)
• Game end statistics (scoreboard + duration)
• Non-blocking voting system
• Force-add players with /forcebridge

**🚧 Planned Features:**

**🔜 Next Update:**
• Max players per game configuration
• Player block/unblock system
• Auto-delete message settings
• Additional game mechanics settings
• Advanced timer warning options

**🔮 Future Plans:**
• Game state persistence (survive bot restarts)
• Achievements & badges system
• Question packs (themed question sets)
• Advanced statistics & leaderboards
• Multi-language support
• Custom game modes

**💡 Have ideas?** Use `/feedback <your suggestion>`!"""
    await message.reply_text(plan_text, quote=True)


@Client.on_message(filters.command("choose") & filters.group)
async def choose_command(client: Client, message: Message):
    """Randomly chooses one item from a comma-separated list."""
    import random

    # Split by space with maxsplit=1 to get command and arguments
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.reply_text(
            "Please provide a list of items separated by commas.\n\n"
            "**Usage:** /choose option1, option2, option3",
            quote=True
        )
        return

    # Get the argument portion
    arguments = parts[1]

    # Split by comma and filter out empty strings (after rstrip)
    items = [item.rstrip() for item in arguments.split(",")]
    items = [item for item in items if item]  # Filter out empty strings

    if not items:
        await message.reply_text(
            "No valid options found. Please provide items separated by commas.\n\n"
            "**Usage:** /choose option1, option2, option3",
            quote=True
        )
        return

    if len(items) == 1:
        await message.reply_text(
            f"Only one option provided!\n\n🎯 **Choice:** {items[0]}",
            quote=True
        )
        return

    # Choose a random item
    chosen = random.choice(items)

    await message.reply_text(
        f"🎲 **Options:** {len(items)}\n\n🎯 **I choose:** {chosen}",
        quote=True
    )


@Client.on_message(filters.command("alphabet") & filters.group)
async def alphabet_command(client: Client, message: Message):
    """Returns a random letter from the alphabet."""
    import random
    import string

    # Get a random uppercase letter
    random_letter = random.choice(string.ascii_uppercase)

    await message.reply_text(
        f"🔤 **Random Alphabet:** {random_letter}",
        quote=True
    )
