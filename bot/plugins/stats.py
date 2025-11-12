from pyrogram import Client, filters
from pyrogram.types import Message
from .. import database

def format_stats_message(stats_data):
    """Formats the raw database stats into a readable message."""
    (user_id, username, total_games, questions_asked, answers_given,
     giveups_as_answerer, giveups_as_questioner, exposed, lucky, revealed, failed_reveal) = stats_data

    total_giveups = giveups_as_answerer + giveups_as_questioner

    # Calculate win/loss ratios
    asker_luck = round(revealed / (revealed + failed_reveal) * 100) if (revealed + failed_reveal) > 0 else 0
    answerer_luck = round(lucky / (lucky + exposed) * 100) if (lucky + exposed) > 0 else 0

    return (
        f"📊 **Player Stats for {username}**\n\n"
        f"**--- Overall ---**\n"
        f"❓ Questions Asked: `{questions_asked}`\n"
        f"💬 Answers Given: `{answers_given}`\n"
        f"🏳️ Total Give Ups: `{total_giveups}`\n"
        f"   - As Questioner: `{giveups_as_questioner}`\n"
        f"   - As Answerer: `{giveups_as_answerer}`\n\n"
        f"**--- As Questioner ---**\n"
        f"✅ Questions Revealed: `{revealed}`\n"
        f"❌ Failed to Reveal: `{failed_reveal}`\n"
        f"🍀 Reveal Luck: `{asker_luck}%`\n\n"
        f"**--- As Answerer ---**\n"
        f"🤫 Kept Secret (Lucky): `{lucky}`\n"
        f"😳 Question Exposed: `{exposed}`\n"
        f"🍀 Survival Rate: `{answerer_luck}%`"
    )

@Client.on_message(filters.command("stats") & filters.group)
async def stats_command(client: Client, message: Message):
    """Shows player stats. Can be used in reply to another user."""
    target_user = message.from_user
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user

    stats = database.get_player_stats(target_user.id)

    if stats is None:
        await message.reply_text(
            "you never played this game in past how can you expect stats.",
            quote=True
        )
        return

    stats_message = format_stats_message(stats)
    await message.reply_text(stats_message, quote=True)


@Client.on_message(filters.command("mystats"))
async def mystats_command(client: Client, message: Message):
    """Shows your own detailed statistics."""
    user = message.from_user
    stats = database.get_player_stats(user.id)

    if stats is None:
        return await message.reply_text(
            "📊 **Your Statistics**\n\n"
            "You haven't played any games yet! Join a game to start building your stats.",
            quote=True
        )

    (user_id, username, total_games, questions_asked, answers_given,
     giveups_as_answerer, giveups_as_questioner, exposed, lucky, revealed, failed_reveal) = stats

    # Calculate statistics
    total_giveups = giveups_as_answerer + giveups_as_questioner
    total_questions_involved = revealed + failed_reveal
    reveal_rate = round(revealed / total_questions_involved * 100) if total_questions_involved > 0 else 0

    total_answers_involved = lucky + exposed
    survival_rate = round(lucky / total_answers_involved * 100) if total_answers_involved > 0 else 0

    stats_text = (
        f"📊 **Your Statistics**\n\n"
        f"🎮 Games Played: **{total_games}**\n\n"
        f"**As Questioner:**\n"
        f"❓ Questions Asked: **{questions_asked}**\n"
        f"✅ Revealed: **{revealed}** ({reveal_rate}%)\n"
        f"❌ Not Revealed: **{failed_reveal}**\n"
        f"🏳️ Give Ups: **{giveups_as_questioner}**\n\n"
        f"**As Answerer:**\n"
        f"💬 Answers Given: **{answers_given}**\n"
        f"🤫 Kept Secret: **{lucky}** ({survival_rate}%)\n"
        f"😳 Exposed: **{exposed}**\n"
        f"🏳️ Give Ups: **{giveups_as_answerer}**\n\n"
        f"**Overall Performance:**\n"
        f"🎯 Questions Success Rate: **{reveal_rate}%**\n"
        f"🛡️ Answer Survival Rate: **{survival_rate}%**\n"
        f"🏳️ Total Give Ups: **{total_giveups}**"
    )

    await message.reply_text(stats_text, quote=True)


@Client.on_message(filters.command("leaderboard"))
async def leaderboard_command(client: Client, message: Message):
    """Shows the top players by questions asked."""
    conn = database.get_db_connection()
    if conn is None:
        return await message.reply_text("❌ Database unavailable.")

    try:
        with conn.cursor() as cur:
            # Get top 10 players by total questions asked
            cur.execute("""
                SELECT username, total_questions_asked, total_answers_given,
                       total_games_played, times_revealed_question
                FROM players
                WHERE total_questions_asked > 0
                ORDER BY total_questions_asked DESC
                LIMIT 10;
            """)
            top_players = cur.fetchall()

            if not top_players:
                return await message.reply_text("📊 No players in leaderboard yet!")

            leaderboard_text = "🏆 **Global Leaderboard** 🏆\n\n"
            leaderboard_text += "Top players by questions asked:\n\n"

            medals = ["👑", "🥈", "🥉"]
            for i, player_data in enumerate(top_players, 1):
                username, questions, answers, games, revealed = player_data
                medal = medals[i-1] if i <= 3 else f"{i}."

                leaderboard_text += f"{medal} **{username}**\n"
                leaderboard_text += f"   ❓ {questions} questions | 💬 {answers} answers | 🎮 {games} games\n\n"

            # Get user's rank
            user_id = message.from_user.id
            cur.execute("""
                SELECT COUNT(*) + 1 as rank
                FROM players
                WHERE total_questions_asked > (
                    SELECT total_questions_asked FROM players WHERE user_id = %s
                );
            """, (user_id,))
            rank_result = cur.fetchone()
            user_rank = rank_result[0] if rank_result else "N/A"

            leaderboard_text += f"\n📍 **Your Rank:** #{user_rank}"

            await message.reply_text(leaderboard_text, quote=True)

    except Exception as e:
        await message.reply_text(f"❌ Error fetching leaderboard: {e}")
    finally:
        database.put_db_connection(conn)
