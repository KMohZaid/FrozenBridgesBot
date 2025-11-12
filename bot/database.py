import psycopg2
import psycopg2.pool
import logging
import os
from threading import Lock

LOGGER = logging.getLogger(__name__)

# Thread-safe connection pool
pool = None
pool_lock = Lock()

def get_db_connection():
    """Gets a connection from the pool."""
    global pool
    with pool_lock:
        if pool is None:
            try:
                pool = psycopg2.pool.SimpleConnectionPool(
                    1, 20,
                    user=os.getenv("POSTGRES_USER"),
                    password=os.getenv("POSTGRES_PASSWORD"),
                    host=os.getenv("DB_HOST"),
                    port=os.getenv("DB_PORT"),
                    database=os.getenv("POSTGRES_DB")
                )
                LOGGER.info("Database connection pool created successfully.")
            except psycopg2.OperationalError as e:
                LOGGER.error(f"Could not connect to database: {e}")
                return None
    return pool.getconn()

def put_db_connection(conn):
    """Returns a connection to the pool."""
    if pool:
        pool.putconn(conn)

def init_db():
    """Initializes the database and creates the players and group_settings tables if they don't exist."""
    conn = get_db_connection()
    if conn is None:
        LOGGER.error("Cannot initialize database, no connection available.")
        return

    try:
        with conn.cursor() as cur:
            # Create players table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    total_games_played INT DEFAULT 0,
                    total_questions_asked INT DEFAULT 0,
                    total_answers_given INT DEFAULT 0,
                    giveups_as_answerer INT DEFAULT 0,
                    giveups_as_questioner INT DEFAULT 0,
                    times_exposed INT DEFAULT 0,
                    times_lucky INT DEFAULT 0,
                    times_revealed_question INT DEFAULT 0,
                    times_failed_to_reveal INT DEFAULT 0
                );
            """)

            # Create group_settings table (timer settings only)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id BIGINT PRIMARY KEY,

                    -- Timer settings (in seconds)
                    asking_timeout INT DEFAULT 300,
                    answering_timeout INT DEFAULT 300,
                    dice_roll_timeout INT DEFAULT 60,
                    accept_reject_timeout INT DEFAULT 120,
                    vote_timeout INT DEFAULT 30,

                    -- Metadata
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create indexes for faster lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_settings_chat_id
                ON group_settings(chat_id);
            """)

            conn.commit()
            LOGGER.info("Database initialized. 'players' and 'group_settings' tables are ready.")
    except Exception as e:
        LOGGER.error(f"Error initializing database tables: {e}")
        conn.rollback()
    finally:
        put_db_connection(conn)

def get_player_stats(user_id: int):
    """Retrieves a player's stats from the database."""
    conn = get_db_connection()
    if conn is None: return None
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM players WHERE user_id = %s;", (user_id,))
            player = cur.fetchone()
            return player
    except Exception as e:
        LOGGER.error(f"Error in get_player_stats for user {user_id}: {e}")
        return None
    finally:
        put_db_connection(conn)

def get_or_create_player(user_id: int, username: str):
    """Retrieves a player from the DB or creates a new entry if they don't exist."""
    player = get_player_stats(user_id)
    if player:
        # Update username if it has changed
        if player[1] != username:
            conn = get_db_connection()
            if conn is None: return player
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE players SET username = %s WHERE user_id = %s;", (username, user_id))
                    conn.commit()
                    LOGGER.info(f"Updated username for user_id: {user_id}")
            except Exception as e:
                LOGGER.error(f"Error updating username for user {user_id}: {e}")
                conn.rollback()
            finally:
                put_db_connection(conn)
        return player

    # Player does not exist, create them
    conn = get_db_connection()
    if conn is None: return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO players (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;",
                (user_id, username)
            )
            conn.commit()
            LOGGER.info(f"Created new player entry for user_id: {user_id}")
            return get_player_stats(user_id)
    except Exception as e:
        LOGGER.error(f"Error creating player for user {user_id}: {e}")
        conn.rollback()
        return None
    finally:
        put_db_connection(conn)


