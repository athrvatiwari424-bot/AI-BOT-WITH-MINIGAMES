import asyncio
from collections import deque
from datetime import datetime
from os import remove
from random import randint
import time

from discord import Embed, File, Forbidden, Member
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
from utils import *

# --- GIF CONFIGURATION ---
GIF_VIRAT = "https://media.discordapp.net/attachments/1034931132547997736/1123908766463700992/virat-kohli-king-kohli.gif"
GIF_CATCH_CHECK = "https://cdn.discordapp.com/attachments/994983976626311169/1441758819507240960/catch_drop_3.gif"
GIF_DROPPED = "https://media.discordapp.net/attachments/1437542136118644958/1437542186534043739/live-1762700491431-ezgif.com-video-to-gif-converter.gif"
GIF_FIFTY = "https://tenor.com/view/veda-veda-krishnamurthy-cricket-50-half-century-gif-21893373"

ACTIVE_CRICKET_LOBBIES = {}


# ==========================================
# SAMIR MISHRA'S CORE CRICKET GAME CLASSES
# ==========================================
class MultiplayerGame:

  def __init__(self, channel, bot):
    self.type = GameType.MULTI
    self.created_at = time.time()
    self.host = None
    self.game_id = randint(4444, 7777)
    self.innings = 0
    self.game_started = False
    self.shuffled = False
    self.bot_count = 0
    self.overs = 5
    self.channel = channel
    self.bot = bot
    self.result = None
    self.is_updating = False

    self.players: list = []
    self.TeamA: list = []
    self.TeamB: list = []

    self.toss_winner = None
    self.TeamA_turn = None
    self.curr_batsman = None
    self.curr_bowler = None
    self.batting_team = None
    self.bowling_team = None
    self.batting_team_stats = {}
    self.bowling_team_stats = {}
    self.team_settings = {'Team A name': 'Team A', 'Team B name': 'Team B'}
    self.players_queue = []
    self.debounce = False

  @classmethod
  def create(cls, channel, bot, host):
    new_game = cls(channel=channel, bot=bot)
    new_game.players.append(host)
    new_game.host = host.id
    return new_game


