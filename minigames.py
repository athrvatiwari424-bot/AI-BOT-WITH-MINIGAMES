"""Liebe minigames: unified game hub, AI opponents, profiles and achievements."""
from __future__ import annotations

import random
import asyncio
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = "bot_data.db"

TRIVIA = [
    ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Mercury"], 1),
    ("How many sides does a hexagon have?", ["5", "6", "7", "8"], 1),
    ("Which ocean is the largest?", ["Atlantic", "Indian", "Arctic", "Pacific"], 3),
    ("What is the chemical symbol for gold?", ["Ag", "Au", "Gd", "Go"], 1),
    ("How many players are on the field for one football team?", ["9", "10", "11", "12"], 2),
]
SCRAMBLES = [("LPEPA", "APPLE"), ("GONAM", "MANGO"), ("RABEZ", "ZEBRA"), ("HCOOLS", "SCHOOL"), ("NTAEPL", "PLANET"), ("GRTIE", "TIGER"), ("HETRAC", "CHATER")]
EMOJI_PUZZLES = [("🦁👑", "LION KING"), ("🕷️👨", "SPIDER-MAN"), ("🌧️🎀", "RAINBOW"), ("⭐⚔️", "STAR WARS"), ("🧊👑", "FROZEN")]


async def init_game_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS minigame_user_stats (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id));
        CREATE TABLE IF NOT EXISTS minigame_game_stats (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, game TEXT NOT NULL,
            played INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, game));
        CREATE TABLE IF NOT EXISTS minigame_achievements (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, achievement TEXT NOT NULL,
            unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, user_id, achievement));
        """)
        await db.commit()


async def record_result(guild_id: int, user_id: int, game: str, result: str) -> list[str]:
    """Persist a completed game. result is win, loss or draw."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO minigame_user_stats(guild_id,user_id,games_played,wins,losses,draws)
            VALUES(?,?,1,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET
            games_played=games_played+1,wins=wins+excluded.wins,
            losses=losses+excluded.losses,draws=draws+excluded.draws""",
            (guild_id, user_id, int(result == "win"), int(result == "loss"), int(result == "draw")))
        await db.execute("""INSERT INTO minigame_game_stats(guild_id,user_id,game,played,wins)
            VALUES(?,?,?,1,?) ON CONFLICT(guild_id,user_id,game) DO UPDATE SET
            played=played+1,wins=wins+excluded.wins""", (guild_id, user_id, game, int(result == "win")))
        async with db.execute("SELECT games_played,wins FROM minigame_user_stats WHERE guild_id=? AND user_id=?", (guild_id,user_id)) as cur:
            played, wins = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) FROM minigame_game_stats WHERE guild_id=? AND user_id=?", (guild_id,user_id)) as cur:
            distinct_games = (await cur.fetchone())[0]
        checks = {
            "first_game": played >= 1,
            "first_win": wins >= 1,
            "veteran": played >= 10,
            "champion": wins >= 25,
            "game_explorer": distinct_games >= 4,
        }
        newly = []
        for key, unlocked in checks.items():
            if unlocked:
                cur = await db.execute("INSERT OR IGNORE INTO minigame_achievements(guild_id,user_id,achievement) VALUES(?,?,?)", (guild_id,user_id,key))
                if cur.rowcount:
                    newly.append(key)
        await db.commit()
        return newly


ACHIEVEMENTS = {
    "first_game": ("🎮 First Steps", "Finish your first game."),
    "first_win": ("🏆 First Victory", "Win your first game."),
    "veteran": ("🎖️ Regular Player", "Play 10 games."),
    "champion": ("👑 Champion", "Win 25 games."),
    "game_explorer": ("🧭 Game Explorer", "Play at least four different games."),
}


async def announce_result(interaction: discord.Interaction, game: str, outcomes: dict[int, tuple[discord.abc.User, str]]):
    if not interaction.guild:
        return
    unlock_lines = []
    for uid, (user, result) in outcomes.items():
        unlocked = await record_result(interaction.guild.id, uid, game, result)
        for key in unlocked:
            title, _ = ACHIEVEMENTS[key]
            unlock_lines.append(f"{user.mention} unlocked **{title}**")
    return "\n".join(unlock_lines)


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="·", row=x)
        self.x, self.y = x, y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user.id != view.current_player.id:
            return await interaction.response.send_message("It's not your turn.", ephemeral=True)
        if view.board[self.x][self.y] != 0:
            return await interaction.response.send_message("That square is already taken.", ephemeral=True)
        view._place(self.x, self.y, 1 if interaction.user.id == view.player1.id else -1)
        result = view.check_winner()
        if result is None and view.ai:
            move = view.ai_move()
            if move:
                view._place(*move, -1)
            result = view.check_winner()
        elif result is None and view.player2:
            view.current_player = view.player2 if view.current_player.id == view.player1.id else view.player1
        if result is not None:
            for item in view.children: item.disabled = True
            if result == 0:
                description = "🤝 It's a draw!"
                outcomes = {view.player1.id:(view.player1,"draw")}
                if view.player2: outcomes[view.player2.id] = (view.player2,"draw")
            elif result == 1:
                description = f"🏆 {view.player1.mention} wins!"
                outcomes = {view.player1.id:(view.player1,"win")}
                if view.player2: outcomes[view.player2.id] = (view.player2,"loss")
            else:
                winner = view.player2 if view.player2 else None
                description = f"🏆 {winner.mention} wins!" if winner else "🤖 The AI wins!"
                outcomes = {view.player1.id:(view.player1,"loss")}
                if winner: outcomes[winner.id] = (winner,"win")
            unlocked = await announce_result(interaction, "Tic-Tac-Toe", outcomes)
            if unlocked: description += "\n\n" + unlocked
            view.stop()
            return await interaction.response.edit_message(embed=discord.Embed(title="Tic-Tac-Toe · Finished", description=description, color=discord.Color.gold()), view=view)
        turn = f"{view.current_player.mention}'s turn" if view.player2 else f"{view.player1.mention}'s turn"
        await interaction.response.edit_message(embed=view.embed(turn), view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member | None = None, ai: bool = False):
        super().__init__(timeout=180)
        self.player1, self.player2, self.ai = player1, player2, ai
        self.current_player = player1
        self.board = [[0]*3 for _ in range(3)]
        for x in range(3):
            for y in range(3): self.add_item(TicTacToeButton(x,y))

    def _place(self, x: int, y: int, val: int):
        self.board[x][y] = val
        for item in self.children:
            if isinstance(item, TicTacToeButton) and item.x == x and item.y == y:
                item.label = "X" if val == 1 else "O"
                item.style = discord.ButtonStyle.danger if val == 1 else discord.ButtonStyle.success
                item.disabled = True
                break

    def check_winner(self):
        lines = self.board + [[self.board[r][c] for r in range(3)] for c in range(3)]
        lines += [[self.board[i][i] for i in range(3)], [self.board[i][2-i] for i in range(3)]]
        for line in lines:
            if sum(line) == 3: return 1
            if sum(line) == -3: return -1
        if all(v for row in self.board for v in row): return 0
        return None

    def ai_move(self):
        # Prefer a winning move, then block the player's immediate win, then center/corners.
        candidates = [(r,c) for r in range(3) for c in range(3) if self.board[r][c] == 0]
        for mark in (-1, 1):
            for move in candidates:
                self.board[move[0]][move[1]] = mark
                won = self.check_winner() == mark
                self.board[move[0]][move[1]] = 0
                if won and mark == -1: return move
                if won and mark == 1: block = move
            if mark == 1 and 'block' in locals(): return block
        return next((m for m in [(1,1),(0,0),(0,2),(2,0),(2,2)] if m in candidates), random.choice(candidates) if candidates else None)

    def embed(self, turn: str):
        board = "\n".join(" ".join("❌" if x==1 else "⭕" if x==-1 else "▫️" for x in row) for row in self.board)
        return discord.Embed(title="🎮 Tic-Tac-Toe", description=f"{turn}\n\n{board}", color=discord.Color.blurple())


class Connect4Button(discord.ui.Button):
    def __init__(self, col: int):
        super().__init__(label=str(col+1), style=discord.ButtonStyle.primary, row=0 if col < 4 else 1)
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        view: Connect4View = self.view
        if interaction.user.id != view.current_player.id:
            return await interaction.response.send_message("It's not your turn.", ephemeral=True)
        if not view.drop(self.col, "🔴" if interaction.user.id == view.player1.id else "🟡"):
            return await interaction.response.send_message("That column is full.", ephemeral=True)
        result = view.winner()
        if result is None and view.ai:
            col = view.ai_move()
            if col is not None: view.drop(col, "🟡")
            result = view.winner()
        elif result is None and view.player2:
            view.current_player = view.player2 if view.current_player.id == view.player1.id else view.player1
        if result is not None:
            for item in view.children: item.disabled = True
            if result == "draw":
                desc = "It's a draw!"; outcomes = {view.player1.id:(view.player1,"draw")}
                if view.player2: outcomes[view.player2.id] = (view.player2,"draw")
            else:
                winner = view.player1 if result == "🔴" else view.player2
                desc = f"🏆 {winner.mention} wins!" if winner else "🤖 The AI wins!"
                outcomes = {view.player1.id:(view.player1,"win" if result=="🔴" else "loss")}
                if view.player2: outcomes[view.player2.id] = (view.player2,"win" if result=="🟡" else "loss")
            unlocked = await announce_result(interaction, "Connect 4", outcomes)
            if unlocked: desc += "\n\n" + unlocked
            view.stop()
            return await interaction.response.edit_message(embed=discord.Embed(title="Connect 4 · Finished", description=f"{desc}\n\n{view.render()}", color=discord.Color.gold()), view=view)
        turn = f"{view.current_player.mention}'s turn" if view.player2 else f"{view.player1.mention}'s turn"
        await interaction.response.edit_message(embed=view.embed(turn), view=view)


class Connect4View(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member | None = None, ai: bool = False):
        super().__init__(timeout=240)
        self.player1, self.player2, self.ai = player1, player2, ai
        self.current_player = player1
        self.board = [["⚪"]*7 for _ in range(6)]
        for col in range(7): self.add_item(Connect4Button(col))

    def drop(self, col: int, piece: str):
        for r in range(5,-1,-1):
            if self.board[r][col] == "⚪": self.board[r][col] = piece; return True
        return False

    def winner(self):
        for r in range(6):
            for c in range(7):
                p = self.board[r][c]
                if p == "⚪": continue
                for dr,dc in ((0,1),(1,0),(1,1),(-1,1)):
                    cells = [(r+i*dr,c+i*dc) for i in range(4)]
                    if all(0<=rr<6 and 0<=cc<7 for rr,cc in cells) and all(self.board[rr][cc]==p for rr,cc in cells): return p
        if all(self.board[0][c] != "⚪" for c in range(7)): return "draw"
        return None

    def ai_move(self):
        available = [c for c in range(7) if self.board[0][c] == "⚪"]
        for piece in ("🟡", "🔴"):
            for col in available:
                self.drop(col,piece); won=self.winner()==piece
                for r in range(5,-1,-1):
                    if self.board[r][col] != "⚪": self.board[r][col]="⚪"; break
                if won: return col
        return min(available, key=lambda c: abs(c-3)) if available else None

    def render(self): return "\n".join("".join(row) for row in self.board)+"\n1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
    def embed(self, turn): return discord.Embed(title="🔴 Connect 4", description=f"{turn}\n\n{self.render()}", color=discord.Color.blurple())


class ChallengeView(discord.ui.View):
    def __init__(self, game: str, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.game, self.challenger, self.opponent = game, challenger, opponent

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge is for the selected opponent.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game == "Tic-Tac-Toe":
            view = TicTacToeView(self.challenger,self.opponent)
            embed = view.embed(f"{self.challenger.mention}'s turn (X)")
        else:
            view = Connect4View(self.challenger,self.opponent)
            embed = view.embed(f"{self.challenger.mention}'s turn (🔴)")
        await interaction.response.edit_message(content=None,embed=embed,view=view)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children: child.disabled=True
        await interaction.response.edit_message(content="Challenge declined.",view=self)
        self.stop()


class GuessModal(discord.ui.Modal):
    guess = discord.ui.TextInput(label="Your answer", max_length=40, required=True)
    def __init__(self, view, title="Submit your answer"):
        super().__init__(title=title); self.game_view=view
    async def on_submit(self, interaction: discord.Interaction):
        await self.game_view.submit(interaction, str(self.guess.value).strip())


class SoloAnswerView(discord.ui.View):
    def __init__(self, user: discord.Member, game: str, answer: str, prompt: str, hint: str = ""):
        super().__init__(timeout=90)
        self.user,self.game,self.answer,self.prompt,self.hint=user,game,answer.casefold(),prompt,hint
        self.finished=False
        self.message=None
    @discord.ui.button(label="Submit answer",style=discord.ButtonStyle.success,emoji="✍️")
    async def submit_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.user.id: return await interaction.response.send_message("This is someone else's game.",ephemeral=True)
        self.message=interaction.message
        await interaction.response.send_modal(GuessModal(self))
    async def submit(self,interaction:discord.Interaction,guess:str):
        if self.finished: return await interaction.response.send_message("This round has already ended.",ephemeral=True)
        self.finished=True
        won=" ".join(guess.casefold().replace("-", " ").split())==" ".join(self.answer.replace("-", " ").split())
        for child in self.children: child.disabled=True
        unlocked=await announce_result(interaction,self.game,{self.user.id:(self.user,"win" if won else "loss")})
        desc=("✅ Correct!" if won else f"❌ Not quite. The answer was **{self.answer.upper()}**.")
        if unlocked: desc += "\n\n"+unlocked
        await interaction.response.defer(ephemeral=True)
        if self.message:
            await self.message.edit(embed=discord.Embed(title=f"{self.game} · Finished",description=desc,color=discord.Color.green() if won else discord.Color.red()),view=self)
        await interaction.followup.send("Your answer has been submitted.",ephemeral=True)
        self.stop()


class HangmanLetterModal(discord.ui.Modal, title="Guess a letter"):
    letter = discord.ui.TextInput(label="One letter", min_length=1, max_length=1, required=True)
    def __init__(self, game_view):
        super().__init__(); self.game_view = game_view
    async def on_submit(self, interaction: discord.Interaction):
        await self.game_view.guess_letter(interaction, str(self.letter.value).strip().upper())


class HangmanSolveModal(discord.ui.Modal, title="Solve the word"):
    answer = discord.ui.TextInput(label="Your word", max_length=30, required=True)
    def __init__(self, game_view):
        super().__init__(); self.game_view = game_view
    async def on_submit(self, interaction: discord.Interaction):
        await self.game_view.solve(interaction, str(self.answer.value).strip())


class HangmanView(discord.ui.View):
    def __init__(self, user: discord.Member, word: str):
        super().__init__(timeout=120)
        self.user, self.word = user, word.upper()
        self.guessed: set[str] = set()
        self.misses = 0
        self.finished = False
        self.message = None

    def board_text(self):
        shown = " ".join(ch if ch in self.guessed else "＿" for ch in self.word)
        return f"**Word:** {shown}\n**Wrong guesses:** {self.misses}/6\n**Used letters:** {', '.join(sorted(self.guessed)) or 'None'}"

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is someone else's Hangman game.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("This round has ended.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Guess a letter", style=discord.ButtonStyle.primary, emoji="🔤")
    async def letter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.message = interaction.message
        await interaction.response.send_modal(HangmanLetterModal(self))

    @discord.ui.button(label="Solve word", style=discord.ButtonStyle.success, emoji="💡")
    async def solve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.message = interaction.message
        await interaction.response.send_modal(HangmanSolveModal(self))

    async def _finish(self, interaction, won: bool):
        self.finished = True
        for item in self.children: item.disabled = True
        unlocked = await announce_result(interaction, "Hangman", {self.user.id: (self.user, "win" if won else "loss")})
        desc = ("🏆 You guessed the word!" if won else f"❌ The word was **{self.word}**.") + "\n\n" + self.board_text()
        if unlocked: desc += "\n\n" + unlocked
        await interaction.response.defer(ephemeral=True)
        if self.message:
            await self.message.edit(embed=discord.Embed(title="🔤 Hangman · Finished", description=desc, color=discord.Color.green() if won else discord.Color.red()), view=self)
        await interaction.followup.send("Your guess has been submitted.", ephemeral=True)
        self.stop()

    async def guess_letter(self, interaction, letter: str):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This is someone else's game.", ephemeral=True)
        if len(letter) != 1 or not letter.isalpha():
            return await interaction.response.send_message("Enter exactly one letter from A to Z.", ephemeral=True)
        if letter in self.guessed:
            return await interaction.response.send_message("You already tried that letter.", ephemeral=True)
        self.guessed.add(letter)
        if letter not in self.word: self.misses += 1
        if all(ch in self.guessed for ch in self.word): return await self._finish(interaction, True)
        if self.misses >= 6: return await self._finish(interaction, False)
        await interaction.response.defer(ephemeral=True)
        if self.message:
            await self.message.edit(embed=discord.Embed(title="🔤 Hangman", description=self.board_text(), color=discord.Color.blurple()), view=self)
        await interaction.followup.send("Letter recorded.", ephemeral=True)

    async def solve(self, interaction, answer: str):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This is someone else's game.", ephemeral=True)
        won = " ".join(answer.upper().replace("-", " ").split()) == " ".join(self.word.replace("-", " ").split())
        await self._finish(interaction, won)


class TriviaView(discord.ui.View):
    def __init__(self,user,question,options,answer):
        super().__init__(timeout=60); self.user=user; self.answer=answer; self.done=False
        for i,option in enumerate(options):
            button=discord.ui.Button(label=option,style=discord.ButtonStyle.primary,row=i//2)
            button.callback=self.make_callback(i)
            self.add_item(button)
    def make_callback(self,index):
        async def callback(interaction):
            if interaction.user.id!=self.user.id: return await interaction.response.send_message("This is someone else's quiz.",ephemeral=True)
            if self.done: return await interaction.response.send_message("This question has ended.",ephemeral=True)
            self.done=True; won=index==self.answer
            for child in self.children: child.disabled=True
            unlocked=await announce_result(interaction,"Trivia",{self.user.id:(self.user,"win" if won else "loss")})
            desc="✅ Correct answer!" if won else "❌ Incorrect."
            if not won:
                correct=self.children[self.answer].label
                desc=f"❌ Incorrect. The answer was **{correct}**."
            if unlocked: desc+="\n\n"+unlocked
            await interaction.response.edit_message(embed=discord.Embed(title="Trivia · Finished",description=desc,color=discord.Color.green() if won else discord.Color.red()),view=self)
            self.stop()
        return callback


class HighLowView(discord.ui.View):
    def __init__(self, user: discord.Member, current_card: int):
        super().__init__(timeout=60)
        self.user, self.current_card = user, current_card
        self.finished = False
    async def interaction_check(self, interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is someone else's round.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("This round has ended.", ephemeral=True)
            return False
        return True
    async def choose(self, interaction, choice):
        next_card = random.randint(1, 13)
        won = (choice == "higher" and next_card > self.current_card) or (choice == "lower" and next_card < self.current_card)
        draw = next_card == self.current_card
        self.finished = True
        for item in self.children: item.disabled = True
        result = "draw" if draw else "win" if won else "loss"
        unlocked = await announce_result(interaction, "High-Low", {self.user.id: (self.user, result)})
        verdict = "🤝 Same card, it's a draw." if draw else "🏆 Correct prediction!" if won else "❌ Not this time."
        desc = f"First card: **{self.current_card}**\nNext card: **{next_card}**\n\n{verdict}"
        if unlocked: desc += "\n\n" + unlocked
        await interaction.response.edit_message(embed=discord.Embed(title="🃏 High-Low · Finished", description=desc, color=discord.Color.gold()), view=self)
        self.stop()
    @discord.ui.button(label="Higher 📈", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "higher")
    @discord.ui.button(label="Lower 📉", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, "lower")


class RockPaperScissorsView(discord.ui.View):
    def __init__(self,user): super().__init__(timeout=60); self.user=user; self.finished=False
    async def play(self,interaction,choice):
        if interaction.user.id!=self.user.id: return await interaction.response.send_message("This is someone else's round.",ephemeral=True)
        if self.finished: return await interaction.response.send_message("This round has ended.",ephemeral=True)
        self.finished=True
        bot=random.choice(["rock","paper","scissors"])
        won=choice==bot or (choice,bot) in (("rock","scissors"),("paper","rock"),("scissors","paper"))
        draw=choice==bot; result="draw" if draw else "win" if won else "loss"
        for child in self.children: child.disabled=True
        unlocked=await announce_result(interaction,"Rock Paper Scissors",{self.user.id:(self.user,result)})
        desc=f"You chose **{choice.title()}**. I chose **{bot.title()}**.\n"+("🤝 Draw!" if draw else "🏆 You win!" if won else "I win this round!")
        if unlocked: desc+="\n\n"+unlocked
        await interaction.response.edit_message(embed=discord.Embed(title="Rock Paper Scissors",description=desc,color=discord.Color.gold()),view=self); self.stop()
    @discord.ui.button(label="Rock 🪨",style=discord.ButtonStyle.primary)
    async def rock(self,i,b): await self.play(i,"rock")
    @discord.ui.button(label="Paper 📄",style=discord.ButtonStyle.primary)
    async def paper(self,i,b): await self.play(i,"paper")
    @discord.ui.button(label="Scissors ✂️",style=discord.ButtonStyle.primary)
    async def scissors(self,i,b): await self.play(i,"scissors")


class GamesHubView(discord.ui.View):
    def __init__(self, owner: discord.Member):
        super().__init__(timeout=180); self.owner=owner
        options=[discord.SelectOption(label="Tic-Tac-Toe",value="Tic-Tac-Toe",emoji="❌",description="Classic 3×3 strategy"),
                 discord.SelectOption(label="Connect 4",value="Connect 4",emoji="🔴",description="Connect four discs in a row"),
                 discord.SelectOption(label="Rock Paper Scissors",value="Rock Paper Scissors",emoji="✂️",description="Quick match against Liebe"),
                 discord.SelectOption(label="High-Low",value="High-Low",emoji="🃏",description="Predict the next card, no stakes"),
                 discord.SelectOption(label="Hangman",value="Hangman",emoji="🔤",description="Guess the hidden word"),
                 discord.SelectOption(label="Word Scramble",value="Word Scramble",emoji="🔀",description="Unscramble the letters"),
                 discord.SelectOption(label="Trivia",value="Trivia",emoji="🧠",description="Test your general knowledge"),
                 discord.SelectOption(label="Emoji Decode",value="Emoji Decode",emoji="🧩",description="Decode the emoji clue")]
        select=discord.ui.Select(placeholder="Choose a game…",options=options)
        select.callback=self.select_game; self.add_item(select)
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner.id:
            await interaction.response.send_message("Open `/games` to start your own game menu.",ephemeral=True); return False
        return True
    async def select_game(self,interaction):
        game=interaction.data["values"][0]
        view=GameLaunchView(self.owner,game)
        embed=discord.Embed(title=f"{game}",description="Choose how you want to play. Tic-Tac-Toe and Connect 4 support both AI and friend matches; the other games are solo challenges against Liebe.",color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed,view=view)


class GameLaunchView(discord.ui.View):
    def __init__(self,owner,game):
        super().__init__(timeout=120); self.owner=owner; self.game=game
        if game in ("Tic-Tac-Toe","Connect 4"):
            self.add_item(discord.ui.Button(label="Play vs AI",style=discord.ButtonStyle.success,emoji="🤖",custom_id="launch_ai"))
            self.children[0].callback=self.start_ai
            self.add_item(discord.ui.UserSelect(placeholder="Select a friend to challenge…",min_values=1,max_values=1,custom_id="launch_friend"))
            self.children[1].callback=self.challenge_friend
        else:
            button=discord.ui.Button(label="Start game",style=discord.ButtonStyle.success,emoji="▶️")
            button.callback=self.start_solo; self.add_item(button)
        back=discord.ui.Button(label="Back to games",style=discord.ButtonStyle.secondary,emoji="↩️")
        back.callback=self.back; self.add_item(back)
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner.id:
            await interaction.response.send_message("Only the person who opened this menu can launch its game.",ephemeral=True); return False
        return True
    async def back(self,interaction):
        await interaction.response.edit_message(embed=discord.Embed(title="🎮 Liebe Game Center",description="Choose a game from the menu below.",color=discord.Color.blurple()),view=GamesHubView(self.owner))
    async def start_ai(self,interaction):
        if self.game=="Tic-Tac-Toe":
            view=TicTacToeView(self.owner,ai=True); embed=view.embed(f"{self.owner.mention}'s turn (X) · AI: Liebe")
        else:
            view=Connect4View(self.owner,ai=True); embed=view.embed(f"{self.owner.mention}'s turn (🔴) · AI: Liebe")
        await interaction.response.edit_message(embed=embed,view=view)
    async def challenge_friend(self,interaction):
        opponent=interaction.data.get("values",[])
        if not opponent: return await interaction.response.send_message("Select a member first.",ephemeral=True)
        user_id=int(opponent[0]); member=interaction.guild.get_member(user_id) if interaction.guild else None
        if member is None and interaction.guild:
            try: member=await interaction.guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException): member=None
        if not member or member.bot or member.id==self.owner.id:
            return await interaction.response.send_message("Choose another server member, not a bot or yourself.",ephemeral=True)
        view=ChallengeView(self.game,self.owner,member)
        await interaction.response.edit_message(content=f"{member.mention}, {self.owner.mention} challenged you to **{self.game}**. Accept or decline.",embed=None,view=view)
    async def start_solo(self,interaction):
        if self.game=="Rock Paper Scissors":
            await interaction.response.edit_message(embed=discord.Embed(title="✂️ Rock Paper Scissors",description="Choose your move against Liebe.",color=discord.Color.blurple()),view=RockPaperScissorsView(self.owner)); return
        if self.game=="High-Low":
            card=random.randint(1,13)
            await interaction.response.edit_message(embed=discord.Embed(title="🃏 High-Low",description=f"Your card is **{card}**. Will the next card be higher or lower? No currency or bets are involved.",color=discord.Color.gold()),view=HighLowView(self.owner,card)); return
        if self.game=="Hangman":
            word=random.choice(["PYTHON","DISCORD","GALAXY","CRICKET","DIAMOND","PUZZLE","LIBRARY"])
            view=HangmanView(self.owner,word)
            await interaction.response.edit_message(embed=discord.Embed(title="🔤 Hangman",description="Guess the hidden word one letter at a time. You have six incorrect guesses.\n\n"+view.board_text(),color=discord.Color.blurple()),view=view); return
        if self.game=="Word Scramble":
            scrambled,answer=random.choice(SCRAMBLES)
            prompt=f"Unscramble: **{' '.join(scrambled)}**"
            view=SoloAnswerView(self.owner,"Word Scramble",answer,prompt)
            await interaction.response.edit_message(embed=discord.Embed(title="🔀 Word Scramble",description=prompt+"\nSubmit the complete word.",color=discord.Color.blurple()),view=view); return
        if self.game=="Trivia":
            question,options,answer=random.choice(TRIVIA)
            await interaction.response.edit_message(embed=discord.Embed(title="🧠 Trivia",description=question,color=discord.Color.blurple()),view=TriviaView(self.owner,question,options,answer)); return
        if self.game=="Emoji Decode":
            clue,answer=random.choice(EMOJI_PUZZLES)
            prompt=f"Decode this clue: **{clue}**"
            view=SoloAnswerView(self.owner,"Emoji Decode",answer,prompt)
            await interaction.response.edit_message(embed=discord.Embed(title="🧩 Emoji Decode",description=prompt+"\nSubmit your answer.",color=discord.Color.blurple()),view=view)


class MiniGames(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def cog_load(self): await init_game_db()

    @app_commands.guild_only()
    @app_commands.command(name="games",description="Open Liebe's game center and choose a game.")
    async def games(self,interaction:discord.Interaction):
        embed=discord.Embed(title="🎮 Liebe Game Center",description="Choose a game below. Challenge a friend or play against AI where supported.",color=discord.Color.blurple())
        embed.add_field(name="Strategy",value="❌ Tic-Tac-Toe\n🔴 Connect 4",inline=True)
        embed.add_field(name="Quick & casual",value="✂️ Rock Paper Scissors\n🃏 High-Low\n🔤 Hangman\n🔀 Word Scramble",inline=True)
        embed.add_field(name="Brain games",value="🧠 Trivia\n🧩 Emoji Decode",inline=True)
        await interaction.response.send_message(embed=embed,view=GamesHubView(interaction.user))

    @app_commands.guild_only()
    @app_commands.command(name="profile",description="View your or another member's minigame profile.")
    async def profile(self,interaction:discord.Interaction,member:discord.Member|None=None):
        target=member or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT games_played,wins,losses,draws FROM minigame_user_stats WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id)) as cur: stats=await cur.fetchone()
            async with db.execute("SELECT game,played,wins FROM minigame_game_stats WHERE guild_id=? AND user_id=? ORDER BY wins DESC,played DESC",(interaction.guild_id,target.id)) as cur: games=await cur.fetchall()
            async with db.execute("SELECT COUNT(*) FROM minigame_achievements WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id)) as cur: achievement_count=(await cur.fetchone())[0]
        played,wins,losses,draws=stats or (0,0,0,0); rate=(wins/played*100) if played else 0
        embed=discord.Embed(title=f"🎮 {target.display_name}'s Game Profile",color=discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Games played",value=str(played),inline=True); embed.add_field(name="Wins",value=str(wins),inline=True); embed.add_field(name="Win rate",value=f"{rate:.1f}%",inline=True)
        embed.add_field(name="Losses / Draws",value=f"{losses} / {draws}",inline=True); embed.add_field(name="Achievements",value=str(achievement_count),inline=True)
        if games: embed.add_field(name="Game breakdown",value="\n".join(f"**{g}** · {w}/{p} wins" for g,p,w in games[:8]),inline=False)
        else: embed.description="No minigame stats yet. Use `/games` to start!"
        await interaction.response.send_message(embed=embed,ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="achievements",description="View your unlocked minigame achievements.")
    async def achievements(self,interaction:discord.Interaction,member:discord.Member|None=None):
        target=member or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT achievement,unlocked_at FROM minigame_achievements WHERE guild_id=? AND user_id=? ORDER BY unlocked_at",(interaction.guild_id,target.id)) as cur: rows=await cur.fetchall()
        embed=discord.Embed(title=f"🏅 {target.display_name}'s Achievements",color=discord.Color.gold())
        if rows: embed.description="\n".join(f"**{ACHIEVEMENTS.get(k,(k,''))[0]}**\n{ACHIEVEMENTS.get(k,('', ''))[1]}" for k,_ in rows)
        else: embed.description="No achievements unlocked yet. Play games to earn your first one!"
        await interaction.response.send_message(embed=embed,ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="serverstats",description="View this server's minigame activity.")
    async def serverstats(self,interaction:discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COALESCE(SUM(games_played),0),COALESCE(SUM(wins),0),COUNT(*) FROM minigame_user_stats WHERE guild_id=?",(interaction.guild_id,)) as cur: total,wins,players=await cur.fetchone()
            async with db.execute("SELECT game,SUM(played) AS n FROM minigame_game_stats WHERE guild_id=? GROUP BY game ORDER BY n DESC LIMIT 5",(interaction.guild_id,)) as cur: popular=await cur.fetchall()
        embed=discord.Embed(title=f"📊 {interaction.guild.name} · Game Stats",color=discord.Color.blurple())
        embed.add_field(name="Player-games",value=str(total),inline=True); embed.add_field(name="Players",value=str(players),inline=True); embed.add_field(name="Wins recorded",value=str(wins),inline=True)
        embed.add_field(name="Popular games",value="\n".join(f"{g}: **{n}**" for g,n in popular) or "No games played yet.",inline=False)
        await interaction.response.send_message(embed=embed,ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="tictactoe",description="Play Tic-Tac-Toe against Liebe or challenge a member.")
    async def tictactoe(self,interaction:discord.Interaction,opponent:discord.Member|None=None):
        if opponent:
            if opponent.bot or opponent.id==interaction.user.id: return await interaction.response.send_message("Choose another human member.",ephemeral=True)
            await interaction.response.send_message(content=f"{opponent.mention}, {interaction.user.mention} challenged you to Tic-Tac-Toe.",view=ChallengeView("Tic-Tac-Toe",interaction.user,opponent))
        else:
            view=TicTacToeView(interaction.user,ai=True)
            await interaction.response.send_message(embed=view.embed(f"{interaction.user.mention}'s turn (X) · AI: Liebe"),view=view)

    @app_commands.guild_only()
    @app_commands.command(name="highlow",description="Predict whether the next card will be higher or lower. No bets.")
    async def highlow(self, interaction: discord.Interaction):
        card=random.randint(1,13)
        await interaction.response.send_message(embed=discord.Embed(title="🃏 High-Low",description=f"Your card is **{card}**. Will the next card be higher or lower? No currency or bets are involved.",color=discord.Color.gold()),view=HighLowView(interaction.user,card))

    @app_commands.guild_only()
    @app_commands.command(name="connect4",description="Play Connect 4 against Liebe or challenge a member.")
    async def connect4(self,interaction:discord.Interaction,opponent:discord.Member|None=None):
        if opponent:
            if opponent.bot or opponent.id==interaction.user.id: return await interaction.response.send_message("Choose another human member.",ephemeral=True)
            await interaction.response.send_message(content=f"{opponent.mention}, {interaction.user.mention} challenged you to Connect 4.",view=ChallengeView("Connect 4",interaction.user,opponent))
        else:
            view=Connect4View(interaction.user,ai=True)
            await interaction.response.send_message(embed=view.embed(f"{interaction.user.mention}'s turn (🔴) · AI: Liebe"),view=view)


async def setup(bot): await bot.add_cog(MiniGames(bot))