def update_player_stat(user_id: int, stat_column: str, increment_by: int = 1):
    """
    Updates a specific stat for a player.

    :param user_id: The player's Telegram user ID.
    :param stat_column: The name of the column to update.
    :param increment_by: The value to increment the stat by.
    """
    conn = get_db_connection()
    if conn is None: return

    allowed_columns = [
        "total_games_played", "total_questions_asked", "total_answers_given",
        "giveups_as_answerer", "giveups_as_questioner", "times_exposed", "times_lucky",
        "times_revealed_question", "times_failed_to_reveal"
    ]
    if stat_column not in allowed_columns:
        LOGGER.error(f"Attempted to update a non-whitelisted column: {stat_column}")
        return

    try:
        with conn.cursor() as cur:
            from psycopg2 import sql
            query = sql.SQL("UPDATE players SET {col} = {col} + %s WHERE user_id = %s;").format(
                col=sql.Identifier(stat_column)
            )
            cur.execute(query, (increment_by, user_id))
            conn.commit()
            LOGGER.info(f"Updated stat '{stat_column}' for user {user_id} by {increment_by}.")
    except Exception as e:
        LOGGER.error(f"Error updating player stat for user {user_id}: {e}")
        conn.rollback()
    finally:
        put_db_connection(conn)


def get_group_settings(chat_id: int):
    """Retrieves group settings from the database. Returns None if not found."""
    conn = get_db_connection()
    if conn is None:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM group_settings WHERE chat_id = %s;", (chat_id,))
            result = cur.fetchone()
            if result:
                # Convert row to dictionary - must match SELECT * column order
                columns = [
                    'chat_id', 'asking_timeout', 'answering_timeout', 'dice_roll_timeout',
                    'accept_reject_timeout', 'vote_timeout', 'created_at', 'updated_at'
                ]
                return dict(zip(columns, result))
            return None
    except Exception as e:
        LOGGER.error(f"Error getting group settings for chat {chat_id}: {e}")
        return None
    finally:
        put_db_connection(conn)


def create_group_settings(chat_id: int):
    """Creates default group settings entry for a chat. Uses .env defaults."""
    conn = get_db_connection()
    if conn is None:
        return None

    # Get defaults from environment variables
    asking = int(os.getenv("ASKING_TIMEOUT", "300"))
    answering = int(os.getenv("ANSWERING_TIMEOUT", "300"))
    dice_roll = int(os.getenv("DICE_ROLL_TIMEOUT", "60"))
    accept_reject = int(os.getenv("ACCEPT_REJECT_TIMEOUT", "120"))
    vote = int(os.getenv("VOTE_TIMEOUT", "30"))

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO group_settings (
                    chat_id, asking_timeout, answering_timeout, dice_roll_timeout,
                    accept_reject_timeout, vote_timeout
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (chat_id) DO NOTHING
                RETURNING *;
            """, (chat_id, asking, answering, dice_roll, accept_reject, vote))
            result = cur.fetchone()
            conn.commit()
            LOGGER.info(f"Created group settings for chat {chat_id}")

            if result:
                columns = [
                    'chat_id', 'asking_timeout', 'answering_timeout', 'dice_roll_timeout',
                    'accept_reject_timeout', 'vote_timeout', 'created_at', 'updated_at'
                ]
                return dict(zip(columns, result))
            return get_group_settings(chat_id)
    except Exception as e:
        LOGGER.error(f"Error creating group settings for chat {chat_id}: {e}")
        conn.rollback()
        return None
    finally:
        put_db_connection(conn)


def update_group_setting(chat_id: int, setting_name: str, value):
    """Updates a specific group setting."""
    conn = get_db_connection()
    if conn is None:
        return False

    allowed_settings = [
        'asking_timeout', 'answering_timeout', 'dice_roll_timeout',
        'accept_reject_timeout', 'vote_timeout'
    ]

    if setting_name not in allowed_settings:
        LOGGER.error(f"Attempted to update non-whitelisted setting: {setting_name}")
        return False

    try:
        with conn.cursor() as cur:
            from psycopg2 import sql
            # Also update the updated_at timestamp
            query = sql.SQL(
                "UPDATE group_settings SET {col} = %s, updated_at = CURRENT_TIMESTAMP WHERE chat_id = %s;"
            ).format(col=sql.Identifier(setting_name))
            cur.execute(query, (value, chat_id))
            conn.commit()
            LOGGER.info(f"Updated setting '{setting_name}' to '{value}' for chat {chat_id}")
            return True
    except Exception as e:
        LOGGER.error(f"Error updating group setting for chat {chat_id}: {e}")
        conn.rollback()
        return False
    finally:
        put_db_connection(conn)
