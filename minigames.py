import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands


# --- 1. TEAM HAND CRICKET ENGINE ---
class CricketButtons(discord.ui.View):

  def __init__(self, player):
    super().__init__(timeout=15)
    self.player = player
    self.value = None
    for i in range(1, 7):
      self.add_item(CricketNumberButton(i))

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user != self.player:
      await interaction.response.send_message(
          "This is not your turn to play!", ephemeral=True
      )
      return False
    return True


class CricketNumberButton(discord.ui.Button):

  def __init__(self, number):
    super().__init__(
        style=discord.ButtonStyle.primary,
        label=str(number),
        custom_id=f"cricket_{number}",
    )
    self.number = number

  async def callback(self, interaction: discord.Interaction):
    view: CricketButtons = self.view
    view.value = self.number
    await interaction.response.send_message(
        f"You chose **{self.number}**!", ephemeral=True
    )
    view.stop()


class TeamCricketGame:

  def __init__(self, ctx, overs=2, players_per_team=2):
    self.ctx = ctx
    self.overs = overs
    self.max_balls = overs * 6
    self.players_per_team = players_per_team
    self.team_a = []
    self.team_b = []
    self.scores = {"TEAM A": 0, "TEAM B": 0}
    self.wickets = {"TEAM A": 0, "TEAM B": 0}
    self.balls = {"TEAM A": 0, "TEAM B": 0}
    self.stats = {}
    # Dynamically grab your server name!
    self.server_name = ctx.guild.name if ctx.guild else "NOTTYAMERICA"

  def init_player(self, user):
    if user not in self.stats:
      self.stats[user] = {
          "runs": 0,
          "balls": 0,
          "wickets": 0,
          "runs_given": 0,
          "balls_bowled": 0,
      }

  async def start_match(self):
    self.team_a.append(self.ctx.author)
    self.init_player(self.ctx.author)

    embed = discord.Embed(
        title=f"🏏 {self.server_name} — TEAM HAND CRICKET MATCH SETUP",
        description=(
            f"**Host:** {self.ctx.author.mention}\n"
            f"**Overs:** {self.overs} | **Players per Team:**"
            f" {self.players_per_team}\n\n"
            "React with 1️⃣ to join **TEAM A**\n"
            "React with 2️⃣ to join **TEAM B**\n"
            "*Missing slots will automatically be filled with Bots!*"
        ),
        color=discord.Color.blue(),
    )
    msg = await self.ctx.send(embed=embed)
    await msg.add_reaction("1️⃣")
    await msg.add_reaction("2️⃣")

    def check(reaction, user):
      return (
          user != self.ctx.bot.user
          and str(reaction.emoji) in ["1️⃣", "2️⃣"]
          and reaction.message.id == msg.id
      )

    end_time = asyncio.get_event_loop().time() + 15.0
    while asyncio.get_event_loop().time() < end_time:
      try:
        remaining = end_time - asyncio.get_event_loop().time()
        reaction, user = await self.ctx.bot.wait_for(
            "reaction_add", timeout=max(0.5, remaining), check=check
        )
        self.init_player(user)
        if (
            str(reaction.emoji) == "1️⃣"
            and user not in self.team_a
            and user not in self.team_b
        ):
          if len(self.team_a) < self.players_per_team:
            self.team_a.append(user)
            await self.ctx.send(f"✅ {user.mention} joined **TEAM A**")
        elif (
            str(reaction.emoji) == "2️⃣"
            and user not in self.team_b
            and user not in self.team_a
        ):
          if len(self.team_b) < self.players_per_team:
            self.team_b.append(user)
            await self.ctx.send(f"✅ {user.mention} joined **TEAM B**")
      except asyncio.TimeoutError:
        break

    bot_counter = 1
    while len(self.team_a) < self.players_per_team:
      bot_name = f"Bot{bot_counter}"
      self.team_a.append(bot_name)
      self.init_player(bot_name)
      bot_counter += 1

    while len(self.team_b) < self.players_per_team:
      bot_name = f"Bot{bot_counter}"
      self.team_b.append(bot_name)
      self.init_player(bot_name)
      bot_counter += 1

    await self.ctx.send(
        "🚀 **Teams locked!**\n"
        f"**Team A:**"
        f" {', '.join([str(p if isinstance(p, str) else p.display_name) for p in self.team_a])}\n"
        f"**Team B:**"
        f" {', '.join([str(p if isinstance(p, str) else p.display_name) for p in self.team_b])}"
    )

    await self.play_innings("TEAM A", self.team_a, self.team_b, target=None)
    await self.play_innings(
        "TEAM B", self.team_b, self.team_a, target=self.scores["TEAM A"] + 1
    )
    await self.send_result_card()

  async def play_innings(
      self, team_name, batting_team, bowling_team, target=None
  ):
    timeline = []
    batter_idx = 0
    bowler_idx = 0
    current_batter = batting_team[batter_idx]
    current_bowler = bowling_team[bowler_idx]

    await self.ctx.send(f"🚨 **INNINGS START:** {team_name} is batting!")

    while (
        self.balls[team_name] < self.max_balls
        and self.wickets[team_name] < len(batting_team)
    ):
      if target and self.scores[team_name] >= target:
        break

      bat_move = await self.get_move(current_batter, "Batting")
      bowl_move = await self.get_move(current_bowler, "Bowling")

      self.balls[team_name] += 1
      self.stats[current_batter]["balls"] += 1
      self.stats[current_bowler]["balls_bowled"] += 1

      b_name = (
          current_batter
          if isinstance(current_batter, str)
          else current_batter.display_name
      )
      bl_name = (
          current_bowler
          if isinstance(current_bowler, str)
          else current_bowler.display_name
      )

      if bat_move == bowl_move:
        self.wickets[team_name] += 1
        self.stats[current_bowler]["wickets"] += 1
        timeline.append("W")
        await self.ctx.send(
            f"❌ **OUT!** {b_name} got out! Bowled/Caught by {bl_name}.\n"
            f"*(Batter: {bat_move} | Bowler: {bowl_move})*"
        )
        batter_idx += 1
        if batter_idx < len(batting_team):
          current_batter = batting_team[batter_idx]
      else:
        self.scores[team_name] += bat_move
        self.stats[current_batter]["runs"] += bat_move
        self.stats[current_bowler]["runs_given"] += bat_move
        timeline.append(str(bat_move))

      if self.balls[team_name] % 6 == 0:
        bowler_idx = (bowler_idx + 1) % len(bowling_team)
        current_bowler = bowling_team[bowler_idx]

      runs_left = (target - self.scores[team_name]) if target else "---"
      balls_left = self.max_balls - self.balls[team_name]
      wickets_left = len(batting_team) - self.wickets[team_name]

      embed = discord.Embed(
          title=f"{self.server_name} — {team_name} Innings",
          description=(
              f"**Score:** {self.scores[team_name]}/{self.wickets[team_name]}"
              f" ({self.balls[team_name]//6}.{self.balls[team_name]%6} overs)\n"
              f"**On Strike:** {b_name} ({self.stats[current_batter]['runs']} runs)"
              f"\n**Bowler:** {bl_name}\n\n"
              f"`Runs left: {runs_left} | Balls left: {balls_left} | Wickets"
              f" left: {wickets_left}`\n"
              f"**Timeline:** `{' '.join(timeline[-10:])}`"
          ),
          color=discord.Color.dark_purple(),
      )
      await self.ctx.send(embed=embed)

  async def get_move(self, player, role):
    if isinstance(player, str):
      await asyncio.sleep(1)
      return random.randint(1, 6)

    view = CricketButtons(player)
    msg = await self.ctx.send(
        f"🎮 {player.mention}, your **{role}** turn! Click a number (1-6):",
        view=view,
    )
    await view.wait()
    try:
      await msg.delete()
    except Exception:
      pass

    if view.value is None:
      return random.randint(1, 6)
    return view.value

  async def send_result_card(self):
    if self.scores["TEAM B"] > self.scores["TEAM A"]:
      win_str = (
          "🎉 **TEAM B won the game by"
          f" {self.scores['TEAM B'] - self.scores['TEAM A']} runs!**"
      )
    elif self.scores["TEAM A"] > self.scores["TEAM B"]:
      win_str = (
          "🎉 **TEAM A won the game by"
          f" {self.scores['TEAM A'] - self.scores['TEAM B']} runs!**"
      )
    else:
      win_str = "🤝 **Match Tied!**"

    mvp = max(
        self.stats.keys(),
        key=lambda u: self.stats[u]["runs"] + (self.stats[u]["wickets"] * 20),
    )
    mvp_name = mvp if isinstance(mvp, str) else mvp.display_name

    embed = discord.Embed(
        title=f"{self.server_name} — Result Scorecard",
        description=(
            f"### MATCH SUMMARY\n{win_str}\n\n**Most Valuable Player (MVP):**"
            f" {mvp_name}"
        ),
        color=discord.Color.green(),
    )
    await self.ctx.send(content=win_str, embed=embed)


