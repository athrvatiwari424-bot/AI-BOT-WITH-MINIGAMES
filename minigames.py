import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

# --- GIF CONFIGURATION ---
GIF_VIRAT = "https://media.discordapp.net/attachments/1034931132547997736/1123908766463700992/virat-kohli-king-kohli.gif"
GIF_CATCH_CHECK = "https://cdn.discordapp.com/attachments/994983976626311169/1441758819507240960/catch_drop_3.gif"
GIF_DROPPED = "https://media.discordapp.net/attachments/1437542136118644958/1437542186534043739/live-1762700491431-ezgif.com-video-to-gif-converter.gif"
GIF_FIFTY = "https://tenor.com/view/veda-veda-krishnamurthy-cricket-50-half-century-gif-21893373"

# --- ECONOMY STORAGE ---
USER_DATA = {}
SHOP_ITEMS = {
    "bat": {"name": "🏏 Custom Cricket Bat", "price": 500, "desc": "Show off your swagger on the pitch!"},
    "coin": {"name": "🪙 Lucky Coin", "price": 1000, "desc": "Boosts your coin flip flex!"},
    "trophy": {"name": "🏆 Gold Trophy", "price": 2500, "desc": "Ultimate flex for server legends."},
    "coffee": {"name": "☕ Energy Drink", "price": 150, "desc": "A quick refreshment after hard work."}
}

def get_user(user_id: int):
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {"wallet": 200, "inventory": []}
    return USER_DATA[user_id]


# --- CRICKET LOBBY UI ---
class CricketLobbyView(discord.ui.View):
    def __init__(self, match_session):
        super().__init__(timeout=900)  # 15 minute timeout auto-disband
        self.match_session = match_session

    async def on_timeout(self):
        if not self.match_session["started"]:
            self.match_session["active"] = False
            try:
                await self.match_session["msg"].edit(content="⌛ **Cricket lobby expired and auto-disbanded after 15 minutes of inactivity.**", embed=None, view=None)
            except Exception:
                pass

    @discord.ui.button(label="Join Team A", style=discord.ButtonStyle.primary, custom_id="join_team_a")
    async def join_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in self.match_session["team_b"]:
            self.match_session["team_b"].remove(user)
        if user not in self.match_session["team_a"]:
            self.match_session["team_a"].append(user)
            await interaction.response.send_message(f"✅ {user.mention} joined **{self.match_session['team_a_name']}**!", ephemeral=True)
            await self.match_session["update_embed"]()
        else:
            await interaction.response.send_message("You are already in this team!", ephemeral=True)

    @discord.ui.button(label="Join Team B", style=discord.ButtonStyle.danger, custom_id="join_team_b")
    async def join_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in self.match_session["team_a"]:
            self.match_session["team_a"].remove(user)
        if user not in self.match_session["team_b"]:
            self.match_session["team_b"].append(user)
            await interaction.response.send_message(f"✅ {user.mention} joined **{self.match_session['team_b_name']}**!", ephemeral=True)
            await self.match_session["update_embed"]()
        else:
            await interaction.response.send_message("You are already in this team!", ephemeral=True)

    @discord.ui.button(label="Start Match 🚀", style=discord.ButtonStyle.success, custom_id="start_match")
    async def start_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.match_session["host"]:
            return await interaction.response.send_message("❌ Only the host can start the match!", ephemeral=True)
        if len(self.match_session["team_a"]) == 0 or len(self.match_session["team_b"]) == 0:
            return await interaction.response.send_message("❌ Both teams must have at least 1 player/bot!", ephemeral=True)
        if len(self.match_session["team_a"]) != len(self.match_session["team_b"]):
            return await interaction.response.send_message("❌ Teams must have an equal number of players! Use `/addbot` to balance.", ephemeral=True)

        self.match_session["started"] = True
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.response.send_message(f"🏏 **Match starting between {self.match_session['team_a_name']} and {self.match_session['team_b_name']}! Check DMs.**")
        self.match_session["future"].set_result(True)


