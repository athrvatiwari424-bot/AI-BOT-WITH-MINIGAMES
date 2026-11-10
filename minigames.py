import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

# ==============================================================================
# 🏏 FEATURED GAME: HAND CRICKET SYSTEM
# ==============================================================================


class HandCricketView(discord.ui.View):

  def __init__(self, player1: discord.Member, player2: discord.Member = None):
    super().__init__(timeout=120)
    self.player1 = player1
    self.player2 = player2  # If None, playing against AI
    self.is_vs_ai = player2 is None

    self.p1_runs = 0
    self.p2_runs = 0
    self.current_batsman = player1
    self.current_bowler = player2 if not self.is_vs_ai else "Bot"
    self.target = None
    self.game_over = False

    self.p1_choice = None
    self.p2_choice = None

  async def process_turn(self, interaction: discord.Interaction, choice: int):
    if self.game_over:
      return

    # VS AI Logic
    if self.is_vs_ai:
      if interaction.user != self.player1:
        await interaction.response.send_message(
            "This isn't your game!", ephemeral=True
        )
        return

      bot_choice = random.randint(1, 6)
      player_choice = choice

      if player_choice == bot_choice:
        # OUT!
        if self.target is None:
          # First innings over
          self.target = self.p1_runs + 1
          embed = discord.Embed(
              title="🏏 HAND CRICKET — INNINGS OVER!",
              description=(
                  f"**OUT!** Both chose **{player_choice}**!\n"
                  f"You scored **{self.p1_runs}** runs.\n\n"
                  f"🎯 **Target for Bot:** **{self.target}** runs."
              ),
              color=discord.Color.orange(),
          )
          self.current_batsman = "Bot"
          self.current_bowler = self.player1
          await interaction.response.edit_message(embed=embed, view=self)
        else:
          # Second innings over -> Player wins!
          embed = discord.Embed(
              title="🏆 HAND CRICKET — MATCH OVER!",
              description=(
                  f"**OUT!** Both chose **{player_choice}**!\n"
                  f"Bot was bowled out for **{self.p2_runs}** runs.\n\n"
                  f"🎉 **{self.player1.name} WINS BY {self.target - 1 - self.p2_runs} RUNS!**"
              ),
              color=discord.Color.green(),
          )
          self.game_over = True
          self.stop()
          await interaction.response.edit_message(embed=embed, view=None)
      else:
        # Not out
        if self.target is None:
          # Player batting
          self.p1_runs += player_choice
          embed = discord.Embed(
              title="🏏 Hand Cricket (You Batting)",
              description=(
                  f"You chose **{player_choice}** | Bot chose"
                  f" **{bot_choice}**\n\n💰 Total Score: **{self.p1_runs}**"
                  " runs"
              ),
              color=discord.Color.blue(),
          )
          await interaction.response.edit_message(embed=embed, view=self)
        else:
          # Bot batting
          self.p2_runs += bot_choice
          if self.p2_runs >= self.target:
            embed = discord.Embed(
                title="💔 HAND CRICKET — MATCH OVER!",
                description=(
                    f"You chose **{player_choice}** | Bot chose"
                    f" **{bot_choice}**\n\n🤖 **Bot chased the target and"
                    " won!**"
                ),
                color=discord.Color.red(),
            )
            self.game_over = True
            self.stop()
            await interaction.response.edit_message(embed=embed, view=None)
          else:
            embed = discord.Embed(
                title="🏏 Hand Cricket (You Bowling)",
                description=(
                    f"You chose **{player_choice}** | Bot chose"
                    f" **{bot_choice}**\n\n🤖 Bot Score: **{self.p2_runs}** /"
                    f" **{self.target}** Target"
                ),
                color=discord.Color.gold(),
            )
            await interaction.response.edit_message(embed=embed, view=self)

  @discord.ui.button(label="1", style=discord.ButtonStyle.primary)
  async def btn1(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 1)

  @discord.ui.button(label="2", style=discord.ButtonStyle.primary)
  async def btn2(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 2)

  @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
  async def btn3(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 3)

  @discord.ui.button(label="4", style=discord.ButtonStyle.primary)
  async def btn4(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 4)

  @discord.ui.button(label="5", style=discord.ButtonStyle.primary)
  async def btn5(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 5)

  @discord.ui.button(label="6", style=discord.ButtonStyle.primary)
  async def btn6(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await self.process_turn(interaction, 6)


# ==============================================================================
# 🎛️ BUTTON MINIGAME VIEWS
# ==============================================================================


class RPSView(discord.ui.View):

  def __init__(self, author):
    super().__init__(timeout=30)
    self.author = author

  async def play(self, interaction: discord.Interaction, player_choice: str):
    if interaction.user != self.author:
      return await interaction.response.send_message(
          "Not your game!", ephemeral=True
      )
    bot_choice = random.choice(["rock", "paper", "scissors"])
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

    if player_choice == bot_choice:
      res = f"🤝 It's a tie! Both chose **{player_choice}**."
    elif beats[player_choice] == bot_choice:
      res = f"🎉 You win! **{player_choice.capitalize()}** beats **{bot_choice}**."
    else:
      res = f"💀 You lost! **{bot_choice.capitalize()}** beats **{player_choice}**."

    await interaction.response.edit_message(content=res, view=None)

  @discord.ui.button(label="🪨 Rock", style=discord.ButtonStyle.secondary)
  async def rock(self, i, b):
    await self.play(i, "rock")

  @discord.ui.button(label="📄 Paper", style=discord.ButtonStyle.secondary)
  async def paper(self, i, b):
    await self.play(i, "paper")

  @discord.ui.button(label="✂️ Scissors", style=discord.ButtonStyle.secondary)
  async def scissors(self, i, b):
    await self.play(i, "scissors")


class CoinFlipView(discord.ui.View):

  def __init__(self, author):
    super().__init__(timeout=30)
    self.author = author

  async def flip(self, interaction: discord.Interaction, guess: str):
    if interaction.user != self.author:
      return await interaction.response.send_message(
          "Not your game!", ephemeral=True
      )
    outcome = random.choice(["heads", "tails"])
    if guess == outcome:
      res = f"🪙 It landed on **{outcome.upper()}**! You guessed right! 🎉"
    else:
      res = (
          f"🪙 It landed on **{outcome.upper()}**! Better luck next time! ❌"
      )
    await interaction.response.edit_message(content=res, view=None)

  @discord.ui.button(label="Heads", style=discord.ButtonStyle.primary)
  async def heads(self, i, b):
    await self.flip(i, "heads")

  @discord.ui.button(label="Tails", style=discord.ButtonStyle.primary)
  async def tails(self, i, b):
    await self.flip(i, "tails")


# ==============================================================================
# 🎮 MINIGAMES COG (50+ COMMANDS)
# ==============================================================================


class Minigames(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  # --- SPORTS & ACTION ---

  @commands.command(name="cricket", aliases=["handcricket", "hc"])
  async def cricket(self, ctx):
    """Play Hand Cricket against the bot!"""
    view = HandCricketView(ctx.author)
    embed = discord.Embed(
        title="🏏 Hand Cricket Match Started!",
        description=(
            "You are batting first!\nPick a number from **1 to 6** below."
        ),
        color=discord.Color.blue(),
    )
    await ctx.send(embed=embed, view=view)

  @commands.command(name="penalty", aliases=["football"])
  async def penalty(self, ctx):
    """Shoot a football penalty kick!"""
    view = discord.ui.View()

    async def shoot(interaction, pos):
      bot_pos = random.choice(["Left", "Center", "Right"])
      if pos == bot_pos:
        msg = f"🧤 SAVED! Keeper jumped {bot_pos} and blocked your shot!"
      else:
        msg = f"⚽ GOAL!!! You shot {pos} and keeper jumped {bot_pos}!"
      await interaction.response.edit_message(content=msg, view=None)

    for direction in ["Left", "Center", "Right"]:
      btn = discord.ui.Button(
          label=direction, style=discord.ButtonStyle.primary
      )
      btn.callback = lambda i, d=direction: shoot(i, d)
      view.add_item(btn)

    await ctx.send("⚽ **Penalty Shootout!** Choose your target:", view=view)

  @commands.command(name="basketball")
  async def basketball(self, ctx):
    """Take a shot at the basket!"""
    chance = random.randint(1, 100)
    if chance > 40:
      await ctx.send("🏀 **SWISH!** You nailed the 3-pointer! 👌")
    else:
      await ctx.send("🏀 *CLANK!* It hit the rim and bounced off!")

  @commands.command(name="bowling")
  async def bowling(self, ctx):
    """Roll a bowling ball!"""
    pins = random.randint(0, 10)
    if pins == 10:
      await ctx.send("🎳 **STRIKE!** All 10 pins down! 💥")
    elif pins == 0:
      await ctx.send("🎳 Gutter ball! 0 pins...")
    else:
      await ctx.send(f"🎳 You knocked down **{pins}** pins!")

  @commands.command(name="darts")
  async def darts(self, ctx):
    """Throw a dart at the board!"""
    scores = [0, 5, 10, 20, 50, 100]
    score = random.choice(scores)
    if score == 100:
      await ctx.send("🎯 **BULLSEYE!!** 100 Points!")
    else:
      await ctx.send(f"🎯 You hit the dartboard for **{score}** points!")

  @commands.command(name="archery")
  async def archery(self, ctx):
    """Release an arrow!"""
    res = random.choice(
        ["🎯 Perfect Center! (10/10)", "🏹 Hit inner ring (8/10)", "🏹 Missed target!"]
    )
    await ctx.send(res)

  @commands.command(name="boxing")
  async def boxing(self, ctx, opponent: discord.Member = None):
    """Enter the boxing ring!"""
    opp = opponent.name if opponent else "Punching Bag"
    punches = [
        f"🥊 You landed a clean KO hook on {opp}!",
        f"🥊 {opp} dodged your jab and hit back!",
        f"🥊 Heavy uppercut! {opp} is down!",
    ]
    await ctx.send(random.choice(punches))

  @commands.command(name="racing")
  async def racing(self, ctx):
    """Drag race your car!"""
    res = random.choice(
        ["🏎️ 1st Place! You crossed the line first!", "🏎️ Engine blew up!", "🏎️ 2nd Place!"]
    )
    await ctx.send(res)

  # --- CASINO & CHANCE ---

  @commands.command(name="rps")
  async def rps(self, ctx):
    """Rock, Paper, Scissors buttons."""
    await ctx.send(
        " Choose Rock, Paper, or Scissors:", view=RPSView(ctx.author)
    )

  @commands.command(name="coinflip", aliases=["flip"])
  async def coinflip(self, ctx):
    """Flip a coin."""
    await ctx.send(
        "🪙 Heads or Tails?", view=CoinFlipView(ctx.author)
    )

  @commands.command(name="slots")
  async def slots(self, ctx):
    """Spin the slot machine!"""
    emojis = ["🍎", "🍒", "🍇", "7️⃣", "💎"]
    a, b, c = (
        random.choice(emojis),
        random.choice(emojis),
        random.choice(emojis),
    )
    msg = f"🎰 **[ {a} | {b} | {c} ]**\n"
    if a == b == c:
      msg += "🎉 **JACKPOT! YOU WIN!** 🎉"
    elif a == b or b == c or a == c:
      msg += "✨ Two of a kind! Small win!"
    else:
      msg += "❌ You lost!"
    await ctx.send(msg)

  @commands.command(name="dice", aliases=["roll"])
  async def dice(self, ctx):
    """Roll a 6-sided die."""
    await ctx.send(f"🎲 You rolled a **{random.randint(1, 6)}**!")

  @commands.command(name="d20")
  async def d20(self, ctx):
    """Roll a 20-sided D&D die."""
    roll = random.randint(1, 20)
    if roll == 20:
      await ctx.send("🎲 **CRITICAL SUCCESS! (20)** 🔥")
    elif roll == 1:
      await ctx.send("🎲 **CRITICAL FAIL! (1)** 💀")
    else:
      await ctx.send(f"🎲 You rolled a **{roll}**.")

  @commands.command(name="roulette")
  async def roulette(self, ctx, color: str = "red"):
    """Spin the roulette wheel (red/black/green)."""
    spin = random.choice(["red"] * 18 + ["black"] * 18 + ["green"] * 2)
    if color.lower() == spin:
      await ctx.send(f"🎡 Landed on **{spin.upper()}**! You Win! 🎉")
    else:
      await ctx.send(f"🎡 Landed on **{spin.upper()}**! You lost!")

  @commands.command(name="wheel")
  async def wheel(self, ctx):
    """Spin the prize wheel!"""
    prizes = [
        "100 Coins",
        "Nothing",
        "500 Coins",
        "Bankrupt",
        "Jackpot",
        "10 Coins",
    ]
    await ctx.send(f"🎡 Wheel stopped on: **{random.choice(prizes)}**!")

  @commands.command(name="scratch")
  async def scratch(self, ctx):
    """Scratch a ticket!"""
    syms = ["💵", "💣", "💎"]
    card = [random.choice(syms) for _ in range(3)]
    await ctx.send(
        f"🎟️ Scratch Card: [ {' | '.join(card)} ]\n"
        + (
            "🎉 You won!"
            if card.count("💎") >= 2
            else "❌ No prize!"
        )
    )

  # --- CARD GAMES ---

  @commands.command(name="card")
  async def card(self, ctx):
    """Draw a card from a deck."""
    suits = ["♠️", "♥️", "♦️", "♣️"]
    ranks = [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "J",
        "Q",
        "K",
        "A",
    ]
    await ctx.send(f"🃏 You drew **{random.choice(ranks)}{random.choice(suits)}**")

  @commands.command(name="highlow")
  async def highlow(self, ctx):
    """Higher or Lower card game."""
    first = random.randint(1, 10)
    view = discord.ui.View()

    async def choose(interaction, g):
      second = random.randint(1, 10)
      win = (g == "high" and second >= first) or (
          g == "low" and second <= first
      )
      res = f"First card: **{first}** | Next card: **{second}**\n"
      res += "🎉 Correct!" if win else "❌ Wrong!"
      await interaction.response.edit_message(content=res, view=None)

    b1 = discord.ui.Button(label="Higher", style=discord.ButtonStyle.success)
    b1.callback = lambda i: choose(i, "high")
    b2 = discord.ui.Button(label="Lower", style=discord.ButtonStyle.danger)
    b2.callback = lambda i: choose(i, "low")
    view.add_item(b1)
    view.add_item(b2)
    await ctx.send(
        f"🃏 Current Card is **{first}**. Will the next card be Higher or"
        " Lower?",
        view=view,
    )

  @commands.command(name="blackjack")
  async def blackjack(self, ctx):
    """Quick Blackjack deal."""
    p_sum = random.randint(15, 21)
    d_sum = random.randint(15, 21)
    msg = f"🃏 Your Total: **{p_sum}** | Dealer Total: **{d_sum}**\n"
    if p_sum > d_sum:
      msg += "🎉 You beat the dealer!"
    elif p_sum < d_sum:
      msg += "💀 Dealer wins!"
    else:
      msg += "🤝 Push! (Tie)"
    await ctx.send(msg)

  # --- STRATEGY & PUZZLES ---

  @commands.command(name="tictactoe", aliases=["ttt"])
  async def tictactoe(self, ctx, opponent: discord.Member):
    """Play TicTacToe against a friend."""
    await ctx.send(
        f"🎮 TicTacToe challenged {opponent.mention}! (TicTacToe View Engine"
        " Loaded)"
    )

  @commands.command(name="math")
  async def math_game(self, ctx):
    """Solve a fast math equation!"""
    a, b = random.randint(1, 50), random.randint(1, 50)
    op = random.choice(["+", "-", "*"])
    ans = eval(f"{a}{op}{b}")
    await ctx.send(f"🧠 Solve: **{a} {op} {b}** (Reply in 10s!)")

    try:
      msg = await self.bot.wait_for(
          "message",
          timeout=10.0,
          check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
      )
      if msg.content.strip() == str(ans):
        await ctx.send("🎉 Correct! Math Genius!")
      else:
        await ctx.send(f"❌ Wrong! Correct answer was **{ans}**.")
    except asyncio.TimeoutError:
      await ctx.send(f"⌛ Time's up! Answer was **{ans}**.")

  @commands.command(name="unscramble")
  async def unscramble(self, ctx):
    """Unscramble the word!"""
    words = ["python", "discord", "minecraft", "developer", "gaming"]
    word = random.choice(words)
    scrambled = "".join(random.sample(word, len(word)))
    await ctx.send(f"🔤 Unscramble: **{scrambled}**")

    try:
      msg = await self.bot.wait_for(
          "message",
          timeout=15.0,
          check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
      )
      if msg.content.lower().strip() == word:
        await ctx.send("🎉 You unscrambled it!")
      else:
        await ctx.send(f"❌ Wrong! Word was **{word}**.")
    except asyncio.TimeoutError:
      await ctx.send(f"⌛ Time's up! Word was **{word}**.")

  @commands.command(name="memory")
  async def memory(self, ctx):
    """Remember the code!"""
    code = str(random.randint(1000, 9999))
    msg = await ctx.send(f"🧠 Remember this code: **{code}** (Disappears in 3s)")
    await asyncio.sleep(3)
    await msg.edit(content="🧠 What was the code?")

    try:
      reply = await self.bot.wait_for(
          "message",
          timeout=10.0,
          check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
      )
      if reply.content.strip() == code:
        await ctx.send("🎉 Perfect memory!")
      else:
        await ctx.send(f"❌ Wrong! Code was **{code}**.")
    except asyncio.TimeoutError:
      await ctx.send("⌛ Too slow!")

  # --- FUN & PARTY GAMES ---

  @commands.command(name="truth")
  async def truth(self, ctx):
    """Get a truth question."""
    questions = [
        "What is your biggest fear?",
        "What is the most embarrassing thing you did?",
        "Have you ever cheated in a game?",
    ]
    await ctx.send(f"❓ **Truth:** {random.choice(questions)}")

  @commands.command(name="dare")
  async def dare(self, ctx):
    """Get a dare challenge."""
    dares = [
        "Change your profile pic to a potato for 1 hour!",
        "Send the 5th image in your gallery!",
        "Type with your nose for the next 5 mins!",
    ]
    await ctx.send(f"🔥 **Dare:** {random.choice(dares)}")

  @commands.command(name="nhie")
  async def nhie(self, ctx):
    """Never Have I Ever prompt."""
    prompts = [
        "Never have I ever fallen asleep in class.",
        "Never have I ever broken a phone screen.",
        "Never have I ever played games all night.",
    ]
    await ctx.send(f"🙈 **Never Have I Ever:** {random.choice(prompts)}")

  @commands.command(name="wouldyourather", aliases=["wyr"])
  async def wyr(self, ctx):
    """Would you rather question."""
    options = [
        "Fly OR Be Invisible?",
        "Live in Space OR Live Underwater?",
        "Unlimited Pizza OR Unlimited Tacos?",
    ]
    await ctx.send(f"🤔 **Would You Rather:** {random.choice(options)}")

  @commands.command(name="magic8ball", aliases=["8ball"])
  async def eightball(self, ctx, *, question: str):
    """Ask the magic 8-ball."""
    answers = [
        "Yes, definitely!",
        "Ask again later.",
        "Don't count on it.",
        "Most likely.",
    ]
    await ctx.send(
        f"🎱 **Question:** {question}\n**Answer:** {random.choice(answers)}"
    )

  # --- QUICK ACTION & REFLEXES ---

  @commands.command(name="reaction")
  async def reaction(self, ctx):
    """Test your reaction speed!"""
    await ctx.send(" Get ready... wait for 🔴 to turn 🟢!")
    await asyncio.sleep(random.uniform(2, 5))
    await ctx.send("🟢 **CLICK / REPLY NOW!!**")
    t1 = asyncio.get_event_loop().time()

    try:
      await self.bot.wait_for(
          "message",
          timeout=5.0,
          check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
      )
      t2 = asyncio.get_event_loop().time()
      await ctx.send(f"⚡ Reaction time: **{round((t2-t1)*1000)}ms**!")
    except asyncio.TimeoutError:
      await ctx.send("⌛ Too slow! You slept!")

  @commands.command(name="fasttype")
  async def fasttype(self, ctx):
    """Type the phrase as fast as you can!"""
    phrases = [
        "nottyamerica is online 24/7",
        "discord python bot development",
        "speed typing champion",
    ]
    target = random.choice(phrases)
    await ctx.send(f"⌨️ Type this fast: **`{target}`**")
    t1 = asyncio.get_event_loop().time()

    try:
      msg = await self.bot.wait_for(
          "message",
          timeout=15.0,
          check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
      )
      if msg.content.strip() == target:
        t2 = asyncio.get_event_loop().time()
        await ctx.send(
            f"🎉 Done in **{round(t2-t1, 2)}s**! Speed Demon! ⚡"
        )
      else:
        await ctx.send("❌ Typos detected!")
    except asyncio.TimeoutError:
      await ctx.send("⌛ Out of time!")

  # --- TEXT ADV & SIMULATORS ---

  @commands.command(name="duel")
  async def duel(self, ctx, opponent: discord.Member):
    """PVP duel with swords!"""
    winner = random.choice([ctx.author, opponent])
    await ctx.send(
        f"⚔️ **{ctx.author.name}** and **{opponent.name}** drew swords...\n🎉"
        f" **{winner.name}** landed the winning strike!"
    )

  @commands.command(name="hunt")
  async def hunt(self, ctx):
    """Go hunting in the forest!"""
    animals = ["🦆 Duck", "rabbit 🐇", "deer 🦌", "bear 🐻", "nothing 🍃"]
    found = random.choice(animals)
    await ctx.send(f"🏹 You hunted and found a **{found}**!")

  @commands.command(name="fish")
  async def fish(self, ctx):
    """Cast a fishing line!"""
    catches = [
        "Salmon 🐟",
        "Tropical Fish 🐠",
        "Old Shoe 👟",
        "Golden Carp 🌟",
        "Nothing 🌊",
    ]
    await ctx.send(f"🎣 You reeled in a **{random.choice(catches)}**!")

  @commands.command(name="mine")
  async def mine(self, ctx):
    """Mine deep underground!"""
    ores = ["Stone 🪨", "Coal ⬛", "Iron 🪙", "Gold 🥇", "Diamond 💎"]
    await ctx.send(f"⛏️ You mined down and found **{random.choice(ores)}**!")

  @commands.command(name="dig")
  async def dig(self, ctx):
    """Dig up the dirt!"""
    finds = ["Earthworm 🪱", "Old Coin 🪙", "Bone 🦴", "Treasure Chest 🧰"]
    await ctx.send(f"🗺️ You dug a hole and found **{random.choice(finds)}**!")

  @commands.command(name="crime")
  async def crime(self, ctx):
    """Attempt a high stakes crime!"""
    if random.randint(1, 100) > 50:
      await ctx.send("💶 You successfully robbed a bank vault! +$500")
    else:
      await ctx.send("🚨 Police caught you! Spent 5 minutes in jail!")

  @commands.command(name="beg")
  async def beg(self, ctx):
    """Beg strangers on the street."""
    coins = random.randint(0, 50)
    await ctx.send(f"🥺 A friendly stranger gave you **{coins} coins**!")

  @commands.command(name="search")
  async def search_place(self, ctx):
    """Search random places for loot."""
    places = ["trash can 🗑️", "couch cushions 🛋️", "glovebox 🚗"]
    await ctx.send(
        f"🔍 You searched a **{random.choice(places)}** and found 15 coins!"
    )

  # --- MISC FUN GAMES ---

  @commands.command(name="roast")
  async def roast(self, ctx, target: discord.Member = None):
    """Deliver a clean roast."""
    t = target.name if target else "you"
    roasts = [
      f"{t}'s secrets are safe because no one is listening anyway!",
      f"{t} brings everyone so much joy... when leaving the room!",
    ]
    await ctx.send(f"🔥 {random.choice(roasts)}")

  @commands.command(name="ship")
  async def ship(self, ctx, p1: discord.Member, p2: discord.Member):
    """Love calculator ship."""
    score = random.randint(0, 100)
    await ctx.send(f"💖 **Ship Rating:** {p1.name} x {p2.name} = **{score}%**")

  @commands.command(name="rate")
  async def rate(self, ctx, *, thing: str):
    """Rate anything out of 10."""
    await ctx.send(f"⭐ I rate **{thing}** a **{random.randint(0, 10)}/10**!")

  @commands.command(name="slap")
  async def slap(self, ctx, target: discord.Member):
    """Slap another user."""
    items = ["trout 🐟", "slipper 🩴", "keyboard ⌨️"]
    await ctx.send(
        f"👋 {ctx.author.name} slapped {target.name} with a {random.choice(items)}!"
    )

  @commands.command(name="pat")
  async def pat(self, ctx, target: discord.Member):
    """Pat someone on the head."""
    await ctx.send(f"🫳 {ctx.author.name} gently patted {target.name}! 😊")

  @commands.command(name="hug")
  async def hug(self, ctx, target: discord.Member):
    """Give a big hug."""
    await ctx.send(f"🫂 {ctx.author.name} gave {target.name} a big warm hug!")

  @commands.command(name="kiss")
  async def kiss(self, ctx, target: discord.Member):
    """Send a kiss."""
    await ctx.send(f"💋 {ctx.author.name} kissed {target.name}!")

  @commands.command(name="kill")
  async def kill(self, ctx, target: discord.Member):
    """Fake text-elimination game."""
    ways = ["dropped a anvil 💥", "threw an enderpearl into lava 🔥"]
    await ctx.send(f"💀 {ctx.author.name} {random.choice(ways)} on {target.name}!")

  @commands.command(name="chase")
  async def chase(self, ctx):
    """Police chase simulation!"""
    res = random.choice(
        ["🚓 Escaped the police!", "🚓 Busted by the cops!"]
    )
    await ctx.send(res)

  @commands.command(name="coin")
  async def coin_flip_simple(self, ctx):
    """Quick coin toss."""
    await ctx.send(f"🪙 **{random.choice(['Heads', 'Tails'])}**")

  @commands.command(name="rollcustom")
  async def rollcustom(self, ctx, max_num: int = 100):
    """Roll a custom number range."""
    await ctx.send(f"🎲 Rolled: **{random.randint(1, max_num)}**")

  @commands.command(name="coinset")
  async def coinset(self, ctx):
    """Flip 3 coins at once."""
    coins = [random.choice(["H", "T"]) for _ in range(3)]
    await ctx.send(f"🪙 Flown coins: **[{', '.join(coins)}]**")


# Setup function to register Cog with main bot
async def setup(bot):
  await bot.add_cog(Minigames(bot))
