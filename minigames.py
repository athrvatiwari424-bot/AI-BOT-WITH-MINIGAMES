import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

# ==========================================
# 1. TIC-TAC-TOE INTERACTIVE COMPONENTS
# ==========================================
class TicTacToeChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=45)
        self.challenger = challenger
        self.opponent = opponent
        self.accepted = False

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("❌ This challenge isn't for you!", ephemeral=True)
        
        self.accepted = True
        game_view = TicTacToeView(self.challenger, self.opponent)
        embed = discord.Embed(
            title="🎮 Tic-Tac-Toe Match",
            description=f"Challenge accepted by {self.opponent.mention}!\nTurn: **{self.challenger.mention}** (`X`)",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=game_view)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, emoji="❌")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("❌ This challenge isn't for you!", ephemeral=True)
        
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🎮 Tic-Tac-Toe Challenge Declined",
            description=f"❌ {self.opponent.mention} declined the challenge from {self.challenger.mention}.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="​", row=x)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user != view.current_player:
            return await interaction.response.send_message("❌ It's not your turn!", ephemeral=True)

        if view.board[self.x][self.y] != 0:
            return await interaction.response.send_message("❌ Tile already occupied!", ephemeral=True)

        current_val = 1 if view.current_player == view.player1 else -1
        view.board[self.x][self.y] = current_val

        self.style = discord.ButtonStyle.danger if current_val == 1 else discord.ButtonStyle.success
        self.label = "X" if current_val == 1 else "O"
        self.disabled = True

        winner = view.check_winner()
        if winner is not None:
            for child in view.children:
                child.disabled = True
            msg = f"🎉 **{view.player1.mention} (X) Wins!**" if winner == 1 else (f"🎉 **{view.player2.mention if view.player2 else 'Bot'} (O) Wins!**" if winner == -1 else "🤝 **It's a Draw!**")
            embed = discord.Embed(title="🎮 Tic-Tac-Toe - Game Over!", description=msg, color=discord.Color.green())
            return await interaction.response.edit_message(embed=embed, view=view)

        if view.player2:
            view.current_player = view.player2 if view.current_player == view.player1 else view.player1
            embed = discord.Embed(
                title="🎮 Tic-Tac-Toe Match",
                description=f"Turn: **{view.current_player.mention}** (`{'X' if view.current_player == view.player1 else 'O'}`)",
                color=discord.Color.blue()
            )
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            empty_tiles = [child for child in view.children if not child.disabled and isinstance(child, TicTacToeButton)]
            if empty_tiles:
                bot_tile = random.choice(empty_tiles)
                view.board[bot_tile.x][bot_tile.y] = -1
                bot_tile.style = discord.ButtonStyle.success
                bot_tile.label = "O"
                bot_tile.disabled = True

                winner = view.check_winner()
                if winner == -1:
                    for child in view.children: child.disabled = True
                    embed = discord.Embed(title="🎮 Tic-Tac-Toe - Game Over!", description="💀 **Bot (O) Wins!**", color=discord.Color.red())
                    return await interaction.response.edit_message(embed=embed, view=view)
                elif winner == 0:
                    for child in view.children: child.disabled = True
                    embed = discord.Embed(title="🎮 Tic-Tac-Toe - Game Over!", description="🤝 **It's a Draw!**", color=discord.Color.gold())
                    return await interaction.response.edit_message(embed=embed, view=view)

            embed = discord.Embed(title="🎮 Tic-Tac-Toe Match", description=f"Turn: **{view.player1.mention}** (`X`)", color=discord.Color.blue())
            await interaction.response.edit_message(embed=embed, view=view)

class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member = None):
        super().__init__(timeout=120)
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        for x in range(3):
            for y in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        for i in range(3):
            if abs(sum(self.board[i])) == 3: return self.board[i][0]
            if abs(sum(self.board[x][i] for x in range(3))) == 3: return self.board[0][i]
        if abs(self.board[0][0] + self.board[1][1] + self.board[2][2]) == 3: return self.board[1][1]
        if abs(self.board[0][2] + self.board[1][1] + self.board[2][0]) == 3: return self.board[1][1]
        if all(cell != 0 for row in self.board for cell in row): return 0
        return None


# ==========================================
# 2. CONNECT 4 INTERACTIVE COMPONENTS
# ==========================================
class Connect4View(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=180)
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.board = [["⚪" for _ in range(7)] for _ in range(6)]
        
        for col in range(7):
            self.add_item(Connect4Button(col))

    def render_board(self) -> str:
        board_str = "\n".join("".join(row) for row in self.board)
        board_str += "\n1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        return board_str

    def drop_piece(self, col: int, emoji: str) -> bool:
        for r in range(5, -1, -1):
            if self.board[r][col] == "⚪":
                self.board[r][col] = emoji
                return True
        return False

    def check_winner(self, emoji: str) -> bool:
        # Horizontal
        for r in range(6):
            for c in range(4):
                if all(self.board[r][c+i] == emoji for i in range(4)): return True
        # Vertical
        for r in range(3):
            for c in range(7):
                if all(self.board[r+i][c] == emoji for i in range(4)): return True
        # Positive Diagonal
        for r in range(3):
            for c in range(4):
                if all(self.board[r+i][c+i] == emoji for i in range(4)): return True
        # Negative Diagonal
        for r in range(3, 6):
            for c in range(4):
                if all(self.board[r-i][c+i] == emoji for i in range(4)): return True
        return False

