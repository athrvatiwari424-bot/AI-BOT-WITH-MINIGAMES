import random
import discord
from discord import app_commands
from discord.ext import commands


# --- ACTIVE MATCH STORAGE ---
ACTIVE_GAMES = {}


# --- SINGLEPLAYER GAME VIEW ---
class SingleCricketView(discord.ui.View):

  def __init__(self, player: discord.Member):
    super().__init__(timeout=60)
    self.player = player
    self.batsman_score = 0
    self.innings = 1  # 1 = User Batting, 2 = Bot Batting
    self.target = 0
    self.is_user_batting = True

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user.id != self.player.id:
      await interaction.response.send_message(
          "❌ This isn't your game! Start your own with `/cricket`.",
          ephemeral=True,
      )
      return False
    return True


class CricketChoiceButton(discord.ui.Button):

  def __init__(self, run_value: int):
    super().__init__(
        label=str(run_value), style=discord.ButtonStyle.blurple, emoji="🏏"
    )
    self.run_value = run_value

  async def callback(self, interaction: discord.Interaction):
    view: SingleCricketView = self.view
    bot_choice = random.randint(1, 6)
    user_choice = self.run_value

    if view.is_user_batting:
      if user_choice == bot_choice:
        # User is out!
        if view.innings == 1:
          view.target = view.batsman_score + 1
          view.innings = 2
          view.is_user_batting = False
          embed = discord.Embed(
              title="🏏 Hand Cricket - OUT!",
              description=(
                  f"You chose: **{user_choice}** | Bot chose:"
                  f" **{bot_choice}**\n💥 **You're Out!**\n\nYour Total Score:"
                  f" **{view.batsman_score}**\nTarget for Bot to win:"
                  f" **{view.target}**\n\n*Now it's your turn to bowl! Click"
                  " buttons to bowl.*"
              ),
              color=discord.Color.red(),
          )
          view.batsman_score = 0  # Reset for bot's batting score
          await interaction.response.edit_message(embed=embed, view=view)
        else:
          # Bot is out while chasing! User wins!
          embed = discord.Embed(
              title="🏆 YOU WIN THE MATCH!",
              description=(
                  f"You chose: **{user_choice}** | Bot chose:"
                  f" **{bot_choice}**\n💥 **Bot is Out!**\n\nBot scored:"
                  f" **{view.batsman_score}**\n🎯 Target was: **{view.target}**"
              ),
              color=discord.Color.gold(),
          )
          ACTIVE_GAMES.pop(interaction.channel.id, None)
          await interaction.response.edit_message(embed=embed, view=None)
      else:
        if view.innings == 1:
          view.batsman_score += user_choice
          embed = discord.Embed(
              title="🏏 Hand Cricket - Batting Innings",
              description=(
                  f"You chose: **{user_choice}** | Bot chose:"
                  f" **{bot_choice}**\n✨ You scored **{user_choice}**"
                  f" runs!\n\nYour Current Score: **{view.batsman_score}**"
              ),
              color=discord.Color.green(),
          )
          await interaction.response.edit_message(embed=embed, view=view)
        else:
          view.batsman_score += bot_choice  # Bot's runs
          if view.batsman_score >= view.target:
            embed = discord.Embed(
                title="💀 BOT WINS!",
                description=(
                    f"You bowled: **{user_choice}** | Bot hit:"
                    f" **{bot_choice}**\n\nBot chased down the target and won"
                    f" the match with **{view.batsman_score}** runs!"
                ),
                color=discord.Color.red(),
            )
            ACTIVE_GAMES.pop(interaction.channel.id, None)
            await interaction.response.edit_message(embed=embed, view=None)
          else:
            embed = discord.Embed(
                title="🏏 Hand Cricket - Bowling Innings",
                description=(
                    f"You bowled: **{user_choice}** | Bot hit:"
                    f" **{bot_choice}**\nBot scored **{bot_choice}**"
                    f" runs.\n\nBot Total: **{view.batsman_score}** / Target:"
                    f" **{view.target}**"
                ),
                color=discord.Color.orange(),
            )
            await interaction.response.edit_message(embed=embed, view=view)
    else:
      # User is bowling in innings 1, bot batted first (optional simplified flow)
      pass


# --- CRICKET COG ---
class Cricket(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name="cricket",
      description="Start a game of Hand Cricket against the bot!",
  )
  @app_commands.describe(mode="Choose game mode")
  @app_commands.choices(
      mode=[
          app_commands.Choice(name="Singleplayer vs Bot", value="single"),
      ]
  )
  async def cricket(self, interaction: discord.Interaction, mode: str = "single"):
    channel_id = interaction.channel.id
    if channel_id in ACTIVE_GAMES:
      await interaction.response.send_message(
          "❌ A cricket match is already active in this channel!", ephemeral=True
      )
      return

    if mode == "single":
      view = SingleCricketView(interaction.user)
      for i in range(1, 7):
        view.add_item(CricketChoiceButton(i))

      ACTIVE_GAMES[channel_id] = view

      embed = discord.Embed(
          title="🏏 Hand Cricket - Singleplayer Match",
          description=(
              f"Match started by {interaction.user.mention} against the"
              " Bot!\n\n**Innings 1: Batting**\nClick a button below to score"
              " runs!"
          ),
          color=discord.Color.blue(),
      )
      await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
  await bot.add_cog(Cricket(bot))
