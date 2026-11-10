import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import update_user_stats, get_user_stats


class LobbyControlView(discord.ui.View):
    """Exact interactive buttons matching the game dashboard interface."""

    def __init__(self, lobby_data):
        super().__init__(timeout=None)
        self.lobby = lobby_data

    @discord.ui.button(
        emoji="🏏",
        style=discord.ButtonStyle.success,
        custom_id="btn_batting",
        row=0,
    )
    async def batting_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "Batting controls activated. Waiting for match phase...",
            ephemeral=True,
        )

    @discord.ui.button(
        emoji="🎾",
        style=discord.ButtonStyle.danger,
        custom_id="btn_bowling",
        row=0,
    )
    async def bowling_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "Bowling controls activated. Waiting for match phase...",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Playerlist",
        style=discord.ButtonStyle.primary,
        custom_id="btn_playerlist",
        row=1,
    )
    async def playerlist_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        t_a_squad = "\n".join(
            [
                f"• {p if isinstance(p, str) else p.display_name}"
                for p in self.lobby["team_a"]
            ]
        )
        t_b_squad = "\n".join(
            [
                f"• {p if isinstance(p, str) else p.display_name}"
                for p in self.lobby["team_b"]
            ]
        )

        embed = discord.Embed(
            title="📋 Match Playerlist", color=discord.Color.dark_purple()
        )
        embed.add_field(
            name=f"Team {self.lobby['team_a_name']}",
            value=t_a_squad or "No players",
            inline=True,
        )
        embed.add_field(
            name=f"Team {self.lobby['team_b_name']}",
            value=t_b_squad or "No players",
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        emoji="⏩",
        style=discord.ButtonStyle.success,
        custom_id="btn_next_player",
        row=1,
    )
    async def next_player_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "Skipping to next active player turn...", ephemeral=True
        )


