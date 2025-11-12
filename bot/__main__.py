import logging
import os
import pkgutil
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client

from . import database

# --- Basic Setup ---
# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
LOGGER = logging.getLogger(__name__)

# --- Environment Variables ---
# Ensure you have API_ID and API_HASH in your .env file or environment
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

bot = Client(
    "FrozenBridgesBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="bot/plugins"),
)

# In-memory storage for running games, keyed by chat_id
running_games = {}

# --- Command List Generation ---


def generate_command_list():
    """Generates the auto_generated_commands_list.txt file for BotFather."""
    commands = {
        "startbridge": "🎲 Create a new game",
        "joinbridge": "🤝 Join ongoing game",
        "leavebridge": "👋 Leave current game",
        "enoughbridge": "👋 Leave current game (alias)",
        "playerlist": "👥 See who's playing",
        "giveup": "🏳️ Give up your turn",
        "skipbridge": "⏭️ Vote to skip someone's turn",
        "endbridge": "🛑 Vote to end game",
        "votekick": "🗳️ Vote to kick a player",
        "stats": "📊 View your statistics",
        "mystats": "📊 View your statistics (alias)",
        "leaderboard": "🏆 View top players",
        "guide": "📖 Learn how to play",
        "help": "❓ Show all commands",
        "bridgeplan": "📝 See upcoming features",
        "del": "🗑️ Delete bot messages",
        "delete": "🗑️ Delete bot messages (alias)",
    }
    try:
        with open("auto_generated_commands_list.txt", "w") as f:
            for command, description in commands.items():
                f.write(f"{command} - {description}\n")
        LOGGER.info("Successfully generated auto_generated_commands_list.txt")
    except Exception as e:
        LOGGER.error(f"Failed to generate command list file: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    LOGGER.info("Starting Frozen Bridges Bot...")
    generate_command_list()
    database.init_db()
    # The bot will be started by Pyrogram's plugin loader
    LOGGER.info("Starting telegram bot...")
    bot.run()
    LOGGER.info("Bot stopped.")