# --- TOSS SELECTION VIEW ---
class TossChoiceView(discord.ui.View):

  def __init__(self, winner: discord.Member, match_session):
    super().__init__(timeout=60)
    self.winner = winner
    self.match_session = match_session

  @discord.ui.button(
      label="Bat First 🏏",
      style=discord.ButtonStyle.primary,
      custom_id="choose_bat",
  )
  async def choose_bat(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if interaction.user != self.winner:
      return await interaction.response.send_message(
          "❌ Only the toss winner can make the choice!", ephemeral=True
      )

    winner_team = (
        "team_a"
        if self.winner in self.match_session["team_a"]
        else "team_b"
    )
    loser_team = "team_b" if winner_team == "team_a" else "team_a"

    self.match_session["batting_team"] = self.match_session[winner_team]
    self.match_session["bowling_team"] = self.match_session[loser_team]
    self.match_session["game_obj"].TeamA_turn = (
        "bat" if winner_team == "team_a" else "bowl"
    )

    for child in self.children:
      child.disabled = True
    await interaction.message.edit(view=self)

    await interaction.response.send_message(
        f"🪙 **{self.winner.display_name}** won the toss and elected to **BAT"
        f" FIRST**!\n🏏 **{self.match_session[winner_team + '_name']}** is"
        f" Batting | ⚾ **{self.match_session[loser_team + '_name']}** is"
        " Bowling."
    )
    self.match_session["toss_done"].set_result(True)

  @discord.ui.button(
      label="Bowl First ⚾",
      style=discord.ButtonStyle.danger,
      custom_id="choose_bowl",
  )
  async def choose_bowl(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if interaction.user != self.winner:
      return await interaction.response.send_message(
          "❌ Only the toss winner can make the choice!", ephemeral=True
      )

    winner_team = (
        "team_a"
        if self.winner in self.match_session["team_a"]
        else "team_b"
    )
    loser_team = "team_b" if winner_team == "team_a" else "team_a"

    self.match_session["batting_team"] = self.match_session[loser_team]
    self.match_session["bowling_team"] = self.match_session[winner_team]
    self.match_session["game_obj"].TeamA_turn = (
        "bowl" if winner_team == "team_a" else "bat"
    )

    for child in self.children:
      child.disabled = True
    await interaction.message.edit(view=self)

    await interaction.response.send_message(
        f"🪙 **{self.winner.display_name}** won the toss and elected to **BOWL"
        f" FIRST**!\n⚾ **{self.match_session[winner_team + '_name']}** is"
        f" Bowling | 🏏 **{self.match_session[loser_team + '_name']}** is"
        " Batting."
    )
    self.match_session["toss_done"].set_result(True)


# --- CRICKET LOBBY UI ---
class CricketLobbyView(discord.ui.View):

  def __init__(self, match_session):
    super().__init__(timeout=900)  # 15 minutes auto-disband
    self.match_session = match_session

  async def on_timeout(self):
    if not self.match_session["started"]:
      self.match_session["active"] = False
      try:
        await self.match_session["msg"].edit(
            content=(
                "⌛ **Cricket lobby expired and auto-disbanded after 15"
                " minutes of inactivity.**"
            ),
            embed=None,
            view=None,
        )
      except Exception:
        pass

  @discord.ui.button(
      label="Join Team A",
      style=discord.ButtonStyle.primary,
      custom_id="join_team_a",
  )
  async def join_a(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in self.match_session["team_b"]:
      self.match_session["team_b"].remove(user)
    if user not in self.match_session["team_a"]:
      self.match_session["team_a"].append(user)
      self.match_session["game_obj"].TeamA.append(user)
      await interaction.response.send_message(
          f"✅ {user.mention} joined **{self.match_session['team_a_name']}**!",
          ephemeral=True,
      )
      await self.match_session["update_embed"]()
    else:
      await interaction.response.send_message(
          "You are already in this team!", ephemeral=True
      )

  @discord.ui.button(
      label="Join Team B",
      style=discord.ButtonStyle.danger,
      custom_id="join_team_b",
  )
  async def join_b(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in self.match_session["team_a"]:
      self.match_session["team_a"].remove(user)
      self.match_session["game_obj"].TeamA.remove(user)
    if user not in self.match_session["team_b"]:
      self.match_session["team_b"].append(user)
      self.match_session["game_obj"].TeamB.append(user)
      await interaction.response.send_message(
          f"✅ {user.mention} joined **{self.match_session['team_b_name']}**!",
          ephemeral=True,
      )
      await self.match_session["update_embed"]()
    else:
      await interaction.response.send_message(
          "You are already in this team!", ephemeral=True
      )

  @discord.ui.button(
      label="Start Match 🚀",
      style=discord.ButtonStyle.success,
      custom_id="start_match",
  )
  async def start_match(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if interaction.user != self.match_session["host"]:
      return await interaction.response.send_message(
          "❌ Only the host can start the match!", ephemeral=True
      )
    if (
        len(self.match_session["team_a"]) == 0
        or len(self.match_session["team_b"]) == 0
    ):
      return await interaction.response.send_message(
          "❌ Both teams must have at least 1 player!", ephemeral=True
      )
    if len(self.match_session["team_a"]) != len(
        self.match_session["team_b"]
    ):
      return await interaction.response.send_message(
          "❌ Teams must have an equal number of players! Use `/addbot` to"
          " balance.",
          ephemeral=True,
      )

    self.match_session["started"] = True
    for child in self.children:
      child.disabled = True
    try:
      await interaction.message.edit(view=self)
    except Exception:
      pass
    await interaction.response.send_message(
        "🪙 **Starting Coin Toss Process...**"
    )
    self.match_session["future"].set_result(True)


# ==========================================
# DISCORD COG COMMANDS
# ==========================================
class Cricket(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @app_commands.command(
      name="cricket", description="Start a Hand Cricket match lobby!"
  )
  @app_commands.describe(
      overs="Number of overs",
      tournament_mode="Enable tournament mode (2 batters on pitch)?",
  )
  @app_commands.choices(
      tournament_mode=[
          app_commands.Choice(name="Yes", value="yes"),
          app_commands.Choice(name="No", value="no"),
      ]
  )
  async def cricket(
      self, interaction: discord.Interaction, overs: int, tournament_mode: str
  ):
    if interaction.channel.id in ACTIVE_CRICKET_LOBBIES:
      return await interaction.response.send_message(
          "❌ There is already an active cricket lobby in this channel!",
          ephemeral=True,
      )

    host = interaction.user
    game_obj = MultiplayerGame.create(interaction.channel, self.bot, host)
    game_obj.overs = overs

    match_session = {
        "host": host,
        "overs": overs,
        "tournament_mode": (tournament_mode == "yes"),
        "team_a_name": "Team A",
        "team_b_name": "Team B",
        "team_a": [host],
        "team_b": [],
        "started": False,
        "active": True,
        "game_obj": game_obj,
        "future": asyncio.get_running_loop().create_future(),
    }
    ACTIVE_CRICKET_LOBBIES[interaction.channel.id] = match_session

    embed = discord.Embed(title="🏏 Cricket Match LOBBY", color=discord.Color.gold())
    embed.add_field(name="Host", value=host.mention, inline=False)
    embed.add_field(name="Overs", value=str(overs), inline=True)
    embed.add_field(
        name="Tournament Mode",
        value="Yes (2 Batters)" if match_session["tournament_mode"] else "No",
        inline=True,
    )
    embed.add_field(name="Team A", value=host.display_name, inline=True)
    embed.add_field(name="Team B", value="Empty", inline=True)

    async def update_embed():
      embed.set_field_at(
          3,
          name=match_session["team_a_name"],
          value="\n".join([m.display_name for m in match_session["team_a"]])
          or "Empty",
          inline=True,
      )
      embed.set_field_at(
          4,
          name=match_session["team_b_name"],
          value="\n".join([m.display_name for m in match_session["team_b"]])
          or "Empty",
          inline=True,
      )
      try:
        await msg.edit(embed=embed)
      except Exception:
        pass

    match_session["update_embed"] = update_embed
    view = CricketLobbyView(match_session)

    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    match_session["msg"] = msg

    try:
      await asyncio.wait_for(match_session["future"], timeout=900)
      if match_session["started"]:
        match_session["toss_done"] = asyncio.get_running_loop().create_future()
        toss_winner = host
        coin_outcome = random.choice(["Heads 🪙", "Tails 🪙"])

        toss_embed = discord.Embed(
            title="🪙 THE COIN TOSS",
            description=(
                f"The coin is in the air...\n\nIt landed on:"
                f" **{coin_outcome}**!\n🎉 **{toss_winner.mention}** won the"
                " toss! Select your choice below:"
            ),
            color=discord.Color.gold(),
        )
        toss_view = TossChoiceView(toss_winner, match_session)
        await interaction.followup.send(embed=toss_embed, view=toss_view)

        await asyncio.wait_for(match_session["toss_done"], timeout=60)
        await interaction.followup.send(
            f"🚀 Match officially started! Secret DM inputs activated with a"
            f" **2-second cooldown**! {GIF_VIRAT}"
        )
    except asyncio.TimeoutError:
      pass
    finally:
      if interaction.channel.id in ACTIVE_CRICKET_LOBBIES:
        del ACTIVE_CRICKET_LOBBIES[interaction.channel.id]

  @app_commands.command(
      name="addbot", description="Add a bot player to a team in the lobby."
  )
  @app_commands.choices(
      team=[
          app_commands.Choice(name="Team A", value="a"),
          app_commands.Choice(name="Team B", value="b"),
      ]
  )
  async def addbot(self, interaction: discord.Interaction, team: str):
    lobby = ACTIVE_CRICKET_LOBBIES.get(interaction.channel.id)
    if not lobby or lobby["started"]:
      return await interaction.response.send_message(
          "❌ No active lobby in this channel!", ephemeral=True
      )
    if interaction.user != lobby["host"]:
      return await interaction.response.send_message(
          "❌ Only the host can add bots!", ephemeral=True
      )

    bot_name = f"Bot_{random.randint(100, 999)}"

    class DummyBot:

      def __init__(self, name):
        self.display_name = name
        self.name = name
        self.bot = True

      def __str__(self):
        return self.name

    dummy = DummyBot(bot_name)
    if team == "a":
      lobby["team_a"].append(dummy)
      lobby["game_obj"].TeamA.append(dummy)
    else:
      lobby["team_b"].append(dummy)
      lobby["game_obj"].TeamB.append(dummy)

    await interaction.response.send_message(
        f"🤖 Added **{bot_name}** to the lobby!", ephemeral=True
    )
    await lobby["update_embed"]()

  @app_commands.command(
      name="changeteamname", description="Change the name of a team in the lobby."
  )
  @app_commands.choices(
      team=[
          app_commands.Choice(name="Team A", value="a"),
          app_commands.Choice(name="Team B", value="b"),
      ]
  )
  async def changeteamname(
      self, interaction: discord.Interaction, team: str, new_name: str
  ):
    lobby = ACTIVE_CRICKET_LOBBIES.get(interaction.channel.id)
    if not lobby or lobby["started"]:
      return await interaction.response.send_message(
          "❌ No active lobby in this channel!", ephemeral=True
      )
    if interaction.user != lobby["host"]:
      return await interaction.response.send_message(
          "❌ Only the host can rename teams!", ephemeral=True
      )

    if team == "a":
      lobby["team_a_name"] = new_name
      lobby["game_obj"].team_settings["Team A name"] = new_name
    else:
      lobby["team_b_name"] = new_name
      lobby["game_obj"].team_settings["Team B name"] = new_name

    await interaction.response.send_message(
        f"✅ Team renamed to **{new_name}**!", ephemeral=True
    )
    await lobby["update_embed"]()

  @app_commands.command(
      name="shuffle", description="Randomly shuffle players between teams."
  )
  async def shuffle(self, interaction: discord.Interaction):
    lobby = ACTIVE_CRICKET_LOBBIES.get(interaction.channel.id)
    if not lobby or lobby["started"]:
      return await interaction.response.send_message(
          "❌ No active lobby in this channel!", ephemeral=True
      )
    if interaction.user != lobby["host"]:
      return await interaction.response.send_message(
          "❌ Only the host can shuffle teams!", ephemeral=True
      )

    all_players = lobby["team_a"] + lobby["team_b"]
    random.shuffle(all_players)
    mid = len(all_players) // 2
    lobby["team_a"] = all_players[:mid] or [all_players[0]]
    lobby["team_b"] = all_players[mid:] if mid > 0 else all_players[1:]
    lobby["game_obj"].TeamA = list(lobby["team_a"])
    lobby["game_obj"].TeamB = list(lobby["team_b"])

    await interaction.response.send_message(
        "🔀 Teams have been randomly shuffled!", ephemeral=True
    )
    await lobby["update_embed"]()

  @app_commands.command(
      name="stop", description="Stop and disband an active cricket match lobby."
  )
  async def stop(self, interaction: discord.Interaction):
    lobby = ACTIVE_CRICKET_LOBBIES.get(interaction.channel.id)
    if not lobby:
      return await interaction.response.send_message(
          "❌ No active lobby to stop in this channel!", ephemeral=True
      )
    if (
        interaction.user != lobby["host"]
        and not interaction.user.guild_permissions.manage_channels
    ):
      return await interaction.response.send_message(
          "❌ Only the host or staff can stop the lobby!", ephemeral=True
      )

    lobby["active"] = False
    if not lobby["started"]:
      lobby["future"].set_result(False)
    del ACTIVE_CRICKET_LOBBIES[interaction.channel.id]
    await interaction.response.send_message(
        "🛑 Cricket match lobby has been successfully stopped and disbanded."
    )


async def setup(bot):
  await bot.add_cog(Cricket(bot))