# --- 2. TIC-TAC-TOE BUTTONS ---
class TicTacToeButton(discord.ui.Button):

  def __init__(self, x, y):
    super().__init__(style=discord.ButtonStyle.secondary, label="‎", row=y)
    self.x = x
    self.y = y

  async def callback(self, interaction: discord.Interaction):
    view = self.view
    if interaction.user != view.current_player:
      return await interaction.response.send_message(
          "Not your turn!", ephemeral=True
      )
    if view.board[self.y][self.x] != 0:
      return await interaction.response.send_message(
          "Space taken!", ephemeral=True
      )

    view.board[self.y][self.x] = view.turn
    self.style = (
        discord.ButtonStyle.success
        if view.turn == 1
        else discord.ButtonStyle.danger
    )
    self.label = "X" if view.turn == 1 else "O"
    self.disabled = True

    winner = view.check_winner()
    if winner is not None:
      for child in view.children:
        child.disabled = True
      content = (
          "It's a tie!"
          if winner == 0
          else (
              "🎉"
              f" {(view.player1 if winner == 1 else view.player2).mention} wins!"
          )
      )
      await interaction.response.edit_message(content=content, view=view)
      return view.stop()

    view.turn *= -1
    view.current_player = view.player1 if view.turn == 1 else view.player2
    await interaction.response.edit_message(
        content=(
            f"Turn: {view.current_player.mention} ({'X' if view.turn == 1 else 'O'})"
        ),
        view=view,
    )