class Connect4Button(discord.ui.Button):
    def __init__(self, col: int):
        super().__init__(label=str(col+1), style=discord.ButtonStyle.primary, row=0 if col < 4 else 1)
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        view: Connect4View = self.view
        if interaction.user != view.current_player:
            return await interaction.response.send_message("❌ It's not your turn!", ephemeral=True)

        piece = "🔴" if view.current_player == view.player1 else "🟡"
        if not view.drop_piece(self.col, piece):
            return await interaction.response.send_message("❌ That column is full!", ephemeral=True)

        if view.check_winner(piece):
            for child in view.children: child.disabled = True
            embed = discord.Embed(
                title="🔴 Connect 4 - Winner!",
                description=f"🎉 **{view.current_player.mention} connected four in a row!**\n\n{view.render_board()}",
                color=discord.Color.green()
            )
            return await interaction.response.edit_message(embed=embed, view=view)

        view.current_player = view.player2 if view.current_player == view.player1 else view.player1
        embed = discord.Embed(
            title="🟡 Connect 4 Match",
            description=f"Turn: **{view.current_player.mention}** ({'🔴' if view.current_player == view.player1 else '🟡'})\n\n{view.render_board()}",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ==========================================
# 3. HIGH-LOW GAMBLING VIEW
# ==========================================
class HighLowView(discord.ui.View):
    def __init__(self, user: discord.Member, current_card: int, bet: int):
        super().__init__(timeout=60)
        self.user = user
        self.current_card = current_card
        self.bet = bet

    @discord.ui.button(label="Higher 📈", style=discord.ButtonStyle.green)
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_guess(interaction, "higher")

    @discord.ui.button(label="Lower 📉", style=discord.ButtonStyle.red)
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_guess(interaction, "lower")

    async def process_guess(self, interaction: discord.Interaction, choice: str):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌ Play your own game!", ephemeral=True)

        next_card = random.randint(1, 13)
        won = (choice == "higher" and next_card > self.current_card) or (choice == "lower" and next_card < self.current_card)

        for child in self.children: child.disabled = True

        if won:
            reward = self.bet * 2
            embed = discord.Embed(
                title="🃏 High-Low - You Won!",
                description=f"First Card: **{self.current_card}**\nNext Card: **{next_card}**\n\n🎉 You guessed correctly and won **${reward}**!",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="🃏 High-Low - You Lost!",
                description=f"First Card: **{self.current_card}**\nNext Card: **{next_card}**\n\n💥 Bad luck! You lost your bet of **${self.bet}**.",
                color=discord.Color.red()
            )
        await interaction.response.edit_message(embed=embed, view=self)


# ==========================================
# 4. MINIGAMES COG MAIN COMMANDS
# ==========================================
class MiniGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tictactoe", description="Challenge a friend or play against the bot in Tic-Tac-Toe")
    @app_commands.describe(opponent="Challenge another player (optional)")
    async def tictactoe(self, interaction: discord.Interaction, opponent: discord.Member = None):
        if not opponent:
            view = TicTacToeView(interaction.user, None)
            embed = discord.Embed(title="🎮 Tic-Tac-Toe vs Bot", description=f"Match started!\nTurn: **{interaction.user.mention}** (`X`)", color=discord.Color.blue())
            return await interaction.response.send_message(embed=embed, view=view)

        if opponent.bot or opponent == interaction.user:
            return await interaction.response.send_message("❌ Invalid opponent selection!", ephemeral=True)

        challenge_view = TicTacToeChallengeView(interaction.user, opponent)
        embed = discord.Embed(
            title="⚔️ Tic-Tac-Toe Challenge!",
            description=f"{opponent.mention}, you have been challenged by {interaction.user.mention}!",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(content=opponent.mention, embed=embed, view=challenge_view)

    @app_commands.command(name="connect4", description="Play Connect 4 against another member")
    @app_commands.describe(opponent="The member you want to challenge")
    async def connect4(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot or opponent == interaction.user:
            return await interaction.response.send_message("❌ Select a valid member to challenge!", ephemeral=True)

        view = Connect4View(interaction.user, opponent)
        embed = discord.Embed(
            title="🔴 Connect 4 Match",
            description=f"Game started between {interaction.user.mention} and {opponent.mention}!\nTurn: **{interaction.user.mention}** (🔴)\n\n{view.render_board()}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(content=f"{interaction.user.mention} vs {opponent.mention}", embed=embed, view=view)

    @app_commands.command(name="highlow", description="Gamble on whether the next card will be higher or lower")
    @app_commands.describe(bet="Amount to bet")
    async def highlow(self, interaction: discord.Interaction, bet: int = 50):
        if bet < 10:
            return await interaction.response.send_message("❌ Minimum bet is $10!", ephemeral=True)

        first_card = random.randint(1, 13)
        view = HighLowView(interaction.user, first_card, bet)
        embed = discord.Embed(
            title="🃏 High-Low Game",
            description=f"Your Card: **{first_card}** (Scale: 1-13)\nBet: **${bet}**\n\nWill the next card be **Higher** or **Lower**?",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MiniGames(bot))
