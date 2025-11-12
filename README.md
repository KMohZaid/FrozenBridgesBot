# 🌉 Frozen Bridges Bot

A Telegram bot for playing the **Frozen Bridges** game - a social deduction game where players ask secret questions and try to reveal or hide the truth through dice rolls!

## 🎮 How to Play

**Frozen Bridges** is a game about secrets, trust, and luck. Players take turns asking each other questions that can be answered with someone's name from the group. The answerer might tell the truth or lie - but a dice roll determines if the question gets revealed to everyone!

### Game Flow

1. **Taking Turns**: Each player takes turns asking questions
2. **Asking**: The current player picks someone and asks them a secret question (e.g., "Who would you trust with your biggest secret?")
3. **Answering**: The chosen player answers by selecting someone's name from the group
4. **Rating**: The questioner rates the difficulty (1-5 stars) - this gives points to the answerer
5. **Dice Roll**: Both players roll dice
   - **Questioner wins** (higher roll) → Question is revealed to everyone! 😱
   - **Answerer wins** (higher roll) → Question stays secret! 🤫
   - **Tie** → Roll again!
6. **Next Turn**: Game continues with the next player

### Voting System

Players can vote to:
- `/skipbridge` - Skip a player's turn (requires majority vote)
- `/endbridge` - End the current game (requires majority vote)

Voting happens in the background without blocking the game!

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Telegram API credentials from [my.telegram.org](https://my.telegram.org)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/FrozenBridgesBot.git
   cd FrozenBridgesBot
   ```

2. **Configure environment variables**
   ```bash
   cp example.env .env
   nano .env  # Edit with your credentials
   ```

3. **Start the bot**
   ```bash
   docker-compose up -d
   ```

4. **Check logs**
   ```bash
   docker-compose logs -f frozen_bridges_bot
   ```

## ⚙️ Configuration

All bot settings are in the `.env` file. See `example.env` for detailed descriptions.

### Key Settings

```env
# Telegram
BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_user_id

# Timers (in seconds)
ASKING_TIMEOUT=180      # 3 minutes to ask
ANSWERING_TIMEOUT=300   # 5 minutes to answer
VOTE_TIMEOUT=30         # 30 seconds for votes
```

## 📋 Commands

### Game Management
- `/startbridge` - Create a new game lobby
- `/joinbridge` - Join an ongoing game
- `/leavebridge` or `/enoughbridge` - Leave the current game
- `/endbridge` - Vote to end the game

### Gameplay
- `/skipbridge` - Vote to skip the current player's turn
- `/giveup` - Give up your turn (as questioner or answerer)

### Information
- `/guide` - Learn how to play
- `/help` - See all commands
- `/stats [@user]` - View game statistics
- `/playerlist` - Show current players
- `/bridgeplan` - See planned features

### Admin (Owner Only)
- `/kick @user` - Vote to kick a player
- `/commandlist` - View all available commands

## 🎲 Game Mechanics

### Scoring
- Answerers earn points based on question difficulty (1-5 stars)
- Points are tracked across all games
- View stats with `/stats`

### Timers
- **Asking**: 3 minutes to ask a question
- **Answering**: 5 minutes to answer
- **Rating**: 2 minutes to rate difficulty
- **Dice Rolling**: 1 minute to roll
- **Voting**: 30 seconds to vote

If time runs out, the turn is skipped automatically.

### Voting Rules
- Requires majority vote: `(Active Players / 2) + 1`
- Examples:
  - 2 players: 2 votes needed (100%)
  - 3 players: 2 votes needed (67%)
  - 4 players: 3 votes needed (75%)
  - 5 players: 3 votes needed (60%)

## 🏗️ Project Structure

```
FrozenBridgesBot/
├── bot/
│   ├── __main__.py          # Bot initialization
│   ├── game.py              # Game logic and state
│   ├── database.py          # PostgreSQL integration
│   ├── timers.py            # Timer management
│   └── plugins/
│       ├── admin.py         # Admin commands
│       ├── callback_handlers.py  # Button interactions
│       ├── game_flow.py     # Dice rolling and turn flow
│       ├── game_management.py    # Start/join/leave
│       ├── inline_handlers.py    # Inline query handling
│       ├── playerlist.py    # Player list display
│       ├── stats.py         # Statistics tracking
│       ├── utils.py         # Shared utilities
│       └── voting.py        # Voting system
├── docker-compose.yml       # Docker services
├── Dockerfile              # Bot container
├── .env                    # Configuration (not in repo)
├── example.env            # Configuration template
└── README.md              # This file
```

## 🔧 Development

### Running Locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up PostgreSQL database

3. Configure `.env` file

4. Run the bot:
   ```bash
   python -m bot
   ```

### Database

The bot uses PostgreSQL to store:
- Player statistics (questions asked, answers given, wins, etc.)
- Game state is kept in memory (not persistent across restarts)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🎯 Future Features

See `/bridgeplan` in the bot or check `PLANNING.md` for upcoming features:
- Game state persistence
- Question packs
- Achievements and leaderboards
- Custom taunts and messages
- And more!

## 💬 Support

For issues or questions:
- Open an issue on GitHub
- Contact the bot owner (set in `OWNER_ID`)

## 🙏 Acknowledgments

Built with:
- [Pyrogram](https://docs.pyrogram.org/) - Telegram MTProto API framework
- [PostgreSQL](https://www.postgresql.org/) - Database
- [Docker](https://www.docker.com/) - Containerization

---

**Have fun playing Frozen Bridges!** 🎲🌉
