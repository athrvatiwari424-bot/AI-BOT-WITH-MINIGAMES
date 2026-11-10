import random
import discord
from discord import app_commands
from discord.ext import commands


# --- OWO ECONOMY & MINIGAMES COG ---
class MiniGames(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  # Helper to fetch or create user balance in database
  async def get_balance(self, user_id):
    async with self.bot.db.execute(
        "SELECT balance FROM economy WHERE user_id = ?;", (user_id,)
    ) as cursor:
      row = await cursor.fetchone()
      if row:
        return row[0]
      else:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO economy (user_id, balance, inventory) VALUES"
            " (?, 500, '[]');",
            (user_id,),
        )
        await self.bot.db.commit()
        return 500

  @app_commands.command(
      name="balance", description="Check your wallet and bank balance!"
  )
  async def balance(
      self, interaction: discord.Interaction, member: discord.Member = None
  ):
    target = member or interaction.user
    bal = await self.get_balance(target.id)

    embed = discord.Embed(
        title=f"💰 {target.display_name}'s Balance",
        description=f"**Wallet:** `{bal} Cowries`",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)

  @app_commands.command(
      name="work", description="Work hard to earn some OwO economy currency!"
  )
  @app_commands.cooldown(1, 30, commands.BucketType.user)
  async def work(self, interaction: discord.Interaction):
    earnings = random.randint(50, 250)
    current_bal = await self.get_balance(interaction.user.id)
    new_bal = current_bal + earnings

    await self.bot.db.execute(
        "UPDATE economy SET balance = ? WHERE user_id = ?;",
        (new_bal, interaction.user.id),
    )
    await self.bot.db.commit()

    jobs = [
        "You worked as a Discord Moderator and earned",
        "You coded a custom Discord bot and earned",
        "You hunted wild Pokémon and sold rare items for",
        "You streamed Minecraft on Twitch and received donations worth",
    ]
    job_text = random.choice(jobs)

    embed = discord.Embed(
        title="💼 Work Shift Complete!",
        description=(
            f"{job_text} **{earnings} Cowries**!\nNew Balance: **{new_bal}"
            " Cowries**"
        ),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed)

  @app_commands.command(
      name="tictactoe", description="Play a game of Tic-Tac-Toe with a friend!"
  )
  async def tictactoe(
      self, interaction: discord.Interaction, opponent: discord.Member
  ):
    if opponent.bot or opponent == interaction.user:
      return await interaction.response.send_message(
          "❌ You cannot play against yourself or a bot!", ephemeral=True
      )

    # Simple placeholder response for Tic-Tac-Toe initiation
    await interaction.response.send_message(
        f"🎮 Tic-Tac-Toe challenge sent from {interaction.user.mention} to"
        f" {opponent.mention}!"
    )

  @app_commands.command(
      name="guesstheword", description="Play a quick word guessing minigame!"
  )
  async def guesstheword(self, interaction: discord.Interaction):
    words = ["python", "discord", "cricket", "botnet", "server", "gaming"]
    secret = random.choice(words)
    hint = secret[0] + "_" * (len(secret) - 2) + secret[-1]

    embed = discord.Embed(
        title="🔠 Guess The Word!",
        description=(
            f"Guess the hidden word!\nHint: `{hint}`\n(Type your guess in chat!)"
        ),
        color=discord.Color.purple(),
    )
    await interaction.response.send_message(embed=embed)


async def setup(bot):
  await bot.add_cog(MiniGames(bot))
