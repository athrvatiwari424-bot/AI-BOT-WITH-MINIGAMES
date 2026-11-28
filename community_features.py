"""Community utilities for Liebe: polls, reaction roles, invites, birthdays and help."""
import re
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB = "bot_data.db"
BOT_OWNER_ID = 1170682591414861896
STAFF_PERMS = ("administrator", "manage_guild", "manage_messages", "manage_roles", "manage_channels", "moderate_members", "kick_members", "ban_members")


def is_staff(member: discord.Member) -> bool:
    p = member.guild_permissions
    return member.id in (BOT_OWNER_ID, member.guild.owner_id) or any(getattr(p, x, False) for x in STAFF_PERMS)


def staff_only():
    async def predicate(interaction: discord.Interaction):
        return bool(interaction.guild and isinstance(interaction.user, discord.Member) and is_staff(interaction.user))
    return app_commands.check(predicate)


class CommunityFeatures(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}

    async def cog_load(self):
        async with aiosqlite.connect(DB) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS community_settings(guild_id INTEGER PRIMARY KEY, welcome_channel INTEGER, welcome_message TEXT, rules TEXT);
            CREATE TABLE IF NOT EXISTS reaction_roles(guild_id INTEGER, message_id INTEGER, emoji TEXT, role_id INTEGER, PRIMARY KEY(guild_id,message_id,emoji));
            CREATE TABLE IF NOT EXISTS invite_stats(guild_id INTEGER, user_id INTEGER, uses INTEGER DEFAULT 0, PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS birthdays(guild_id INTEGER, user_id INTEGER, month INTEGER, day INTEGER, PRIMARY KEY(guild_id,user_id));
            """)
            await db.commit()

    async def _setting(self, guild_id: int):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT welcome_channel,welcome_message,rules FROM community_settings WHERE guild_id=?", (guild_id,))
            return await cur.fetchone()

    async def _save_setting(self, guild_id: int, field: str, value):
        allowed = {"welcome_channel", "welcome_message", "rules"}
        if field not in allowed:
            raise ValueError("Invalid setting")
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT OR IGNORE INTO community_settings(guild_id) VALUES(?)", (guild_id,))
            await db.execute(f"UPDATE community_settings SET {field}=? WHERE guild_id=?", (value, guild_id))
            await db.commit()

    async def _cache_invites(self, guild: discord.Guild):
        try:
            self.invite_cache[guild.id] = {i.code: i.uses or 0 for i in await guild.invites()}
        except (discord.Forbidden, discord.HTTPException):
            self.invite_cache[guild.id] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        await self._cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        used_by = None
        try:
            current = {i.code: i.uses or 0 for i in await member.guild.invites()}
            previous = self.invite_cache.get(member.guild.id, {})
            for code, uses in current.items():
                if uses > previous.get(code, 0):
                    invite = next((x for x in await member.guild.invites() if x.code == code), None)
                    used_by = invite.inviter if invite else None
                    break
            self.invite_cache[member.guild.id] = current
        except (discord.Forbidden, discord.HTTPException):
            pass
        if used_by and not used_by.bot:
            async with aiosqlite.connect(DB) as db:
                await db.execute("INSERT INTO invite_stats(guild_id,user_id,uses) VALUES(?,?,1) ON CONFLICT(guild_id,user_id) DO UPDATE SET uses=uses+1", (member.guild.id, used_by.id))
                await db.commit()
        row = await self._setting(member.guild.id)
        if row and row[0]:
            channel = member.guild.get_channel(row[0])
            if isinstance(channel, discord.TextChannel):
                template = row[1] or "Welcome {member} to **{server}**! You are member #{count}."
                text = template.replace("{member}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count or 0))
                try:
                    await channel.send(embed=discord.Embed(description=text, color=discord.Color.green()), allowed_mentions=discord.AllowedMentions(users=[member]))
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or (self.bot.user and payload.user_id == self.bot.user.id):
            return
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?", (payload.guild_id, payload.message_id, str(payload.emoji)))
            row = await cur.fetchone()
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(row[0]) if guild and row else None
        if member and role and not member.bot and role < guild.me.top_role and not role.is_default() and not role.managed:
            try:
                await member.add_roles(role, reason="Reaction role self-service")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?", (payload.guild_id, payload.message_id, str(payload.emoji)))
            row = await cur.fetchone()
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(row[0]) if guild and row else None
        if member and role and not member.bot:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except discord.HTTPException:
                pass

    @app_commands.guild_only()
    @app_commands.command(name="help", description="Show member commands and server rules")
    async def help_command(self, interaction: discord.Interaction):
        row = await self._setting(interaction.guild_id) if interaction.guild_id else None
        rules = row[2] if row and row[2] else "Server rules have not been configured yet."
        embed = discord.Embed(title="Liebe | Member Help", description="**Member commands**\n`/poll` create a poll\n`/birthday` save your birthday\n`/birthdays` view this month's birthdays\n`/invites` view your invite count\n`/leaderboard` view invite rankings\n\n**Server rules**\n" + rules[:3000], color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    @app_commands.guild_only()
    @app_commands.command(name="staffhelp", description="Show staff-only commands")
    @staff_only()
    async def staffhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Liebe | Staff Help", description="**Moderation**\n`/punishment`, `/ban`, `/kick`, `/timeout`, `/purge`, `/bans`\n\n**Server setup**\n`/echo`, `/message-log`, `/mod-log`, `/bot-log`, `/bot-update-log`, `/ticket-setup`, `/ticket-edit`, `/template-copy`, `/reactionrole`, `/welcomesetup`, `/invitesetup`, `/setrules`, `/rolecolor`\n\nUse conversational commands such as `warn @member reason` where enabled. Every action still checks Discord permissions and hierarchy.", color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="setrules", description="Set the rules shown in member help")
    @app_commands.describe(text="Server rules text")
    @staff_only()
    async def setrules(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 3000]):
        await self._save_setting(interaction.guild_id, "rules", text)
        await interaction.response.send_message("✅ Member rules updated.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="echo", description="Send a normal message or embed as Liebe")
    @app_commands.choices(format=[app_commands.Choice(name="Normal message", value="message"), app_commands.Choice(name="Embed", value="embed")])
    @staff_only()
    async def echo(self, interaction: discord.Interaction, message: app_commands.Range[str, 1, 1800], format: str, channel: discord.TextChannel | None = None):
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel) or not target.permissions_for(interaction.guild.me).send_messages:
            return await interaction.response.send_message("I cannot send messages in that channel.", ephemeral=True)
        if format == "embed":
            await target.send(embed=discord.Embed(description=message, color=discord.Color.blurple()), allowed_mentions=discord.AllowedMentions.none())
        else:
            await target.send(message, allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(f"Announcement posted in {target.mention}.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="poll", description="Create a yes/no poll")
    async def poll(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 240]):
        embed = discord.Embed(title="📊 Community Poll", description=question, color=discord.Color.blurple())
        embed.set_footer(text=f"Poll by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for emoji in ("👍", "👎"):
            try: await msg.add_reaction(emoji)
            except discord.HTTPException: pass

    @app_commands.guild_only()
    @app_commands.command(name="reactionrole", description="Create a reaction-role panel")
    @staff_only()
    async def reactionrole(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role, emoji: str, label: app_commands.Range[str, 1, 80] = "Get this role"):
        dangerous = role.permissions.administrator or any((
            role.permissions.manage_guild, role.permissions.manage_roles,
            role.permissions.manage_channels, role.permissions.manage_webhooks,
            role.permissions.ban_members, role.permissions.kick_members,
            role.permissions.moderate_members, role.permissions.manage_messages,
            role.permissions.mention_everyone,
        ))
        if role.is_default() or role.managed or dangerous or role >= interaction.guild.me.top_role or (interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role):
            return await interaction.response.send_message("That role is privileged, managed, above your or the bot's role, or @everyone. Only safe self-assignable roles are allowed.", ephemeral=True)
        embed = discord.Embed(title="Self-assignable role", description=f"React with {emoji} to {label}: {role.mention}", color=discord.Color.blurple())
        msg = await channel.send(embed=embed)
        try: await msg.add_reaction(emoji)
        except discord.HTTPException:
            await msg.delete()
            return await interaction.response.send_message("That emoji could not be added. Check the emoji and bot permissions.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT OR REPLACE INTO reaction_roles VALUES(?,?,?,?)", (interaction.guild_id, msg.id, emoji, role.id))
            await db.commit()
        await interaction.response.send_message(f"Reaction role panel created in {channel.mention}.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="welcomesetup", description="Configure the welcome channel and message")
    @staff_only()
    async def welcomesetup(self, interaction: discord.Interaction, channel: discord.TextChannel, message: app_commands.Range[str, 1, 800] = "Welcome {member} to **{server}**! You are member #{count}."):
        await self._save_setting(interaction.guild_id, "welcome_channel", channel.id)
        await self._save_setting(interaction.guild_id, "welcome_message", message)
        await interaction.response.send_message(f"Welcome messages will be sent in {channel.mention}. Placeholders: `{{member}}`, `{{server}}`, `{{count}}`.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="invitesetup", description="Check invite tracking permissions and enable tracking")
    @staff_only()
    async def invitesetup(self, interaction: discord.Interaction):
        if not interaction.guild.me.guild_permissions.manage_guild:
            return await interaction.response.send_message("I need Manage Server permission to inspect invite usage.", ephemeral=True)
        await self._cache_invites(interaction.guild)
        await interaction.response.send_message("Invite tracking initialized. Discord may not reveal vanity or some unknown invite sources.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="invites", description="Show your tracked invite count")
    async def invites(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT uses FROM invite_stats WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
            row = await cur.fetchone()
        await interaction.response.send_message(embed=discord.Embed(title="Invite count", description=f"{target.mention} has **{row[0] if row else 0}** tracked invites.", color=discord.Color.blurple()))

    @app_commands.guild_only()
    @app_commands.command(name="leaderboard", description="Show the top inviters")
    async def leaderboard(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT user_id,uses FROM invite_stats WHERE guild_id=? ORDER BY uses DESC LIMIT 10", (interaction.guild_id,))
            rows = await cur.fetchall()
        desc = "\n".join(f"**{i}.** <@{uid}> · **{uses}** invites" for i,(uid,uses) in enumerate(rows,1)) or "No tracked invites yet."
        await interaction.response.send_message(embed=discord.Embed(title="🏆 Invite Leaderboard", description=desc, color=discord.Color.gold()))

    @app_commands.guild_only()
    @app_commands.command(name="birthday", description="Register or update your birthday (month and day only)")
    async def birthday(self, interaction: discord.Interaction, month: app_commands.Range[int, 1, 12], day: app_commands.Range[int, 1, 31]):
        import datetime
        try: datetime.date(2024, month, day)
        except ValueError: return await interaction.response.send_message("That date is not valid.", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            await db.execute("INSERT OR REPLACE INTO birthdays VALUES(?,?,?,?)", (interaction.guild_id, interaction.user.id, month, day))
            await db.commit()
        await interaction.response.send_message("🎂 Your birthday has been saved (year not stored).", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="birthdays", description="Show birthdays this month")
    async def birthdays(self, interaction: discord.Interaction):
        from datetime import datetime
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT user_id,day FROM birthdays WHERE guild_id=? AND month=? ORDER BY day", (interaction.guild_id, datetime.now().month))
            rows = await cur.fetchall()
        desc = "\n".join(f"**{day:02d}** · <@{uid}>" for uid,day in rows) or "No birthdays registered this month."
        await interaction.response.send_message(embed=discord.Embed(title="🎂 Birthday Chart", description=desc, color=discord.Color.magenta()))

    @app_commands.guild_only()
    @app_commands.command(name="rolecolor", description="Change a role colour")
    @staff_only()
    async def rolecolor(self, interaction: discord.Interaction, role: discord.Role, hex_color: str):
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", hex_color):
            return await interaction.response.send_message("Use a six-digit hex colour, e.g. `#5865F2`.", ephemeral=True)
        if role.is_default() or role.managed or role >= interaction.guild.me.top_role or (interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role):
            return await interaction.response.send_message("That role is not below your and the bot's top roles.", ephemeral=True)
        await role.edit(colour=discord.Color(int(hex_color.lstrip('#'),16)), reason=f"Role colour changed by {interaction.user.id}")
        await interaction.response.send_message(f"Updated {role.mention} colour to `#{hex_color.lstrip('#').upper()}`.")

    @app_commands.guild_only()
    @app_commands.command(name="bans", description="List recent server bans")
    @staff_only()
    async def bans(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entries = [entry async for entry in interaction.guild.bans(limit=50)]
        except discord.Forbidden:
            return await interaction.followup.send("I need Ban Members permission to view the ban list.", ephemeral=True)
        desc = "\n".join(f"• **{entry.user}** (`{entry.user.id}`) · {(entry.reason or 'No reason')[:100]}" for entry in entries) or "No bans found."
        embed = discord.Embed(title="🔨 Server Ban List (latest 50)", description=desc[:4000], color=discord.Color.red())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member): return
        raw = message.content.strip()
        if self.bot.user: raw = re.sub(rf"^<@!?{self.bot.user.id}>\s*[,]?\s*", "", raw).strip()
        raw = re.sub(r"^Liebe\s*[,：:]\s*", "", raw, flags=re.I).strip()
        # Natural-language aliases; slash commands remain available for structured options.
        if re.match(r"^help$", raw, re.I):
            row = await self._setting(message.guild.id)
            rules = row[2] if row and row[2] else "Server rules have not been configured yet."
            embed = discord.Embed(title="Liebe | Member Help", description="`poll <question>` · `/poll`\n`birthday <month> <day>` · `/birthday`\n`birthdays` · `/birthdays`\n`invites` · `/invites`\n`leaderboard` · `/leaderboard`\n\n**Server Rules**\n" + rules[:2500], color=discord.Color.blurple())
            await message.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none()); return
        if re.fullmatch(r"birthdays", raw, re.I):
            from datetime import datetime
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute("SELECT user_id,day FROM birthdays WHERE guild_id=? AND month=? ORDER BY day", (message.guild.id, datetime.now().month))
                rows = await cur.fetchall()
            desc = "\n".join(f"**{day:02d}** · <@{uid}>" for uid, day in rows) or "No birthdays registered this month."
            await message.reply(embed=discord.Embed(title="🎂 Birthday Chart", description=desc, color=discord.Color.magenta()), mention_author=False); return
        if re.fullmatch(r"invites", raw, re.I):
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute("SELECT uses FROM invite_stats WHERE guild_id=? AND user_id=?", (message.guild.id, message.author.id)); row = await cur.fetchone()
            await message.reply(f"{message.author.mention}, you have **{row[0] if row else 0}** tracked invites.", mention_author=False); return
        if re.fullmatch(r"leaderboard", raw, re.I):
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute("SELECT user_id,uses FROM invite_stats WHERE guild_id=? ORDER BY uses DESC LIMIT 10", (message.guild.id,)); rows = await cur.fetchall()
            desc = "\n".join(f"**{i}.** <@{uid}> · **{uses}** invites" for i,(uid,uses) in enumerate(rows,1)) or "No tracked invites yet."
            await message.reply(embed=discord.Embed(title="🏆 Invite Leaderboard", description=desc, color=discord.Color.gold()), mention_author=False); return
        if re.fullmatch(r"bans|banlist", raw, re.I):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            if not message.guild.me.guild_permissions.ban_members: return await message.reply("I need Ban Members permission.", mention_author=False)
            try:
                entries = [entry async for entry in message.guild.bans(limit=30)]
            except discord.Forbidden: return await message.reply("I cannot access the ban list.", mention_author=False)
            desc = "\n".join(f"• **{entry.user}** (`{entry.user.id}`) · {(entry.reason or 'No reason')[:80]}" for entry in entries) or "No bans found."
            await message.reply(embed=discord.Embed(title="🔨 Server Ban List", description=desc[:4000], color=discord.Color.red()), mention_author=False); return
        if re.fullmatch(r"invitesetup", raw, re.I):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            if not message.guild.me.guild_permissions.manage_guild: return await message.reply("I need Manage Server permission to inspect invites.", mention_author=False)
            await self._cache_invites(message.guild)
            await message.reply("Invite tracking initialized. Vanity and some unknown invite sources may not be attributable.", mention_author=False); return
        if raw.lower().startswith("rolecolor "):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            match = re.match(r"rolecolor\s+<@&?(\d+)>\s+(#?[0-9a-fA-F]{6})$", raw, re.I)
            if not match: return await message.reply("Usage: `rolecolor @role #5865F2`.", mention_author=False)
            role = message.guild.get_role(int(match.group(1)))
            if not role or role.is_default() or role.managed or role >= message.guild.me.top_role or (message.author.id != message.guild.owner_id and role >= message.author.top_role): return await message.reply("That role is not below your and the bot's top roles.", mention_author=False)
            await role.edit(colour=discord.Color(int(match.group(2).lstrip('#'),16)), reason=f"Role colour changed by {message.author.id}")
            await message.reply(f"Updated {role.mention} colour to `{match.group(2)}`.", mention_author=False); return
        if raw.lower().startswith("setrules "):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            await self._save_setting(message.guild.id, "rules", raw[9:][:3000])
            await message.reply("✅ Member rules updated.", mention_author=False); return
        if raw.lower().startswith("welcomesetup "):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            match = re.match(r"welcomesetup\s+<#(\d+)>\s*(.*)$", raw, re.I)
            if not match: return await message.reply("Usage: `welcomesetup #channel [Welcome {member} to {server}]`.", mention_author=False)
            channel = message.guild.get_channel(int(match.group(1)))
            if not isinstance(channel, discord.TextChannel): return await message.reply("Choose a valid text channel.", mention_author=False)
            await self._save_setting(message.guild.id, "welcome_channel", channel.id)
            await self._save_setting(message.guild.id, "welcome_message", match.group(2) or "Welcome {member} to **{server}**!")
            await message.reply(f"Welcome messages configured for {channel.mention}.", mention_author=False); return
        if raw.lower().startswith("reactionrole "):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            match = re.match(r"reactionrole\s+<#(\d+)>\s+<@&?(\d+)>\s+(\S+)(?:\s+(.*))?$", raw, re.I)
            if not match: return await message.reply("Usage: `reactionrole #channel @role 😀 [label]`.", mention_author=False)
            channel = message.guild.get_channel(int(match.group(1))); role = message.guild.get_role(int(match.group(2)))
            if not isinstance(channel, discord.TextChannel) or not role or role.is_default() or role.managed or role >= message.guild.me.top_role or (message.author.id != message.guild.owner_id and role >= message.author.top_role): return await message.reply("Invalid channel or role hierarchy.", mention_author=False)
            emoji, label = match.group(3), match.group(4) or "Get this role"
            panel = await channel.send(embed=discord.Embed(title="Self-assignable role", description=f"React with {emoji} to {label}: {role.mention}", color=discord.Color.blurple()))
            try: await panel.add_reaction(emoji)
            except discord.HTTPException: await panel.delete(); return await message.reply("Could not add that emoji.", mention_author=False)
            async with aiosqlite.connect(DB) as db:
                await db.execute("INSERT OR REPLACE INTO reaction_roles VALUES(?,?,?,?)", (message.guild.id,panel.id,emoji,role.id)); await db.commit()
            await message.reply(f"Reaction-role panel created in {channel.mention}.", mention_author=False); return
        if raw.lower().startswith("poll "):
            question = raw[5:].strip()
            if question:
                embed = discord.Embed(title="📊 Community Poll", description=question[:240], color=discord.Color.blurple())
                embed.set_footer(text=f"Poll by {message.author.display_name}")
                poll = await message.reply(embed=embed, mention_author=False)
                for e in ("👍", "👎"):
                    try: await poll.add_reaction(e)
                    except discord.HTTPException: pass
            return
        if raw.lower().startswith("echo "):
            if not is_staff(message.author): return await message.reply("Staff only.", mention_author=False)
            text = raw[5:].strip()
            if text: await message.channel.send(text[:1800], allowed_mentions=discord.AllowedMentions.none())
            return
        if raw.lower().startswith("birthday "):
            m = re.fullmatch(r"birthday\s+(\d{1,2})\s+(\d{1,2})", raw, re.I)
            if m:
                from datetime import date
                month,day = map(int,m.groups())
                try: date(2024,month,day)
                except ValueError: return await message.reply("Invalid date. Use `birthday MM DD`.", mention_author=False)
                async with aiosqlite.connect(DB) as db:
                    await db.execute("INSERT OR REPLACE INTO birthdays VALUES(?,?,?,?)", (message.guild.id,message.author.id,month,day)); await db.commit()
                await message.reply("🎂 Birthday saved (year not stored).", mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(CommunityFeatures(bot))
