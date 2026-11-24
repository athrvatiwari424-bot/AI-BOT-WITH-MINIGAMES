import asyncio
import os
import logging
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types

logger = logging.getLogger("ai_chat")
DB_PATH = "bot_data.db"


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ai_channels: dict[int, int] = {}
        self.channel_history: dict[int, list[str]] = {}
        self.channel_locks: dict[int, asyncio.Lock] = {}
        self.user_memories: dict[tuple[int, int], str] = {}

        # Live & persistent bot stats
        self.stats: dict[str, int] = {
            "messages_sent": 0,
            "timeouts": 0,
            "bans": 0,
        }

        api_key = os.getenv("GEMINI_API_KEY")
        # 20s deadline so big tasks and detailed answers don't time out
        self.client = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=20000),
            )
            if api_key
            else None
        )

        # Fast free-tier models ordered for low latency
        self.models = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.6-flash",
        ]
        self.current_model: str = self.models[0]

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_chat_channels (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_memories (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    memory TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_stats (
                    stat_key TEXT PRIMARY KEY,
                    stat_value INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            for key in self.stats:
                await db.execute(
                    "INSERT OR IGNORE INTO bot_stats (stat_key, stat_value) VALUES (?, 0)",
                    (key,),
                )
            await db.commit()

            async with db.execute(
                "SELECT guild_id, channel_id FROM ai_chat_channels"
            ) as cursor:
                for guild_id, channel_id in await cursor.fetchall():
                    self.ai_channels[guild_id] = channel_id

            async with db.execute(
                "SELECT guild_id, user_id, memory FROM user_memories"
            ) as cursor:
                for guild_id, user_id, memory in await cursor.fetchall():
                    self.user_memories[(guild_id, user_id)] = memory

            async with db.execute(
                "SELECT stat_key, stat_value FROM bot_stats"
            ) as cursor:
                for stat_key, stat_value in await cursor.fetchall():
                    if stat_key in self.stats:
                        self.stats[stat_key] = stat_value

    async def increment_stat(self, key: str, amount: int = 1):
        self.stats[key] = self.stats.get(key, 0) + amount
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    INSERT INTO bot_stats (stat_key, stat_value)
                    VALUES (?, ?)
                    ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + excluded.stat_value
                    """,
                    (key, amount),
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist stat {key}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Automatically counts timeouts issued by this bot from any cog."""
        if before.timed_out_until == after.timed_out_until or after.timed_out_until is None:
            return
        if not self.bot.user or not after.guild.me.guild_permissions.view_audit_log:
            return

        try:
            await asyncio.sleep(0.8)
            async for entry in after.guild.audit_logs(
                limit=3, action=discord.AuditLogAction.member_update
            ):
                if entry.target and entry.target.id == after.id:
                    if entry.user and entry.user.id == self.bot.user.id:
                        await self.increment_stat("timeouts")
                    break
        except Exception as e:
            logger.debug(f"Audit log timeout check skipped: {e}")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Automatically counts bans issued by this bot from any cog."""
        if not self.bot.user or not guild.me.guild_permissions.view_audit_log:
            return

        try:
            await asyncio.sleep(0.8)
            async for entry in guild.audit_logs(
                limit=3, action=discord.AuditLogAction.ban
            ):
                if entry.target and entry.target.id == user.id:
                    if entry.user and entry.user.id == self.bot.user.id:
                        await self.increment_stat("bans")
                    break
        except Exception as e:
            logger.debug(f"Audit log ban check skipped: {e}")

    def find_developer_mention(self, guild: discord.Guild) -> str:
        """Finds NoTGaMeR in the server to mention him, or falls back to his name."""
        for member in guild.members:
            if (
                "notgamer" in member.name.lower()
                or "notgamer" in member.display_name.lower()
            ):
                return f"{member.mention} (**NoTGaMeR**)"
        return "**NoTGaMeR**"

    def build_status_embed(self, guild: discord.Guild) -> discord.Embed:
        ping_ms = round(self.bot.latency * 1000)
        dev_display = self.find_developer_mention(guild)

        embed = discord.Embed(
            title="🤖 Bot System Status",
            description=f"Developed & maintained completely by {dev_display}.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="📡 Ping", value=f"`{ping_ms} ms`", inline=True)
        embed.add_field(
            name="🧠 Active Gemini Model",
            value=f"`{self.current_model}`",
            inline=True,
        )
        embed.add_field(
            name="💬 Messages Sent",
            value=f"`{self.stats.get('messages_sent', 0):,}`",
            inline=True,
        )
        embed.add_field(
            name="⏳ Timeouts Done",
            value=f"`{self.stats.get('timeouts', 0):,}`",
            inline=True,
        )
        embed.add_field(
            name="🔨 Bans Done",
            value=f"`{self.stats.get('bans', 0):,}`",
            inline=True,
        )
        embed.set_footer(text="Requested by Administrator")
        return embed

    def build_server_context(
        self, guild: discord.Guild, current_channel: discord.abc.GuildChannel
    ) -> str:
        # 1. Member info
        total_members = guild.member_count or len(guild.members)
        human_names = [
            m.display_name for m in guild.members if not m.bot
        ][:25]
        members_preview = ", ".join(human_names) if human_names else "unavailable"

        # 2. Channels info (cap to keep prompt short and fast)
        text_ch = [f"#{c.name}" for c in guild.text_channels if not c.is_nsfw()][:20]
        voice_ch = [c.name for c in guild.voice_channels][:10]

        # 3. Bot commands info
        slash_cmds = [
            f"/{cmd.name}: {cmd.description}"
            for cmd in self.bot.tree.get_commands()
        ]
        prefix_cmds = [
            f"!{cmd.name}" + (f" - {cmd.help}" if cmd.help else "")
            for cmd in self.bot.commands
            if not cmd.hidden
        ]
        all_cmds = slash_cmds + prefix_cmds
        cmds_summary = " | ".join(all_cmds[:30]) if all_cmds else "standard bot commands"

        return (
            f"Server Name: {guild.name} | Current Channel: #{getattr(current_channel, 'name', 'unknown')}\n"
            f"Total Members: {total_members} | Sample Members: {members_preview}\n"
            f"Text Channels: {', '.join(text_ch) if text_ch else 'none'} | Voice Channels: {', '.join(voice_ch) if voice_ch else 'none'}\n"
            f"My Commands: {cmds_summary}"
        )

    @app_commands.command(
        name="setaichat",
        description="Set a specific channel for AI chat, big tasks, Q&A, and personalized memory.",
    )
    @app_commands.describe(channel="The text channel for AI chat")
    @app_commands.default_permissions(administrator=True)
    async def set_ai_chat(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )

        if not self.client:
            return await interaction.response.send_message(
                "GEMINI_API_KEY is not configured in Render environment variables.",
                ephemeral=True,
            )

        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO ai_chat_channels (guild_id, channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
