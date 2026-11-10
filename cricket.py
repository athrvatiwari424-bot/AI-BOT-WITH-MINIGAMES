import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import update_user_stats, get_user_stats


class BotPlayer:
    def __init__(self, name: str):
        self.name = name
        self.display_name = name
        self.id = name

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class LobbyJoinView(discord.ui.View):
    def __init__(self, lobby_data):
        super().__init__(timeout=None)
        self.lobby = lobby_data

    @discord.ui.button(
        label="Join Match",
        style=discord.ButtonStyle.success,
        custom_id="btn_join_lobby",
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user in self.lobby["players"]:
            return await interaction.response.send_message(
                "You are already in this lobby!", ephemeral=True
            )

        self.lobby["players"].append(interaction.user)
        if len(self.lobby["team_a"]) <= len(self.lobby["team_b"]):
            self.lobby["team_a"].append(interaction.user)
        else:
            self.lobby["team_b"].append(interaction.user)
            if not self.lobby["captain_b"]:
                self.lobby["captain_b"] = interaction.user.id

        embed = interaction.message.embeds[0]
        t_a_squad = (
            "\n".join([p.display_name for p in self.lobby["team_a"]])
            or "None"
        )
        t_b_squad = (
            "\n".join([p.display_name for p in self.lobby["team_b"]])
            or "None"
        )

        embed.clear_fields()
        embed.add_field(name="Host", value=self.lobby["host"].mention, inline=False)
        embed.add_field(
            name="Lobby Info",
            value=(
                f"Players: {len(self.lobby['players'])}\nOvers:"
                f" {self.lobby['overs']}\nTournament Mode:"
                f" {'✅' if self.lobby['tournament_mode'] else '❌'}"
            ),
            inline=False,
        )
        embed.add_field(name="Team A", value=t_a_squad, inline=True)
        embed.add_field(name="Team B", value=t_b_squad, inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(
            f"{interaction.user.mention} joined the match lobby! ✅",
            ephemeral=True,
        )


class TossView(discord.ui.View):
    def __init__(self, lobby_data):
        super().__init__(timeout=30)
        self.lobby = lobby_data

    @discord.ui.button(
        label="Heads", style=discord.ButtonStyle.primary, custom_id="toss_heads"
    )
    async def heads(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_toss(interaction, "Heads")

    @discord.ui.button(
        label="Tails", style=discord.ButtonStyle.primary, custom_id="toss_tails"
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
            title="🪙 Coin Toss Result",
            description=(
                f"Coin landed on **{outcome}**!\n**{winning_team}** won the toss!"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

        decision_view = TossDecisionView(self.lobby)
        if isinstance(winning_captain, int):
            await interaction.channel.send(
                f"<@{winning_captain}> has won the toss. Choose bat or bowl:",
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
                f"**{winning_team}** (Bot) won the toss and decided to **{choice}** first!\nNow use `/start` to begin the match."
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
                " Now use `/start` to begin the match."
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
                " Now use `/start` to begin the match."
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


class CricketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lobbies = {}

    def build_match_embed(
        self,
        match_title: str,
        innings: str,
        overs_str: str,
        host_name: str,
        timeline: list,
        team_a_txt: str,
        team_b_txt: str,
        batter_txt: str,
        bowler_txt: str,
    ) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 37))
        embed.set_author(name=match_title, icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
        
        embed.add_field(name="Innings", value=innings, inline=True)
        embed.add_field(name="Overs", value=overs_str, inline=True)
        embed.add_field(name="Host", value=host_name, inline=True)

        timeline_display = " ".join(timeline) if timeline else "----------------"
        embed.add_field(name="Timeline", value=timeline_display, inline=False)
        
        embed.add_field(name="Team A", value=team_a_txt, inline=False)
        embed.add_field(name="Team B", value=team_b_txt, inline=False)
        embed.add_field(name="Batter", value=batter_txt, inline=False)
        embed.add_field(name="Bowler", value=bowler_txt, inline=False)

        embed.set_image(url="https://media.tenor.com/images/3a958e82110c4d320921e42dd503d526/tenor.gif")
        embed.set_footer(text="LIVE ●")
        return embed

    @app_commands.command(name="create", description="Create a Hand Cricket match lobby.")
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

        guild_name = interaction.guild.name if interaction.guild else "Cricket Match"
        self.lobbies[channel_id] = {
            "host": interaction.user,
            "overs": overs,
            "tournament_mode": tournament_mode,
            "players": [interaction.user],
            "team_a": [interaction.user],
            "team_b": [],
            "team_a_name": "Team A",
            "team_b_name": "Team B",
            "captain_a": interaction.user.id,
            "captain_b": None,
            "batting_first": None,
            "last_actions": {},
        }

        embed = discord.Embed(
            title=f"🏏 {guild_name} - Match Lobby",
            description="Click the button below to join the match team!",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="Host", value=interaction.user.mention, inline=False)
        embed.add_field(
            name="Lobby Info",
            value=f"Players: 1\nOvers: {overs}\nTournament Mode: {'✅' if tournament_mode else '❌'}",
            inline=False,
        )
        embed.add_field(name="Team A", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Team B", value="None yet", inline=True)

        view = LobbyJoinView(self.lobbies[channel_id])
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="join", description="Join the active multiplayer lobby.")
    async def join_lobby(self, interaction: discord.Interaction):
        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No active lobby in this channel.", ephemeral=True
            )
        if interaction.user in lobby["players"]:
            return await interaction.response.send_message(
                "You are already in the lobby!", ephemeral=True
            )

        lobby["players"].append(interaction.user)
        if len(lobby["team_a"]) <= len(lobby["team_b"]):
            lobby["team_a"].append(interaction.user)
        else:
            lobby["team_b"].append(interaction.user)
            if not lobby["captain_b"]:
                lobby["captain_b"] = interaction.user.id

        await interaction.response.send_message(
            f"{interaction.user.mention} has joined the match via `/join`! ✅"
        )

    @app_commands.command(name="addbots", description="Add bots to your cricket match.")
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
            bot_obj = BotPlayer(bname)
            lobby["players"].append(bot_obj)
            if len(lobby["team_a"]) <= len(lobby["team_b"]):
                lobby["team_a"].append(bot_obj)
            else:
                lobby["team_b"].append(bot_obj)
                if not lobby["captain_b"]:
                    lobby["captain_b"] = bot_obj.id

        await interaction.response.send_message(
            f"Successfully added {len(bot_list)} bot(s) to the match. ✅"
        )

    @app_commands.command(name="toss", description="Start the toss for the match.")
    async def trigger_toss(self, interaction: discord.Interaction):
        lobby = self.lobbies.get(interaction.channel_id)
        if not lobby:
            return await interaction.response.send_message(
                "No active lobby.", ephemeral=True
            )

        if not lobby["captain_b"]:
            lobby["captain_b"] = (
                lobby["team_b"][0].id if lobby["team_b"] else "Opponent Captain"
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

    @app_commands.command(name="start", description="Starts the match.")
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
            "Match is starting! Initializing live dashboard..."
        )
        await self.run_full_match(interaction.channel, lobby)

    async def get_typing_input(
        self, player, role: str, last_action: int, opponent_last_action: int, current_score: int, is_innings_two: bool, runs_needed: int, balls_left: int, wickets_left: int
    ) -> int:
        if isinstance(player, BotPlayer) or isinstance(player, str):
            await asyncio.sleep(1)
            return random.randint(1, 6)

        try:
            embed = discord.Embed(title="🏏 Hand Cricket Match Status", color=discord.Color.dark_purple())
            embed.add_field(name="Opponent's Last Action", value=str(opponent_last_action), inline=False)
            embed.add_field(name="Current Score", value=str(current_score), inline=False)
            
            if is_innings_two:
                embed.add_field(
                    name="Run Chase Status",
                    value=f"Runs left: {runs_needed} | Balls left: {balls_left} | Wickets left: {wickets_left}",
                    inline=False,
                )

            embed.description = f"You are **{role}**! Type a number between **1 and 6** in your DMs within 15 seconds:"
            
            dm_msg = await player.send(embed=embed)

            def check(m):
                return m.author.id == player.id and isinstance(m.channel, discord.DMChannel) and m.content.isdigit() and 1 <= int(m.content) <= 6

            msg = await self.bot.wait_for('message', timeout=15.0, check=check)
            return int(msg.content)
        except asyncio.TimeoutError:
            try:
                await player.send("⌛ You didn't respond in time, repeating previous action.")
            except Exception:
                pass
            return last_action if last_action != 0 else 1
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

    async def send_dm_embed_safe(self, player, title: str, description: str):
        if isinstance(player, discord.User) or isinstance(player, discord.Member):
            try:
                embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
                await player.send(embed=embed)
            except Exception:
                pass

    async def play_innings(self, channel, lobby, batting_squad, bowling_squad, batting_team_name, bowling_team_name, innings_label, is_innings_two: bool = False, target_score=None):
        max_balls = lobby["overs"] * 6
        total_runs = 0
        wickets = 0
        balls_bowled = 0
        timeline = []
        striker_idx = 0
        non_striker_idx = 1 if len(batting_squad) > 1 else 0

        guild_name = channel.guild.name if channel.guild else "Cricket Match"
        embed = self.build_match_embed(
            match_title=guild_name,
            innings=innings_label,
            overs_str=f"0.0 / {lobby['overs']}.0",
            host_name=lobby["host"].name,
            timeline=timeline,
            team_a_txt=f"{batting_team_name}: 0/0 (0.0 overs)",
            team_b_txt=f"{bowling_team_name}: 0/0 (0.0 overs)",
            batter_txt="Starting...",
            bowler_txt="Ready...",
        )
        status_msg = await channel.send(embed=embed)

        while balls_bowled < max_balls and wickets < len(batting_squad):
            if target_score is not None and total_runs >= target_score:
                break

            striker = batting_squad[striker_idx]
            bowler = bowling_squad[balls_bowled % len(bowling_squad)]

            striker_name = striker.display_name if hasattr(striker, 'display_name') else str(striker)
            bowler_name = bowler.display_name if hasattr(bowler, 'display_name') else str(bowler)

            last_bat = lobby["last_actions"].get(striker_name, 0)
            last_bowl = lobby["last_actions"].get(bowler_name, 0)

            balls_remaining = max_balls - balls_bowled
            wickets_remaining = len(batting_squad) - wickets
            runs_needed = (target_score - total_runs) if target_score else 0

            bat_task = self.get_typing_input(
                striker, "BATTER", last_bat, last_bowl, total_runs, is_innings_two, runs_needed, balls_remaining, wickets_remaining
            )
            bowl_task = self.get_typing_input(
                bowler, "BOWLER", last_bowl, last_bat, total_runs, is_innings_two, runs_needed, balls_remaining, wickets_remaining
            )

            bat_move, bowl_move = await asyncio.gather(bat_task, bowl_task)

            lobby["last_actions"][striker_name] = bat_move
            lobby["last_actions"][bowler_name] = bowl_move

            balls_bowled += 1
            overs_completed = f"{balls_bowled//6}.{balls_bowled%6}"
            rr = round(total_runs / (balls_bowled / 6), 2) if balls_bowled > 0 else 0.0

            if bat_move == bowl_move:
                is_out = True
                if lobby["tournament_mode"]:
                    is_out = await self.handle_catch_system(channel, bowling_squad, striker_name)

                if is_out:
                    wickets += 1
                    timeline.append("🔴 W")
                    await channel.send(f"🔴 **WICKET!** {striker_name} is OUT! Both played **{bat_move}**.")
                    
                    # CORRECTED DM NOTIFICATIONS (Batter sees opponent is out, Bowler sees opponent's score)
                    is_team_all_out = (wickets >= len(batting_squad))
                    out_status_text = "Their team is all out! Innings over." if is_team_all_out else "Wicket fallen!"

                    await self.send_dm_embed_safe(
                        striker, 
                        "🔴 Wicket Update", 
                        f"Opponent is out!\nOpponent's last action -> {bowl_move}\nScore: {total_runs} ({balls_bowled})\n{out_status_text}"
                    )
                    await self.send_dm_embed_safe(
                        bowler, 
                        "🔴 Wicket Update", 
                        f"Batter is out!\nOpponent's last action -> {bat_move}\nOpponent score: {total_runs} ({balls_bowled})\n{out_status_text}"
                    )

                    striker_idx = max(striker_idx, non_striker_idx) + 1
                else:
                    total_runs += bat_move
                    timeline.append(str(bat_move))
                    await channel.send(f"🏏 Catch dropped! {striker_name} scores **{bat_move}** runs!")
            else:
                total_runs += bat_move
                timeline.append(str(bat_move))
                await channel.send(f"⚡ **{striker_name}** played **{bat_move}** | **{bowler_name}** bowled **{bowl_move}** | Runs: **{total_runs}/{wickets}** ({overs_completed} overs)")

                if bat_move % 2 != 0 and non_striker_idx < len(batting_squad):
                    striker_idx, non_striker_idx = non_striker_idx, striker_idx

            if balls_bowled % 6 == 0 and non_striker_idx < len(batting_squad):
                striker_idx, non_striker_idx = non_striker_idx, striker_idx
                await self.send_dm_embed_safe(bowler, "Over Finished", "Your over is finished!")

            updated_embed = self.build_match_embed(
                match_title=guild_name,
                innings=innings_label,
                overs_str=f"{overs_completed} / {lobby['overs']}.0",
                host_name=lobby["host"].name,
                timeline=timeline[-10:],
                team_a_txt=f"{total_runs}/{wickets} ({overs_completed} overs) (RR: {rr})",
                team_b_txt="Target / Stats tracking...",
                batter_txt=f"{striker_name}: {total_runs} runs",
                bowler_txt=f"{bowler_name}: {wickets} wickets",
            )
            await status_msg.edit(embed=updated_embed)

        return total_runs, wickets

    async def run_full_match(self, channel, lobby):
        team_a_squad = lobby["team_a"]
        team_b_squad = lobby["team_b"]

        team_a_name = lobby["team_a_name"]
        team_b_name = lobby["team_b_name"]

        batting_first = lobby["batting_first"]
        
        if batting_first == team_a_name:
            bat1_squad, bowl1_squad = team_a_squad, team_b_squad
            name1, name2 = team_a_name, team_b_name
        else:
            bat1_squad, bowl1_squad = team_b_squad, team_a_squad
            name1, name2 = team_b_name, team_a_name

        await channel.send(f"🏟️ **Innings ONE Started!**\nBatting: **{name1}** | Bowling: **{name2}**")
        score1, wickets1 = await self.play_innings(channel, lobby, bat1_squad, bowl1_squad, name1, name2, "ONE", is_innings_two=False)

        target = score1 + 1
        await channel.send(f"🏁 **Innings 1 Over!**\n**{name1}** scored **{score1}/{wickets1}**.\nTarget for **{name2}**: **{target}** runs.")

        await asyncio.sleep(3)
        await channel.send(f"🚀 **Innings TWO Starting in 5 seconds!** Target: {target} runs.")
        await asyncio.sleep(5)

        # Innings 2 - Swap roles
        await channel.send(f"🏟️ **Innings TWO Started!**\nBatting: **{name2}** | Bowling: **{name1}**")
        score2, wickets2 = await self.play_innings(channel, lobby, bowl1_squad, bat1_squad, name2, name1, "TWO", is_innings_two=True, target_score=target)

        # Match Result
        if score2 >= target:
            winner = name2
            await channel.send(f"🎉 **{winner} won the game by chasing the target!** 🏆")
        elif score2 == score1:
            await channel.send(f"🤝 **The match is a tie!**")
        else:
            winner = name1
            margin = score1 - score2
            await channel.send(f"🏆 **{winner} won the game by {margin} runs!** 🥇")

        del self.lobbies[channel.id]


async def setup(bot: commands.Bot):
    await bot.add_cog(CricketCog(bot))