# --- TIC-TAC-TOE UI ---
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
            return await interaction.response.send_message("❌ Spot already taken!", ephemeral=True)

        if view.current_player == view.playerX:
            self.style = discord.ButtonStyle.primary
            self.label = "X"
            view.board[self.x][self.y] = 1
            view.current_player = view.playerO
        else:
            self.style = discord.ButtonStyle.danger
            self.label = "O"
            view.board[self.x][self.y] = 2
            view.current_player = view.playerX

        self.disabled = True
        winner = view.check_winner()
        if winner is not None:
            for child in view.children:
                child.disabled = True
            if winner == 1:
                content = f"🎉 **{view.playerX.mention} (X) wins!**"
            elif winner == 2:
                content = f"🎉 **{view.playerO.mention} (O) wins!**"
            else:
                content = "🤝 **It's a tie!**"
            await interaction.response.edit_message(content=content, view=view)
            view.stop()
            return

        content = f"🎮 Tic-Tac-Toe! Turn: **{view.current_player.mention}**"
        await interaction.response.edit_message(content=content, view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, playerX: discord.Member, playerO: discord.Member):
        super().__init__(timeout=120)
        self.playerX = playerX
        self.playerO = playerO
        self.current_player = playerX
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        for x in range(3):
            for y in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        for row in self.board:
            if row[0] == row[1] == row[2] != 0:
                return row[0]
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] != 0:
                return self.board[0][col]
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]
        if all(self.board[r][c] != 0 for r in range(3) for c in range(3)):
            return 0
        return None


# --- ACTIVE LOBBY REGISTRY FOR MANAGEMENT COMMANDS ---
ACTIVE_LOBBIES = {}


