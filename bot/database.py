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
    """Initializes the database and creates the players table if it doesn't exist."""
    conn = get_db_connection()
    if conn is None:
        LOGGER.error("Cannot initialize database, no connection available.")
        return
        
    try:
        with conn.cursor() as cur:
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
            conn.commit()
            LOGGER.info("Database initialized. 'players' table is ready.")
    except Exception as e:
        LOGGER.error(f"Error initializing database table: {e}")
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
