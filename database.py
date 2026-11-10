import aiosqlite

DB_NAME = "cricket_game.db"


async def init_db():
  async with aiosqlite.connect(DB_NAME) as db:
    await db.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                matches_played INTEGER DEFAULT 0,
                matches_won INTEGER DEFAULT 0,
                runs_scored INTEGER DEFAULT 0,
                wickets_taken INTEGER DEFAULT 0,
                balls_faced INTEGER DEFAULT 0,
                balls_bowled INTEGER DEFAULT 0
            )
        """)
    await db.commit()


async def update_user_stats(
    user_id: int, runs: int, wickets: int, balls_faced: int, balls_bowled: int, won: bool
):
  async with aiosqlite.connect(DB_NAME) as db:
    await db.execute(
        """
            INSERT INTO user_stats (user_id, matches_played, matches_won, runs_scored, wickets_taken, balls_faced, balls_bowled)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                matches_played = matches_played + 1,
                matches_won = matches_won + ?,
                runs_scored = runs_scored + ?,
                wickets_taken = wickets_taken + ?,
                balls_faced = balls_faced + ?,
                balls_bowled = balls_bowled + ?
        """,
        (
            user_id,
            1 if won else 0,
            runs,
            wickets,
            balls_faced,
            balls_bowled,
            1 if won else 0,
            runs,
            wickets,
            balls_faced,
            balls_bowled,
        ),
    )
    await db.commit()


async def get_user_stats(user_id: int):
  async with aiosqlite.connect(DB_NAME) as db:
    async with db.execute(
        "SELECT matches_played, matches_won, runs_scored, wickets_taken, balls_faced, balls_bowled FROM user_stats WHERE user_id = ?",
        (user_id,),
    ) as cursor:
      return await cursor.fetchone()