class TossView(discord.ui.View):

    def __init__(self, lobby_data):
        super().__init__(timeout=30)
        self.lobby = lobby_data

    @discord.ui.button(
        label="Heads",
        style=discord.ButtonStyle.primary,
        custom_id="toss_heads",
    )
    async def heads(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_toss(interaction, "Heads")

    @discord.ui.button(
        label="Tails",
        style=discord.ButtonStyle.primary,
        custom_id="toss_tails",
    )
    async def tails(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_toss(interaction, "Tails")

    async def process_toss(self, interaction: discord.Interaction, choice: str):
        captain_a = self.lobby["captain_a"]
        if interaction.user.id != captain_a:
            return await interaction.response.send_message(
                "Only Team A Captain can choose for the toss!", ephemeral=True
            )

        outcome = random.choice(["Heads", "Tails"])
        won = choice.lower() == outcome.lower()
        winning_team = (
            self.lobby["team_a_name"] if won else self.lobby["team_b_name"]
        )
        winning_captain = (
            self.lobby["captain_a"] if won else self.lobby["captain_b"]
        )

        self.lobby["toss_winner"] = winning_team
        self.lobby["toss_winner_captain"] = winning_captain

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="🪙 Coin Toss",
            description=(
                f"Coin landed on **{outcome}**!\n**{winning_team}** won the toss."
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

        decision_view = TossDecisionView(self.lobby)
        if isinstance(winning_captain, int):
            await interaction.channel.send(
                f"<@{winning_captain}> has won the toss. Choose bat or bowl?",
                view=decision_view,
            )
        else:
            choice = random.choice(["bat", "bowl"])
            self.lobby["batting_first"] = (
                winning_team
                if choice == "bat"
                else (
                    self.lobby["team_b_name"]
                    if winning_team == self.lobby["team_a_name"]
                    else self.lobby["team_a_name"]
                )
            )
            await interaction.channel.send(
                f"**{winning_team}** (Bot) won the toss and decided to **{choice}** first!\nUse `/start` to start the game."
            )


class TossDecisionView(discord.ui.View):

    def __init__(self, lobby_data):
        super().__init__(timeout=30)
        self.lobby = lobby_data

    @discord.ui.button(
        label="Bat", style=discord.ButtonStyle.success, custom_id="decide_bat"
    )
    async def bat(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.lobby["toss_winner_captain"]:
            return await interaction.response.send_message(
                "Only the toss winner can decide!", ephemeral=True
            )
        self.lobby["batting_first"] = self.lobby["toss_winner"]
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=(
                f"**{self.lobby['toss_winner']}** has decided to **bat** first!"
                " Now use `/start` to start the game."
            ),
            view=self,
        )

    @discord.ui.button(
        label="Bowl", style=discord.ButtonStyle.danger, custom_id="decide_bowl"
    )
    async def bowl(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.lobby["toss_winner_captain"]:
            return await interaction.response.send_message(
                "Only the toss winner can decide!", ephemeral=True
            )
        other_team = (
            self.lobby["team_b_name"]
            if self.lobby["toss_winner"] == self.lobby["team_a_name"]
            else self.lobby["team_a_name"]
        )
        self.lobby["batting_first"] = other_team
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=(
                f"**{self.lobby['toss_winner']}** has decided to **bowl** first!"
                " Now use `/start` to start the game."
            ),
            view=self,
        )


class CatchDMView(discord.ui.View):

    def __init__(self, fielder_id: int, correct_option: int, future: asyncio.Future):
        super().__init__(timeout=12)
        self.fielder_id = fielder_id
        self.correct_option = correct_option
        self.future = future

        opts = [1, 2, 3]
        for opt in opts:
            self.add_item(CatchOptionButton(opt, opt == correct_option))


class CatchOptionButton(discord.ui.Button):

    def __init__(self, val: int, is_correct: bool):
        super().__init__(
            label=str(val), style=discord.ButtonStyle.primary, custom_id=f"catch_{val}"
        )
        self.val = val
        self.is_correct = is_correct

    async def callback(self, interaction: discord.Interaction):
        view: CatchDMView = self.view
        if interaction.user.id != view.fielder_id:
            return await interaction.response.send_message(
                "This catch isn't for you!", ephemeral=True
            )

        for child in view.children:
            child.disabled = True

        if self.is_correct:
            await interaction.response.edit_message(
                content="👐 **CATCH TAKEN!** Excellent reaction!", view=view
            )
            if not view.future.done():
                view.future.set_result(True)
        else:
            await interaction.response.edit_message(
                content="❌ **DROPPED!** You guessed the wrong spot.", view=view
            )
            if not view.future.done():
                view.future.set_result(False)
        view.stop()


class PlayActionView(discord.ui.View):

    def __init__(self, player_id: int, last_action: int):
        super().__init__(timeout=15)
        self.player_id = player_id
        self.last_action = last_action
        self.selected_value = None

    @discord.ui.button(
        label="1", style=discord.ButtonStyle.secondary, row=0
    )
    async def btn1(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 1)

    @discord.ui.button(
        label="2", style=discord.ButtonStyle.secondary, row=0
    )
    async def btn2(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 2)

    @discord.ui.button(
        label="3", style=discord.ButtonStyle.secondary, row=0
    )
    async def btn3(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 3)

    @discord.ui.button(
        label="4", style=discord.ButtonStyle.primary, row=1
    )
    async def btn4(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 4)

    @discord.ui.button(
        label="5", style=discord.ButtonStyle.secondary, row=1
    )
    async def btn5(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 5)

    @discord.ui.button(
        label="6", style=discord.ButtonStyle.success, row=1
    )
    async def btn6(self, interaction: discord.Interaction, button):
        await self.process_click(interaction, 6)

    async def process_click(
        self, interaction: discord.Interaction, value: int
    ):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message(
                "Not your control panel!", ephemeral=True
            )
        self.selected_value = value
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"Selected **{value}**", view=self
        )
        self.stop()

    async def on_timeout(self):
        if self.selected_value is None:
            self.selected_value = self.last_action if self.last_action != 0 else 1
        self.stop()


class CricketCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lobbies = {}

    def build_match_status_embed(self, lobby_data) -> discord.Embed:
        """Constructs the exact match status dashboard matching Screenshot 5."""
        embed = discord.Embed(
            title="Match Status", color=discord.Color.from_rgb(32, 34, 37)
        )
        embed.set_author(
            name="Not Nuked Yet",
            icon_url=self.bot.user.display_avatar.url
            if self.bot.user
            else None,
        )

        embed.add_field(name="Innings", value="ONE", inline=True)
        embed.add_field(
            name="Overs", value=f"0.0 / {lobby_data['overs']}.0", inline=True
        )
        embed.add_field(
            name="Host", value=lobby_data["host"].name, inline=True
        )

        embed.add_field(
            name="Timeline",
            value="----------------",
            inline=False,
        )

        embed.add_field(
            name=f"{lobby_data['team_a_name']}",
            value="0/0 (0.0 overs) (RR: 0.0)",
            inline=False,
        )
        embed.add_field(
            name=f"{lobby_data['team_b_name']}",
            value="0/0 (0.0 overs) (RR: 0.0)",
            inline=False,
        )

        embed.add_field(
            name="Batter",
            value=f"{lobby_data['host'].name}: 0 (0) runs",
            inline=False,
        )
        embed.add_field(
            name="Bowler",
            value="Bot2: 0 - 0 (0.0 overs)",
            inline=False,
        )

        # Stadium Preview Banner
        embed.set_image(
            url="https://media.tenor.com/images/3a958e82110c4d320921e42dd503d526/tenor.gif"
        )
        embed.set_footer(text="LIVE ●")

        return embed

    @app_commands.command(
        name="create", description="Create a Hand Cricket match lobby."
    )
    async def create_lobby(
        self,
        interaction: discord.Interaction,
        overs: int = 2,
        tournament_mode: bool = False,
    ):
        channel_id = interaction.channel_id
        if channel_id in self.lobbies:
            return await interaction.response.send_message(
                "A match lobby is already active in this channel!", ephemeral=True
            )

        self.lobbies[channel_id] = {
            "host": interaction.user,
            "overs": overs,
            "tournament_mode": tournament_mode,
            "players": [interaction.user],
            "team_a": [interaction.user],
            "team_b": [],
            "team_a_name": "baldness",
            "team_b_name": "proness",
            "captain_a": interaction.user.id,
            "captain_b": None,
            "locked": False,
            "batting_first": None,
            "last_actions": {},
        }

        embed = self.build_match_status_embed(self.lobbies[channel_id])
        view = LobbyControlView(self.lobbies[channel_id])

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="addbots", description="Add bots to your cricket match."
    )
    @app_commands.describe(
        bot_count="The number of Bots to add.",
        names="Comma-separated bot names.",
    )
    async def addbots(
        self,
        interaction: discord.Interaction,
        bot_count: int = None,
        names: str = None,
    ):
        if (bot_count is not None and names is not None) or (
            bot_count is None and names is None
        ):
            return await interaction.response.send_message(
                "Either mention the 'bot_count' parameter or mention the 'names' of bots. Don't do both or neither! ❌",
                ephemeral=True,
            )

        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No lobby active in this channel.", ephemeral=True
            )

        bot_list = []
        if bot_count is not None:
            for i in range(1, bot_count + 1):
                bot_list.append(f"Bot{i}")
        else:
            bot_list = [n.strip() for n in names.split(",") if n.strip()]

        for bname in bot_list:
            lobby["players"].append(bname)
            if len(lobby["team_a"]) <= len(lobby["team_b"]):
                lobby["team_a"].append(bname)
            else:
                lobby["team_b"].append(bname)
                if not lobby["captain_b"]:
                    lobby["captain_b"] = bname

        await interaction.response.send_message(
            f"Successfully added {len(bot_list)} bots. ✅"
        )

    @app_commands.command(
        name="lobby", description="Show the Multiplayer match lobby."
    )
    @app_commands.describe(show_me_only="Show this message to you only.")
    async def show_lobby(
        self, interaction: discord.Interaction, show_me_only: bool = False
    ):
        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No active lobby.", ephemeral=True
            )

        embed = self.build_match_status_embed(lobby)
        view = LobbyControlView(lobby)

        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=show_me_only
        )

    @app_commands.command(
        name="toss", description="Start the toss for the match."
    )
    async def trigger_toss(self, interaction: discord.Interaction):
        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No active lobby.", ephemeral=True
            )

        if not lobby["captain_b"]:
            lobby["captain_b"] = (
                lobby["team_b"][0] if lobby["team_b"] else "Opponent Captain"
            )

        cap_a_mention = (
            f"<@{lobby['captain_a']}>"
            if isinstance(lobby["captain_a"], int)
            else lobby["captain_a"]
        )
        view = TossView(lobby)
        await interaction.response.send_message(
            f"Starting toss, **{lobby['team_a_name']}** captain {cap_a_mention} choose heads or tails?",
            view=view,
        )

    @app_commands.command(
        name="start", description="Starts a Multiplayer or Run Race match."
    )
    async def start_game(self, interaction: discord.Interaction):
        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No active lobby found.", ephemeral=True
            )
        if not lobby.get("batting_first"):
            return await interaction.response.send_message(
                "Perform the toss first using `/toss`!", ephemeral=True
            )

        await interaction.response.send_message(
            "Match is starting! Directing controls..."
        )
        await self.run_match_loop(interaction.channel, lobby)

    async def get_player_input(
        self, channel, player, role: str, last_action: int
    ) -> int:
        if isinstance(player, str):
            await asyncio.sleep(1)
            return random.randint(1, 6)

        try:
            view = PlayActionView(player.id, last_action)
            await player.send(
                f"You are **{role}**! Select your action (Respond within 15 seconds):",
                view=view,
            )
            await view.wait()
            return view.selected_value
        except Exception:
            return last_action if last_action != 0 else 1

    async def handle_catch_system(
        self, channel, bowling_team: list, batter_name: str
    ) -> bool:
        fielders = [p for p in bowling_team if isinstance(p, discord.User)]
        if not fielders:
            return True

        selected_fielder = random.choice(fielders)
        correct_spot = random.randint(1, 3)

        await channel.send(
            f"🚨 **CHANCE OF WICKET!**\nA catch opportunity is coming toward {selected_fielder.mention}!\nIf {selected_fielder.mention} takes this catch, **{batter_name}** will be out!"
        )

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        view = CatchDMView(selected_fielder.id, correct_spot, future)

        try:
            await selected_fielder.send(
                f"⚡ **CATCH OPPORTUNITY!** Pick the correct spot (1, 2, or 3) to catch out **{batter_name}**:",
                view=view,
            )
            result = await asyncio.wait_for(future, timeout=12.0)
            return result
        except (asyncio.TimeoutError, Exception):
            await channel.send(
                f"❌ {selected_fielder.mention} couldn't reach the ball in time! Catch dropped."
            )
            return False

    async def run_match_loop(self, channel, lobby):
        batting_team_name = lobby["batting_first"]
        bowling_team_name = (
            lobby["team_b_name"]
            if batting_team_name == lobby["team_a_name"]
            else lobby["team_a_name"]
        )

        batting_squad = list(
            lobby["team_a"]
            if batting_team_name == lobby["team_a_name"]
            else lobby["team_b"]
        )
        bowling_squad = list(
            lobby["team_b"]
            if batting_team_name == lobby["team_a_name"]
            else lobby["team_a"]
        )

        max_balls = lobby["overs"] * 6
        total_runs = 0
        wickets = 0
        balls_bowled = 0

        striker_idx = 0
        non_striker_idx = 1 if len(batting_squad) > 1 else 0

        await channel.send(
            f"🏟️ **Innings ONE Started!**\nBatting: **{batting_team_name}** | Bowling: **{bowling_team_name}**"
        )

        while balls_bowled < max_balls and wickets < len(batting_squad):
            striker = batting_squad[striker_idx]
            bowler = bowling_squad[balls_bowled % len(bowling_squad)]

            striker_name = (
                striker if isinstance(striker, str) else striker.display_name
            )
            bowler_name = (
                bowler if isinstance(bowler, str) else bowler.display_name
            )

            last_bat = lobby["last_actions"].get(striker_name, 0)
            last_bowl = lobby["last_actions"].get(bowler_name, 0)

            bat_move = await self.get_player_input(
                channel, striker, "BATTER", last_bat
            )
            bowl_move = await self.get_player_input(
                channel, bowler, "BOWLER", last_bowl
            )

            lobby["last_actions"][striker_name] = bat_move
            lobby["last_actions"][bowler_name] = bowl_move

            balls_bowled += 1

            if bat_move == bowl_move:
                is_out = True
                if lobby["tournament_mode"]:
                    is_out = await self.handle_catch_system(
                        channel, bowling_squad, striker_name
                    )

                if is_out:
                    wickets += 1
                    await channel.send(
                        f"🔴 **WICKET!** {striker_name} is OUT! Both chose **{bat_move}**."
                    )
                    striker_idx = max(striker_idx, non_striker_idx) + 1
                else:
                    total_runs += bat_move
                    await channel.send(
                        f"🏏 Catch dropped! {striker_name} scores **{bat_move}** runs!"
                    )
            else:
                total_runs += bat_move
                await channel.send(
                    f"⚡ **{striker_name}** played **{bat_move}** | **{bowler_name}** bowled **{bowl_move}** | Runs: **{total_runs}/{wickets}** ({balls_bowled//6}.{balls_bowled%6} overs)"
                )

                if bat_move % 2 != 0 and non_striker_idx < len(batting_squad):
                    striker_idx, non_striker_idx = non_striker_idx, striker_idx

            if balls_bowled % 6 == 0 and non_striker_idx < len(batting_squad):
                striker_idx, non_striker_idx = non_striker_idx, striker_idx

        target = total_runs + 1
        await channel.send(
            f"🏁 **Innings Over!**\n**{batting_team_name}** scored **{total_runs}/{wickets}** in {balls_bowled//6}.{balls_bowled%6} overs.\nTarget for **{bowling_team_name}**: **{target}** runs."
        )

        del self.lobbies[channel.id]


async def setup(bot: commands.Bot):
    await bot.add_cog(CricketCog(bot))