class TicTacToeView(discord.ui.View):

  def __init__(self, p1, p2):
    super().__init__(timeout=60)
    self.player1 = p1
    self.player2 = p2
    self.current_player = p1
    self.turn = 1
    self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for y in range(3):
      for x in range(3):
        self.add_item(TicTacToeButton(x, y))

  def check_winner(self):
    for r in self.board:
      if sum(r) == 3:
        return 1
      if sum(r) == -3:
        return -1
    for c in range(3):
      if self.board[0][c] + self.board[1][c] + self.board[2][c] == 3:
        return 1
      if self.board[0][c] + self.board[1][c] + self.board[2][c] == -3:
        return -1
    if self.board[0][0] + self.board[1][1] + self.board[2][2] == 3:
      return 1
    if self.board[0][0] + self.board[1][1] + self.board[2][2] == -3:
      return -1
    if self.board[0][2] + self.board[1][1] + self.board[2][0] == 3:
      return 1
    if self.board[0][2] + self.board[1][1] + self.board[2][0] == -3:
      return -1
    if all(cell != 0 for r in self.board for cell in r):
      return 0
    return None


# --- 3. HYBRID COMMANDS COG ---
USER_BALANCES = {}


class Minigames(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  # 🏏 Hand Cricket (.cricket and /cricket)
  @commands.hybrid_command(
      name="cricket",
      description="Start a multi-player Team Hand Cricket match!",
  )
  @app_commands.describe(
      overs="Overs per match (default: 2)",
      players_per_team="Players per team (default: 2)",
  )
  async def cricket(
      self, ctx: commands.Context, overs: int = 2, players_per_team: int = 2
  ):
    game = TeamCricketGame(ctx, overs=overs, players_per_team=players_per_team)
    await game.start_match()

  # ❌⭕ Tic-Tac-Toe (.ttt and /ttt)
  @commands.hybrid_command(
      name="ttt", description="Play interactive Tic-Tac-Toe with a friend!"
  )
  @app_commands.describe(member="The member you want to challenge")
  async def ttt(self, ctx: commands.Context, member: discord.Member):
    if member == ctx.author or member.bot:
      return await ctx.send("You cannot play against yourself or a bot!")
    await ctx.send(
        f"🎮 **Tic-Tac-Toe:** {ctx.author.mention} vs {member.mention}",
        view=TicTacToeView(ctx.author, member),
    )

  # 💼 Work (.work and /work)
  @commands.hybrid_command(
      name="work", description="Earn virtual cash by working!"
  )
  async def work(self, ctx: commands.Context):
    earned = random.randint(100, 500)
    USER_BALANCES[ctx.author.id] = USER_BALANCES.get(ctx.author.id, 0) + earned
    await ctx.send(
        f"💼 {ctx.author.mention}, you worked hard and earned **${earned}**!"
    )

  # 💰 Balance (.bal and /bal)
  @commands.hybrid_command(
      name="bal", description="Check your virtual coin balance."
  )
  @app_commands.describe(member="Member whose balance you want to check")
  async def bal(
      self, ctx: commands.Context, member: discord.Member | None = None
  ):
    target = member or ctx.author
    await ctx.send(
        f"💰 **{target.display_name}'s Balance:**"
        f" ${USER_BALANCES.get(target.id, 0):,}"
    )

  # 🧩 Word Guess (.wordguess and /wordguess)
  @commands.hybrid_command(
      name="wordguess", description="Guess the scrambled word with a hint!"
  )
  async def wordguess(self, ctx: commands.Context):
    words = {
        "python": "Programming language",
        "minecraft": "Block sandbox game",
        "discord": "Chat app",
        "render": "Hosting platform",
    }
    word, hint = random.choice(list(words.items()))
    await ctx.send(
        "🧩 **Guess the Word!** Scrambled:"
        f" `{''.join(random.sample(word, len(word)))}` | Hint: {hint}"
    )
    try:
      m = await self.bot.wait_for(
          "message",
          timeout=30.0,
          check=lambda msg: msg.channel == ctx.channel
          and msg.content.lower() == word,
      )
      await ctx.send(f"🎉 Correct, {m.author.mention}! It was **{word}**!")
    except asyncio.TimeoutError:
      await ctx.send(f"⏱️ Time's up! The word was **{word}**.")


async def setup(bot):
  await bot.add_cog(Minigames(bot))
