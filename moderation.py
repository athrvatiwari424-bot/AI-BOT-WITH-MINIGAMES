import asyncio
import os
import re
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
        self.stats: dict[str, int] = {"messages_sent": 0, "timeouts": 0, "bans": 0}

        api_key = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20000))
            if api_key
            else None
        )
        self.models = [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
        ]
        self.current_model: str = "gemini-3.5-flash-lite"

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS ai_chat_channels ("
                "guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_memories ("
                "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, memory TEXT NOT NULL, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS bot_stats ("
                "stat_key TEXT PRIMARY KEY, stat_value INTEGER NOT NULL DEFAULT 0)"
            )
            for k in self.stats:
                await db.execute(
                    "INSERT OR IGNORE INTO bot_stats (stat_key, stat_value) VALUES (?, 0)",
                    (k,),
                )
            await db.commit()

            async with db.execute("SELECT guild_id, channel_id FROM ai_chat_channels") as c:
                for g, ch in await c.fetchall():
                    self.ai_channels[g] = ch

            async with db.execute("SELECT guild_id, user_id, memory FROM user_memories") as c:
                for g, u, m in await c.fetchall():
                    self.user_memories[(g, u)] = m

            async with db.execute("SELECT stat_key, stat_value FROM bot_stats") as c:
                for k, v in await c.fetchall():
                    if k in self.stats:
                        self.stats[k] = v

    async def increment_stat(self, key: str, amount: int = 1):
        self.stats[key] = self.stats.get(key, 0) + amount
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO bot_stats (stat_key, stat_value) VALUES (?, ?) "
                    "ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + excluded.stat_value",
                    (key, amount),
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Stat save failed: {e}")

    async def auto_update_memory(self, guild_id: int, user_id: int, user_name: str, msg: str):
        if not self.client or len(msg.strip()) < 6:
            return
        existing = self.user_memories.get((guild_id, user_id), "None")
        prompt = (
            f"Existing memory for {user_name}: {existing}\n"
            f"New message from {user_name}: {msg}\n\n"
            "Merge any lasting personal facts, preferences, name, or hobbies in under 400 characters. "
            "If there are no new personal facts worth remembering, reply strictly with: NO_CHANGE"
        )
        try:
            res = await self.client.aio.models.generate_content(
                model=self.current_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=150),
            )
            if res and res.text and "NO_CHANGE" not in res.text:
                mem = res.text.strip()[:600]
                self.user_memories[(guild_id, user_id)] = mem
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) "
                        "ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory",
                        (guild_id, user_id, mem),
                    )
                    await db.commit()
        except Exception as e:
            logger.debug(f"Memory update skipped: {e}")

    @staticmethod
    def is_restricted_request(text: str) -> bool:
        low = text.lower()
        patterns = [
            r"@everyone",
            r"@here",
            r"\b(ping|mention|tag)\s+(everyone|here|all|everybody|members|roles)\b",
            r"\bmass\s*ping\b",
            r"\bspam\s*ping\b",
            r"\b(delete|remove|nuke|destroy)\s+(this\s+|the\s+|all\s+)?channels?\b",
        ]
        return any(re.search(p, low) for p in patterns) or len(re.findall(r"<@[!&]?\d+>", text)) >= 3

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if (
            before.timed_out_until == after.timed_out_until
            or after.timed_out_until is None
            or not self.bot.user
            or not after.guild.me.guild_permissions.view_audit_log
        ):
            return
        try:
            await asyncio.sleep(0.8)
            async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                if entry.target and entry.target.id == after.id:
                    if entry.user and entry.user.id == self.bot.user.id:
                        await self.increment_stat("timeouts")
                    break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not self.bot.user or not guild.me.guild_permissions.view_audit_log:
            return
        try:
            await asyncio.sleep(0.8)
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == user.id:
                    if entry.user and entry.user.id == self.bot.user.id:
                        await self.increment_stat("bans")
                    break
        except Exception:
            pass

    def find_developer_mention(self, guild: discord.Guild) -> str:
        for m in guild.members:
            if "notgamer" in m.name.lower() or "notgamer" in m.display_name.lower():
                return f"{m.mention} (**NoTGaMeR**)"
        return "**NoTGaMeR**"

    def build_server_context(self, guild: discord.Guild, ch: discord.abc.GuildChannel) -> str:
        names = ", ".join([m.display_name for m in guild.members if not m.bot][:25]) or "unavailable"
        tch = ", ".join([f"#{c.name}" for c in guild.text_channels if not c.is_nsfw()][:20]) or "none"
        vch = ", ".join([c.name for c in guild.voice_channels][:10]) or "none"
        cmds = " | ".join([f"/{c.name}: {c.description}" for c in self.bot.tree.get_commands()][:30]) or "standard"
        return (
            f"Server: {guild.name} | Channel: #{getattr(ch, 'name', 'unknown')} | "
            f"Members: {guild.member_count or len(guild.members)} ({names})\n"
            f"Text: {tch} | Voice: {vch}\nCommands: {cmds}"
        )

    @app_commands.command(name="setaichat", description="Set a specific channel for AI chat, Q&A, and auto memory.")
    @app_commands.describe(channel="The text channel for AI chat")
    @app_commands.default_permissions(administrator=True)
    async def set_ai_chat(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not self.client:
            return await interaction.response.send_message(
                "Run this inside a server with GEMINI_API_KEY configured.", ephemeral=True
            )
        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO ai_chat_channels (guild_id, channel_id) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
                (interaction.guild.id, channel.id),
            )
            await db.commit()
        await interaction.response.send_message(f"✅ Fast Gemini AI chat enabled in {channel.mention}.")

    @app_commands.command(name="clearaichat", description="Disable AI chat in this server.")
    @app_commands.default_permissions(administrator=True)
    async def clear_ai_chat(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        removed = self.ai_channels.pop(interaction.guild.id, None)
        if removed:
            self.channel_history.pop(removed, None)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM ai_chat_channels WHERE guild_id = ?", (interaction.guild.id,))
            await db.commit()
        await interaction.response.send_message("🗑️ AI chat disabled for this server.")

    @app_commands.command(name="aistatus", description="View bot system status, active Gemini model, and stats.")
    @app_commands.default_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        embed = discord.Embed(
            title="🤖 Bot System Status",
