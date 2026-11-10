import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

ACTIVE_LOBBIES = {}
USER_BALANCES = {}


# --- 1. TEAM HAND CRICKET ENGINE ---
class CricketSetupView(discord.ui.View):

  def __init__(self, game):
    super().__init__(timeout=60)
    self.game = game

  @discord.ui.button(
      label="Join Team A (1️⃣)", style=discord.ButtonStyle.primary
  )
  async def join_a(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in self.game.team_b:
      self.game.team_b.remove(user)
    if user not in self.game.team_a:
      self.game.team_a.append(user)
      self.game.init_player(user)
      await interaction.response.send_message(
          f"✅ {user.mention} joined **Team A**!", ephemeral=True
      )
    else:
      await interaction.response.send_message(
          "You are already in Team A!", ephemeral=True
      )

  @discord.ui.button(
      label="Join Team B (2️⃣)", style=discord.ButtonStyle.secondary
  )
  async def join_b(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in self.game.team_a:
      self.game.team_a.remove(user)
    if user not in self.game.team_b:
      self.game.team_b.append(user)
      self.game.init_player(user)
      await interaction.response.send_message(
          f"✅ {user.mention} joined **Team B**!", ephemeral=True
      )
    else:
      await interaction.response.send_message(
          "You are already in Team B!", ephemeral=True
      )


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
          "Not your turn!", ephemeral=True
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
    self.server_name = ctx.guild.name if ctx.guild else "NOTTYAMERICA"
    self.bot_counter = 1
    self.match_started = False
    self.gifs = [
        "https://media.giphy.com/media/l4FGpPki5v2Bcd6Ss/giphy.gif",
        "https://media.giphy.com/media/26ufc8n6KYsFpuzoA/giphy.gif",
        "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif",
        "https://media.giphy.com/media/3orieNwJHFXfO9q1y8/giphy.gif",
        "https://media.giphy.com/media/xT9IgusjhuL5TSGc8U/giphy.gif",
    ]

  def init_player(self, user):
    if user not in self.stats:
      self.stats[user] = {
          "runs": 0,
          "balls": 0,
          "wickets": 0,
          "runs_given": 0,
          "balls_bowled": 0,
      }

  def add_bot(self, team_side):
    bot_name = f"Bot{self.bot_counter}"
    self.bot_counter += 1
    self.init_player(bot_name)

    if team_side.lower() in ["a", "team_a", "teama"]:
      if len(self.team_a) < self.players_per_team:
        self.team_a.append(bot_name)
        return bot_name
    elif team_side.lower() in ["b", "team_b", "teamb"]:
      if len(self.team_b) < self.players_per_team:
        self.team_b.append(bot_name)
        return bot_name
    return None

  async def start_match(self):
    ACTIVE_LOBBIES[self.ctx.channel.id] = self
    self.team_a.append(self.ctx.author)
    self.init_player(self.ctx.author)

    view = CricketSetupView(self)
    embed = discord.Embed(
        title=f"🏏 {self.server_name} — TEAM HAND CRICKET LOBBY",
        description=(
            f"**Host:** {self.ctx.author.mention}\n"
            f"**Overs:** {self.overs} | **Players per Team:**"
            f" {self.players_per_team}\n\n"
            "Click the buttons below to join **Team A** or **Team B**.\n"
            "Host can manually add bots using `/addbot a` or `/addbot b`!\n\n"
            "*Match will start automatically when teams are full, or timeout in"
            " 60s.*"
        ),
        color=discord.Color.blue(),
    )
    embed.set_image(url=random.choice(self.gifs))
    msg = await self.ctx.send(embed=embed, view=view)

    while (
        len(self.team_a) < self.players_per_team
        or len(self.team_b) < self.players_per_team
    ):
      if self.match_started:
        break
      await asyncio.sleep(1)

    if self.ctx.channel.id in ACTIVE_LOBBIES:
      del ACTIVE_LOBBIES[self.ctx.channel.id]

    try:
      await msg.edit(view=None)
    except Exception:
      pass

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
      embed.set_image(url=random.choice(self.gifs))
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
    embed.set_image(
        url="https://media.giphy.com/media/26ufc8n6KYsFpuzoA/giphy.gif"
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


# --- 3. HYBRID COMMANDS COG (ECO, GAMES, STEAL, TESTS) ---
class Minigames(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  def get_balanced_percentage(self):
    if random.random() < 0.75:
      return random.randint(0, 100)
    else:
      return random.randint(101, 250)

  @commands.hybrid_command(
      name="cricket",
      description="Start a multi-player Team Hand Cricket match with real cricket GIFs!",
  )
  @app_commands.describe(
      overs="Overs per match (default: 2)",
      players_per_team="Players per team (default: 2)",
  )
  async def cricket(
      self, ctx: commands.Context, overs: int = 2, players_per_team: int = 2
  ):
    if ctx.channel.id in ACTIVE_LOBBIES:
      return await ctx.send(
          "A cricket match setup is already active in this channel!",
          ephemeral=True,
      )
    game = TeamCricketGame(ctx, overs=overs, players_per_team=players_per_team)
    await game.start_match()

  @commands.hybrid_command(
      name="addbot", description="Manually add a bot to Team A or Team B."
  )
  @app_commands.describe(team="Type 'a' for Team A or 'b' for Team B")
  @app_commands.choices(
      team=[
          app_commands.Choice(name="Team A", value="a"),
          app_commands.Choice(name="Team B", value="b"),
      ]
  )
  async def addbot(self, ctx: commands.Context, team: str):
    lobby = ACTIVE_LOBBIES.get(ctx.channel.id)
    if not lobby:
      return await ctx.send(
          "No active cricket match lobby in this channel! Start one with"
          " `/cricket`.",
          ephemeral=True,
      )

    bot_name = lobby.add_bot(team)
    if not bot_name:
      return await ctx.send(
          f"❌ Team {team.upper()} is already full!", ephemeral=True
      )

    await ctx.send(
        f"🤖 Added **{bot_name}** to **Team {team.upper()}**! (Team A:"
        f" {len(lobby.team_a)}/{lobby.players_per_team} | Team B:"
        f" {len(lobby.team_b)}/{lobby.players_per_team})"
    )

    if (
        len(lobby.team_a) >= lobby.players_per_team
        and len(lobby.team_b) >= lobby.players_per_team
    ):
      lobby.match_started = True

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

  @commands.hybrid_command(
      name="work", description="Work hard to earn virtual coins!"
  )
  async def work(self, ctx: commands.Context):
    earned = random.randint(150, 600)
    USER_BALANCES[ctx.author.id] = USER_BALANCES.get(ctx.author.id, 0) + earned
    jobs = [
        "coded a custom Discord bot",
        "streamed anime on Discord",
        "managed the server Discord support ticket system",
        "mined diamonds in Minecraft",
    ]
    embed = discord.Embed(
        title="💼 Work Shift Completed!",
        description=(
            f"{ctx.author.mention} went to work and **{random.choice(jobs)}**,"
            f" earning **${earned:,} coins**!"
        ),
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)

  @commands.hybrid_command(
      name="bal", description="Check your or another member's balance."
  )
  @app_commands.describe(member="Member whose balance you want to check")
  async def bal(
      self, ctx: commands.Context, member: discord.Member | None = None
  ):
    target = member or ctx.author
    coins = USER_BALANCES.get(target.id, 0)
    embed = discord.Embed(
        title=f"💰 {target.display_name}'s Wallet",
        description=f"**Current Balance:** `${coins:,} virtual coins`",
        color=discord.Color.green(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)

  @commands.hybrid_command(
      name="steal", description="Attempt to steal coins from another user!"
  )
  @app_commands.describe(member="The user you want to rob")
  async def steal(self, ctx: commands.Context, member: discord.Member):
    if member == ctx.author or member.bot:
      return await ctx.send(
          "You can't steal from yourself or bots!", ephemeral=True
      )

    author_bal = USER_BALANCES.get(ctx.author.id, 0)
    target_bal = USER_BALANCES.get(member.id, 0)

    if target_bal < 100:
      return await ctx.send(
          f"❌ {member.display_name} is too poor to rob! They have less than"
          " $100.",
          ephemeral=True,
      )

    success = random.choice([True, False, False])
    if success:
      stolen = random.randint(50, min(300, target_bal // 2))
      USER_BALANCES[member.id] -= stolen
      USER_BALANCES[ctx.author.id] = author_bal + stolen
      await ctx.send(
          f"🦹 **Success!** {ctx.author.mention} sneaked up on {member.mention}"
          f" and stole **${stolen:,} coins**!"
      )
    else:
      fine = random.randint(50, 200)
      USER_BALANCES[ctx.author.id] = max(0, author_bal - fine)
      USER_BALANCES[member.id] = target_bal + fine
      await ctx.send(
          f"🚨 **Busted!** {ctx.author.mention} got caught trying to rob"
          f" {member.mention} and had to pay a fine of **${fine:,} coins**!"
      )

  @commands.hybrid_command(
      name="wordguess", description="Guess the scrambled word with a hint!"
  )
  async def wordguess(self, ctx: commands.Context):
    words = {
        "python": "A popular programming language named after a snake",
        "minecraft": "A sandbox game built with blocks",
        "discord": "The app you are using right now",
        "render": "The platform where this bot is hosted 24/7",
        "cricket": "A popular bat-and-ball team sport",
    }
    word, hint = random.choice(list(words.items()))
    scrambled = "".join(random.sample(word, len(word)))

    embed = discord.Embed(
        title="🧩 Guess the Word!",
        description=(
            f"**Scrambled:** `{scrambled}`\n**Hint:** {hint}\n*Type the correct"
            " word in chat within 30 seconds!*"
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)

    try:
      m = await self.bot.wait_for(
          "message",
          timeout=30.0,
          check=lambda msg: msg.channel == ctx.channel
          and msg.content.lower() == word,
      )
      await ctx.send(
          f"🎉 Correct, {m.author.mention}! The secret word was **{word}**!"
      )
    except asyncio.TimeoutError:
      await ctx.send(
          f"⏱️ Time's up! Nobody guessed it. The word was **{word}**."
      )

  @commands.hybrid_command(
      name="gaytest", description="Calculates the gay percentage for a user."
  )
  @app_commands.describe(member="The member to test (defaults to you)")
  async def gaytest(
      self, ctx: commands.Context, member: discord.Member | None = None
  ):
    target = member or ctx.author
    pct = self.get_balanced_percentage()
    embed = discord.Embed(
        title="🌈 Gay Test Result",
        description=f"**{target.display_name}** is **{pct}%** gay!",
        color=discord.Color.magenta(),
    )
    await ctx.send(embed=embed)

  @commands.hybrid_command(
      name="lesbiantest", description="Calculates the lesbian percentage for a user."
  )
  @app_commands.describe(member="The member to test (defaults to you)")
  async def lesbiantest(
      self, ctx: commands.Context, member: discord.Member | None = None
  ):
    target = member or ctx.author
    pct = self.get_balanced_percentage()
    embed = discord.Embed(
        title="💜 Lesbian Test Result",
        description=f"**{target.display_name}** is **{pct}%** lesbian!",
        color=discord.Color.purple(),
    )
    await ctx.send(embed=embed)

  @commands.hybrid_command(
      name="baldtest", description="Calculates how bald a user is."
  )
  @app_commands.describe(member="The member to test (defaults to you)")
  async def baldtest(
      self, ctx: commands.Context, member: discord.Member | None = None
  ):
    target = member or ctx.author
    pct = self.get_balanced_percentage()
    embed = discord.Embed(
        title="🥚 Baldness Test Result",
        description=f"**{target.display_name}** is **{pct}%** bald!",
        color=discord.Color.light_gray(),
    )
    await ctx.send(embed=embed)


async def setup(bot):
  await bot.add_cog(Minigames(bot))
