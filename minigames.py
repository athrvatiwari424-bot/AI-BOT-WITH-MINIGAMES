import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands


# --- 1. TEAM HAND CRICKET ENGINE ---
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
        title="🏏 TEAM HAND CRICKET MATCH SETUP",
        description=(
            f"**Host:** {self.ctx.author.mention}\n"
            f"**Overs:** {self.overs} | **Players per Team:**"
            f" {self.players_per_team}\n\n"
            "React with 1️⃣ to join **TEAM A**\n"
            "React with 2️⃣ to join **TEAM B**"
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

    while (
        len(self.team_a) < self.players_per_team
        or len(self.team_b) < self.players_per_team
    ):
      try:
        reaction, user = await self.ctx.bot.wait_for(
            "reaction_add", timeout=30.0, check=check
        )
        self.init_player(user)
        if str(reaction.emoji) == "1️⃣" and user not in self.team_a:
          if len(self.team_a) < self.players_per_team:
            self.team_a.append(user)
            await self.ctx.send(f"✅ {user.mention} joined **TEAM A**")
        elif str(reaction.emoji) == "2️⃣" and user not in self.team_b:
          if len(self.team_b) < self.players_per_team:
            self.team_b.append(user)
            await self.ctx.send(f"✅ {user.mention} joined **TEAM B**")
      except asyncio.TimeoutError:
        while len(self.team_a) < self.players_per_team:
          bot_user = f"Bot{len(self.team_a)+1}"
          self.team_a.append(bot_user)
          self.init_player(bot_user)
        while len(self.team_b) < self.players_per_team:
          bot_user = f"Bot{len(self.team_b)+1}"
          self.team_b.append(bot_user)
          self.init_player(bot_user)
        break

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

    status_embed = discord.Embed(
        title=f"🏏 MATCH STATUS - {team_name} INNINGS",
        color=discord.Color.gold(),
    )
    status_msg = await self.ctx.send(embed=status_embed)

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

      if bat_move == bowl_move:
        self.wickets[team_name] += 1
        self.stats[current_bowler]["wickets"] += 1
        timeline.append("W")
        await self.ctx.send(
            f"🚨 **Batter Out!** {current_batter if isinstance(current_batter, str) else current_batter.mention} is OUT!"
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

      overs_str = f"{self.balls[team_name] // 6}.{self.balls[team_name] % 6}"
      rr = round(
          (self.scores[team_name] / (self.balls[team_name] / 6))
          if self.balls[team_name] > 0
          else 0,
          2,
      )

      embed = discord.Embed(
          title="Not Nuked Yet - Match Status", color=discord.Color.dark_purple()
      )
      embed.add_field(
          name="Innings",
          value="ONE" if team_name == "TEAM A" else "TWO",
          inline=True,
      )
      embed.add_field(
          name="Overs", value=f"{overs_str} / {self.overs}.0", inline=True
      )
      embed.add_field(
          name="Timeline", value=" | ".join(timeline[-10:]) if timeline else "None", inline=False
      )
      embed.add_field(
          name=f"{team_name}",
          value=f"{self.scores[team_name]}/{self.wickets[team_name]} ({overs_str} overs) (RR: {rr})",
          inline=False,
      )
      await status_msg.edit(embed=embed)

  async def get_move(self, player, role):
    if isinstance(player, str):
      return random.randint(1, 6)
    try:
      await player.send(f"🎮 **{role} Turn!** Send a number between `1` and `6`:")
      msg = await self.ctx.bot.wait_for(
          "message",
          timeout=20.0,
          check=lambda m: m.author == player
          and isinstance(m.channel, discord.DMChannel)
          and m.content.isdigit()
          and 1 <= int(m.content) <= 6,
      )
      return int(msg.content)
    except Exception:
      return random.randint(1, 6)

  async def send_result_card(self):
    if self.scores["TEAM B"] > self.scores["TEAM A"]:
      win_str = f"🎉 **TEAM B won by {self.scores['TEAM B'] - self.scores['TEAM A']} runs!**"
    elif self.scores["TEAM A"] > self.scores["TEAM B"]:
      win_str = f"🎉 **TEAM A won by {self.scores['TEAM A'] - self.scores['TEAM B']} runs!**"
    else:
      win_str = "🤝 **Match Tied!**"

    mvp = max(self.stats.keys(), key=lambda u: self.stats[u]["runs"] + (self.stats[u]["wickets"] * 20))
    mvp_name = mvp if isinstance(mvp, str) else mvp.display_name

    embed = discord.Embed(
        title="📋 Result Scorecard",
        description=f"### MATCH SUMMARY\n{win_str}\n\n**MVP:** {mvp_name}",
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
      return await interaction.response.send_message("Not your turn!", ephemeral=True)
    if view.board[self.y][self.x] != 0:
      return await interaction.response.send_message("Space taken!", ephemeral=True)

    view.board[self.y][self.x] = view.turn
    self.style = discord.ButtonStyle.success if view.turn == 1 else discord.ButtonStyle.danger
    self.label = "X" if view.turn == 1 else "O"
    self.disabled = True

    winner = view.check_winner()
    if winner is not None:
      for child in view.children:
        child.disabled = True
      content = "It's a tie!" if winner == 0 else f"🎉 {(view.player1 if winner == 1 else view.player2).mention} wins!"
      await interaction.response.edit_message(content=content, view=view)
      return view.stop()

    view.turn *= -1
    view.current_player = view.player1 if view.turn == 1 else view.player2
    await interaction.response.edit_message(
        content=f"Turn: {view.current_player.mention} ({'X' if view.turn == 1 else 'O'})", view=view
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
      if sum(r) == 3: return 1
      if sum(r) == -3: return -1
    for c in range(3):
      if self.board[0][c] + self.board[1][c] + self.board[2][c] == 3: return 1
      if self.board[0][c] + self.board[1][c] + self.board[2][c] == -3: return -1
    if self.board[0][0] + self.board[1][1] + self.board[2][2] == 3: return 1
    if self.board[0][0] + self.board[1][1] + self.board[2][2] == -3: return -1
    if self.board[0][2] + self.board[1][1] + self.board[2][0] == 3: return 1
    if self.board[0][2] + self.board[1][1] + self.board[2][0] == -3: return -1
    if all(cell != 0 for r in self.board for cell in r): return 0
    return None


# --- 3. MAIN COG ---
USER_BALANCES = {}


class Minigames(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  # Hand Cricket Prefix & Slash
  @commands.command(name="cricket", aliases=["hc"])
  async def cricket_prefix(self, ctx, overs: int = 2, pts: int = 2):
    game = TeamCricketGame(ctx, overs=overs, players_per_team=pts)
    await game.start_match()

  @app_commands.command(name="cricket", description="Play Team Hand Cricket")
  async def cricket_slash(self, interaction: discord.Interaction, overs: int = 2, pts: int = 2):
    await interaction.response.defer()
    class Wrapper:
      def __init__(self, i):
        self.author, self.bot, self.channel, self.interaction = i.user, i.client, i.channel, i
      async def send(self, *a, **kw):
        return await (self.interaction.followup.send(*a, **kw) if self.interaction.response.is_done() else self.interaction.response.send_message(*a, **kw))
    game = TeamCricketGame(Wrapper(interaction), overs=overs, players_per_team=pts)
    await game.start_match()

  # Tic-Tac-Toe
  @commands.command(name="tictactoe", aliases=["ttt"])
  async def tictactoe(self, ctx, member: discord.Member):
    if member == ctx.author or member.bot:
      return await ctx.send("Invalid opponent!")
    await ctx.send(f"🎮 Tic-Tac-Toe: {ctx.author.mention} vs {member.mention}", view=TicTacToeView(ctx.author, member))

  # OwO Economy Work & Balance
  @commands.command(name="work")
  async def work(self, ctx):
    earned = random.randint(100, 500)
    USER_BALANCES[ctx.author.id] = USER_BALANCES.get(ctx.author.id, 0) + earned
    await ctx.send(f"💼 {ctx.author.mention} went to work and earned **${earned}**!")

  @commands.command(name="bal", aliases=["balance"])
  async def balance(self, ctx, member: discord.Member = None):
    target = member or ctx.author
    await ctx.send(f"💰 **{target.display_name}'s Balance:** ${USER_BALANCES.get(target.id, 0):,}")

  # Word Guess
  @commands.command(name="wordguess", aliases=["gw"])
  async def wordguess(self, ctx):
    words = {"python": "Programming language", "minecraft": "Block sandbox game", "discord": "Chat app", "render": "Hosting platform"}
    word, hint = random.choice(list(words.items()))
    await ctx.send(f"🧩 **Guess the Word!** Scrambled: `{''.join(random.sample(word, len(word)))}` | Hint: {hint}")
    try:
      m = await self.bot.wait_for("message", timeout=30.0, check=lambda msg: msg.channel == ctx.channel and msg.content.lower() == word)
      await ctx.send(f"🎉 Correct, {m.author.mention}! It was **{word}**!")
    except asyncio.TimeoutError:
      await ctx.send(f"⏱️ Time's up! The word was **{word}**.")


async def setup(bot):
  await bot.add_cog(Minigames(bot))
