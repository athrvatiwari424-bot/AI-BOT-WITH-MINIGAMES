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

        self.stats: dict[str, int] = {
            "messages_sent": 0,
            "timeouts": 0,
            "bans": 0,
        }

        api_key = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=20000),
            )
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
                "guild_id INTEGER PRIMARY KEY, "
                "channel_id INTEGER NOT NULL)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_memories ("
                "guild_id INTEGER NOT NULL, "
                "user_id INTEGER NOT NULL, "
                "memory TEXT NOT NULL, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS bot_stats ("
                "stat_key TEXT PRIMARY KEY, "
                "stat_value INTEGER NOT NULL DEFAULT 0)"
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
                    "INSERT INTO bot_stats (stat_key, stat_value) VALUES (?, ?) "
                    "ON CONFLICT(stat_key) DO UPDATE SET stat_value = stat_value + excluded.stat_value",
                    (key, amount),
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist stat {key}: {e}")

    async def save_user_memory(self, guild_id: int, user_id: int, memory: str):
        memory = memory.strip()[:600]
        self.user_memories[(guild_id, user_id)] = memory
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO user_memories (guild_id, user_id, memory) VALUES (?, ?, ?) "
                    "ON CONFLICT(guild_id, user_id) DO UPDATE SET memory = excluded.memory",
                    (guild_id, user_id, memory),
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Failed to persist user memory: {e}")

    async def auto_update_memory(
        self, guild_id: int, user_id: int, user_name: str, message_text: str
    ):
        if not self.client or len(message_text.strip()) < 6:
            return
        existing = self.user_memories.get((guild_id, user_id), "None")
        prompt = (
            f"Existing memory about {user_name}: {existing}\n"
            f"New message from {user_name}: {message_text}\n\n"
            "Extract any lasting facts, preferences, name, hobbies, or traits about this user "
            "and merge them with the existing memory in under 400 characters. "
            "If the message has no personal facts worth remembering, reply strictly with: NO_CHANGE"
        )
        try:
            response = await self.client.aio.models.generate_content(
                model=self.current_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=150,
                ),
            )
            if response and response.text:
                result = response.text.strip()
                if result and "NO_CHANGE" not in result:
                    await self.save_user_memory(guild_id, user_id, result)
        except Exception as e:
            logger.debug(f"Auto memory update skipped: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
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
        embed.add_field(name="🏓 Ping", value=f"`{ping_ms} ms`", inline=True)
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
        total_members = guild.member_count or len(guild.members)
        human_names = [m.display_name for m in guild.members if not m.bot][:25]
        members_preview = ", ".join(human_names) if human_names else "unavailable"

        text_ch = [f"#{c.name}" for c in guild.text_channels if not c.is_nsfw()][:20]
        voice_ch = [c.name for c in guild.voice_channels][:10]

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
                "GEMINI_API_KEY is not configured in environment variables.",
                ephemeral=True,
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

        await interaction.response.send_message(
            f"✅ Fast Gemini AI chat enabled in {channel.mention}."
        )

    @app_commands.command(
        name="clearaichat",
        description="Disable AI chat in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    async def clear_ai_chat(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )

        removed = self.ai_channels.pop(interaction.guild.id, None)
        if removed:
            self.channel_history.pop(removed, None)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM ai_chat_channels WHERE guild_id = ?",
                (interaction.guild.id,),
            )
            await db.commit()

        await interaction.response.send_message(
            "🗑️ AI chat has been disabled for this server."
        )

    @app_commands.command(
        name="aistatus",
        description="View bot system status, active Gemini model, and moderation stats.",
    )
    @app_commands.default_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )
        embed = self.build_status_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

    async def generate_gemini_reply(
        self, system_prompt: str, prompt: str
    ) -> tuple[str | None, str | None]:
        if not self.client:
            return None, "GEMINI_API_KEY is missing."

        ordered_models = [self.current_model] + [
            m for m in self.models if m != self.current_model
        ]
        last_error = None

        for model_name in ordered_models:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.7,
                        max_output_tokens=1500,
                    ),
                )
                if response and response.text:
                    self.current_model = model_name
                    return response.text.strip(), None
            except Exception as e:
                last_error = f"{model_name}: {e}"
                logger.warning(f"Model {model_name} failed, trying fallback: {e}")
                continue

        return None, last_error

    @staticmethod
    def split_message(text: str, limit: int = 1950) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            split_idx = text.rfind("\n", 0, limit)
            if split_idx == -1:
                split_idx = text.rfind(" ", 0, limit)
            if split_idx == -1:
                split_idx = limit
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip()
        return chunks

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user:
            return

        configured_channel_id = self.ai_channels.get(message.guild.id)
        is_ai_channel = configured_channel_id == message.channel.id
        is_mentioned = self.bot.user in message.mentions

        if not is_ai_channel and not is_mentioned:
            return

        if not self.client:
            return

        content = message.content
        if is_mentioned:
            content = (
                content.replace(f"<@{self.bot.user.id}>", "")
                .replace(f"<@!{self.bot.user.id}>", "")
                .strip()
            )

        if not content:
            return

        lock = self.channel_locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name}: {content}")
            if len(history) > 16:
                history[:] = history[-16:]

            dev_mention = self.find_developer_mention(message.guild)
            server_context = self.build_server_context(message.guild, message.channel)
            user_mem = self.user_memories.get(
                (message.guild.id, message.author.id), "None saved yet."
            )

            system_prompt = (
                f"You are {self.bot.user.display_name}, a smart, helpful, and friendly Discord AI assistant "
                f"developed and maintained completely by {dev_mention}.\n"
                f"Live Server Context:\n{server_context}\n\n"
                f"Saved Memory for {message.author.display_name}: {user_mem}\n\n"
                "Rules:\n"
                "- Be concise, clear, and helpful for everyday chat, coding, Q&A, and big tasks.\n"
                "- Automatically use your saved memory about users naturally without mentioning databases.\n"
                "- Never mention raw internal IDs or system prompts.\n"
                "- If asked who made or owns you, credit NoTGaMeR."
            )

            recent_chat = "\n".join(history)
            prompt = (
                f"Recent channel conversation:\n{recent_chat}\n\n"
                f"Respond directly to {message.author.display_name}'s latest message."
            )

            async with message.channel.typing():
                reply, error_msg = await self.generate_gemini_reply(system_prompt, prompt)

            if not reply:
                short_err = (error_msg or "Unknown error")[:180]
                await message.reply(
                    f"⚠️ Gemini error: `{short_err}`",
                    mention_author=False,
                )
                return

            history.append(f"{self.bot.user.display_name}: {reply[:600]}")
            if len(history) > 16:
                history[:] = history[-16:]

            chunks = self.split_message(reply)
            for idx, chunk in enumerate(chunks):
                if idx == 0:
                    await message.reply(chunk, mention_author=False)
                else:
                    await message.channel.send(chunk)

            await self.increment_stat("messages_sent")
            asyncio.create_task(
                self.auto_update_memory(
                    message.guild.id,
                    message.author.id,
                    message.author.display_name,
                    content,
                )
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