# --- MAIN COG ---
class Minigames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- 1. WORD & PUZZLE GAMES ---
    @app_commands.command(name="guesstheword", description="Play a round of Guess the Word!")
    async def guesstheword(self, interaction: discord.Interaction):
        words_list = ["APPLE", "TRAIN", "BEACH", "CHESS", "PLANT", "TIGER", "SMILE", "WATER", "HOUSE", "MUSIC"]
        target = random.choice(words_list)
        await interaction.response.send_message(f"🧩 **Guess the Word!** 5-letter word. Type your guesses in chat! 5 attempts.")

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel and len(m.content.upper()) == 5

        for _ in range(5):
            try:
                msg = await self.bot.wait_for("message", timeout=30.0, check=check)
                guess = msg.content.upper()
                if guess == target:
                    return await msg.reply(f"🎉 Correct! The word was **{target}**!")
                
                feedback = "".join([f"🟩 `{guess[i]}`" if guess[i] == target[i] else f"🟨 `{guess[i]}`" if guess[i] in target else f"⬛ `{guess[i]}`" for i in range(5)])
                await msg.reply(f"Feedback: {feedback}")
            except asyncio.TimeoutError:
                return await interaction.followup.send(f"⏰ Time's up! The word was **{target}**.")
        await interaction.followup.send(f"❌ Out of attempts! The word was **{target}**.")

    @app_commands.command(name="makeword", description="Unscramble the letters to make a valid word!")
    async def makeword(self, interaction: discord.Interaction):
        word_bank = ["PYTHON", "DISCORD", "CRICKET", "GAMING", "SERVER", "DEVELOP", "SYSTEM", "PLAYER"]
        original = random.choice(word_bank)
        scrambled_list = list(original)
        random.shuffle(scrambled_list)
        scrambled = "".join(scrambled_list)
        if scrambled == original:
            scrambled = scrambled[::-1]

        await interaction.response.send_message(f"🔤 Unscramble this word: **{scrambled}**! Type your answer in chat.")

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for("message", timeout=30.0, check=check)
            if msg.content.upper() == original:
                await msg.reply(f"🎉 Spot on! The word was **{original}**!")
            else:
                await msg.reply(f"❌ Incorrect! The correct word was **{original}**.")
        except asyncio.TimeoutError:
            await interaction.followup.send(f"⏰ Time's up! The word was **{original}**.")

    @app_commands.command(name="tictactoe", description="Play Tic-Tac-Toe against another member!")
    @app_commands.describe(opponent="The member you want to play against")
    async def tictactoe(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot or opponent == interaction.user:
            return await interaction.response.send_message("❌ You cannot play against bots or yourself!", ephemeral=True)
        
        view = TicTacToeView(interaction.user, opponent)
        await interaction.response.send_message(
            f"🎮 **Tic-Tac-Toe!** {interaction.user.mention} (X) vs {opponent.mention} (O)\nTurn: **{interaction.user.mention}**",
            view=view
        )

    # --- 2. OWOC ECONOMY & SHOP ---
    @app_commands.command(name="work", description="Work to earn coins (or risk losing money on a bad day!).")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def work(self, interaction: discord.Interaction):
        data = get_user(interaction.user.id)
        if random.random() < 0.25:
            loss = random.randint(30, 150)
            data["wallet"] = max(0, data["wallet"] - loss)
            fail_msg = random.choice([
                f"💥 You broke a customer's vase! Paid **{loss} coins** in damages.",
                f"💸 Caught slacking off! Deducted **{loss} coins**.",
                f"📉 Bad day at work! You lost **{loss} coins**.",
                f"🚨 Spilled coffee on the server rig! Fined **{loss} coins**."
            ])
            await interaction.response.send_message(f"{fail_msg}\n💳 Wallet balance: **{data['wallet']} coins**")
        else:
            earnings = random.randint(50, 300)
            data["wallet"] += earnings
            win_msg = random.choice([
                f"💼 Worked hard as a server mod and earned **{earnings} coins**!",
                f"🏏 Coached a cricket squad and got paid **{earnings} coins**!",
                f"🛠️ Fixed bot bugs and received a tip of **{earnings} coins**!",
                f"📦 Delivered packages all day and earned **{earnings} coins**!"
            ])
            await interaction.response.send_message(f"✅ {win_msg}\n💳 Wallet balance: **{data['wallet']} coins**")

    @app_commands.command(name="balance", description="Check your current wallet balance.")
    @app_commands.describe(member="Member to check balance for")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        data = get_user(target.id)
        embed = discord.Embed(title=f"💳 {target.display_name}'s Balance", color=discord.Color.green())
        embed.add_field(name="Wallet", value=f"🪙 **{data['wallet']} coins**", inline=True)
        embed.add_field(name="Inventory Items", value=f"📦 {len(data['inventory'])} items", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop", description="Browse the item shop!")
    async def shop(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛒 NOTTYAMERICA Item Shop", color=discord.Color.gold())
        for item_id, item in SHOP_ITEMS.items():
            embed.add_field(name=f"{item['name']} — 🪙 {item['price']} coins", value=f"ID: `{item_id}` | {item['desc']}", inline=False)
        embed.set_footer(text="Use /buy item_id to purchase!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop!")
    @app_commands.describe(item_id="The ID of the item to purchase (e.g. bat, coin, trophy)")
    async def buy(self, interaction: discord.Interaction, item_id: str):
        item_key = item_id.lower()
        if item_key not in SHOP_ITEMS:
            return await interaction.response.send_message("❌ Invalid item ID! Type `/shop` to view available items.", ephemeral=True)
        
        item = SHOP_ITEMS[item_key]
        data = get_user(interaction.user.id)
        if data["wallet"] < item["price"]:
            return await interaction.response.send_message(f"❌ You need **{item['price']} coins**, but only have **{data['wallet']} coins**.", ephemeral=True)

        data["wallet"] -= item["price"]
        data["inventory"].append(item["name"])
        await interaction.response.send_message(f"🎉 Successfully bought **{item['name']}** for **{item['price']} coins**!\n💳 Balance: **{data['wallet']} coins**")

    @app_commands.command(name="inventory", description="Check your purchased items.")
    async def inventory(self, interaction: discord.Interaction):
        data = get_user(interaction.user.id)
        if not data["inventory"]:
            return await interaction.response.send_message("📦 Your inventory is empty! Use `/shop` to buy items.", ephemeral=True)
        items_list = "\n".join([f"• {item}" for item in data["inventory"]])
        embed = discord.Embed(title=f"📦 {interaction.user.display_name}'s Inventory", description=items_list, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    # --- 3. FUN TESTS & MINIGAMES ---
    @app_commands.command(name="gaytest", description="Calculates the gay percentage!")
    async def gaytest(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        prob = random.randint(1, 100) if random.random() < 0.75 else random.randint(101, 250)
        await interaction.response.send_message(f"🏳️‍🌈 **{target.display_name}** is **{prob}%** gay! {GIF_VIRAT}")

    @app_commands.command(name="lesbiantest", description="Calculates the lesbian percentage!")
    async def lesbiantest(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        prob = random.randint(1, 100) if random.random() < 0.75 else random.randint(101, 250)
        await interaction.response.send_message(f"💜 **{target.display_name}** is **{prob}%** lesbian!")

    @app_commands.command(name="baldtest", description="Calculates how bald someone is!")
    async def baldtest(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        prob = random.randint(1, 100) if random.random() < 0.75 else random.randint(101, 250)
        await interaction.response.send_message(f"🧑‍🦲 **{target.display_name}** is **{prob}%** bald!")

    @app_commands.command(name="coinflip", description="Flip a coin!")
    async def coinflip(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🪙 The coin landed on: **{random.choice(['Heads 🪙', 'Tails 🪙'])}**!")

    @app_commands.command(name="8ball", description="Ask the Magic 8-Ball a question!")
    async def eightball(self, interaction: discord.Interaction, question: str):
        reply = random.choice(["It is certain.", "Without a doubt.", "Reply hazy, try again.", "Don't count on it.", "My sources say no.", "Outlook good!"])
        await interaction.response.send_message(f"❓ **Question:** {question}\n🎱 **8-Ball:** {reply}")

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors with the bot!")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock 🪨", value="rock"),
        app_commands.Choice(name="Paper 📄", value="paper"),
        app_commands.Choice(name="Scissors ✂️", value="scissors")
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        bot_choice = random.choice(["rock", "paper", "scissors"])
        user_choice = choice.value
        res = "It's a tie! 🤝" if user_choice == bot_choice else "You win! 🎉" if (
            (user_choice == "rock" and bot_choice == "scissors") or 
            (user_choice == "paper" and bot_choice == "rock") or 
            (user_choice == "scissors" and bot_choice == "paper")
        ) else "I win! 😈"
        await interaction.response.send_message(f"You chose **{user_choice.title()}**, I chose **{bot_choice.title()}**. {res}")

    # --- 4. STREAMLINED HAND CRICKET SUITE ---
    @app_commands.command(name="cricket", description="Start a Hand Cricket match lobby!")
    @app_commands.describe(overs="Number of overs", tournament_mode="Enable tournament mode (2 batters)?")
    @app_commands.choices(tournament_mode=[
        app_commands.Choice(name="Yes", value="yes"),
        app_commands.Choice(name="No", value="no")
    ])
    async def cricket(self, interaction: discord.Interaction, overs: int, tournament_mode: str):
        if interaction.channel.id in ACTIVE_LOBBIES:
            return await interaction.response.send_message("❌ There is already an active cricket lobby in this channel!", ephemeral=True)

        host = interaction.user
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
            "future": asyncio.get_running_loop().create_future()
        }
        ACTIVE_LOBBIES[interaction.channel.id] = match_session

        embed = discord.Embed(title="🏏 Cricket Match LOBBY", color=discord.Color.gold())
        embed.add_field(name="Host", value=host.mention, inline=False)
        embed.add_field(name="Overs", value=str(overs), inline=True)
        embed.add_field(name="Tournament Mode", value="Yes (2 Batters)" if match_session["tournament_mode"] else "No", inline=True)
        embed.add_field(name="Team A", value=host.display_name, inline=True)
        embed.add_field(name="Team B", value="Empty", inline=True)

        async def update_embed():
            embed.set_field_at(3, name=match_session["team_a_name"], value="\n".join([m.display_name for m in match_session["team_a"]]) or "Empty", inline=True)
            embed.set_field_at(4, name=match_session["team_b_name"], value="\n".join([m.display_name for m in match_session["team_b"]]) or "Empty", inline=True)
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
        except asyncio.TimeoutError:
            pass
        finally:
            if interaction.channel.id in ACTIVE_LOBBIES:
                del ACTIVE_LOBBIES[interaction.channel.id]

    @app_commands.command(name="addbot", description="Add a bot player to a team in the lobby.")
    @app_commands.choices(team=[app_commands.Choice(name="Team A", value="a"), app_commands.Choice(name="Team B", value="b")])
    async def addbot(self, interaction: discord.Interaction, team: str):
        lobby = ACTIVE_LOBBIES.get(interaction.channel.id)
        if not lobby or lobby["started"]:
            return await interaction.response.send_message("❌ No active lobby in this channel!", ephemeral=True)
        if interaction.user != lobby["host"]:
            return await interaction.response.send_message("❌ Only the host can add bots!", ephemeral=True)
        
        bot_name = f"Bot_{random.randint(100, 999)}"
        # Mocking a bot member container
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
        else:
            lobby["team_b"].append(dummy)

        await interaction.response.send_message(f"🤖 Added **{bot_name}** to the lobby!", ephemeral=True)
        await lobby["update_embed"]()

    @app_commands.command(name="changeteamname", description="Change the name of a team in the lobby.")
    @app_commands.choices(team=[app_commands.Choice(name="Team A", value="a"), app_commands.Choice(name="Team B", value="b")])
    async def changeteamname(self, interaction: discord.Interaction, team: str, new_name: str):
        lobby = ACTIVE_LOBBIES.get(interaction.channel.id)
        if not lobby or lobby["started"]:
            return await interaction.response.send_message("❌ No active lobby in this channel!", ephemeral=True)
        if interaction.user != lobby["host"]:
            return await interaction.response.send_message("❌ Only the host can rename teams!", ephemeral=True)

        if team == "a":
            lobby["team_a_name"] = new_name
        else:
            lobby["team_b_name"] = new_name

        await interaction.response.send_message(f"✅ Team renamed to **{new_name}**!", ephemeral=True)
        await lobby["update_embed"]()

    @app_commands.command(name="shuffle", description="Randomly shuffle players between teams.")
    async def shuffle(self, interaction: discord.Interaction):
        lobby = ACTIVE_LOBBIES.get(interaction.channel.id)
        if not lobby or lobby["started"]:
            return await interaction.response.send_message("❌ No active lobby in this channel!", ephemeral=True)
        if interaction.user != lobby["host"]:
            return await interaction.response.send_message("❌ Only the host can shuffle teams!", ephemeral=True)

        all_players = lobby["team_a"] + lobby["team_b"]
        random.shuffle(all_players)
        mid = len(all_players) // 2
        lobby["team_a"] = all_players[:mid] or [all_players[0]]
        lobby["team_b"] = all_players[mid:] if mid > 0 else all_players[1:]

        await interaction.response.send_message("🔀 Teams have been randomly shuffled!", ephemeral=True)
        await lobby["update_embed"]()

    @app_commands.command(name="stop", description="Stop and disband an active cricket match lobby.")
    async def stop(self, interaction: discord.Interaction):
        lobby = ACTIVE_LOBBIES.get(interaction.channel.id)
        if not lobby:
            return await interaction.response.send_message("❌ No active lobby to stop in this channel!", ephemeral=True)
        if interaction.user != lobby["host"] and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Only the host or staff can stop the lobby!", ephemeral=True)

        lobby["active"] = False
        if not lobby["started"]:
            lobby["future"].set_result(False)
        del ACTIVE_LOBBIES[interaction.channel.id]
        await interaction.response.send_message("🛑 Cricket match lobby has been successfully stopped and disbanded.")


async def setup(bot):
    await bot.add_cog(Minigames(bot))
