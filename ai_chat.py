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

        api_key = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=8000),  # 8s hard HTTP cap
            )
            if api_key
            else None
        )

        # Fastest low-latency Gemini models first
        self.models = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
        ]

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
            await db.commit()
            async with db.execute(
                "SELECT guild_id, channel_id FROM ai_chat_channels"
            ) as cursor:
                rows = await cursor.fetchall()
                for guild_id, channel_id in rows:
                    self.ai_channels[guild_id] = channel_id

    @app_commands.command(
        name="setaichat",
        description="Set a specific channel where Gemini will chat.",
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
                """,
                (interaction.guild.id, channel.id),
            )
            await db.commit()

        await interaction.response.send_message(
            f"Fast Gemini AI chat enabled in {channel.mention}."
        )

    @app_commands.command(
        name="clearaichat",
        description="Disable Gemini AI chat in this server.",
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
            await interaction.response.send_message("Gemini AI chat disabled.")
        else:
            await interaction.response.send_message(
                "No AI chat channel was set for this server.", ephemeral=True
            )

    async def generate_reply(self, prompt: str) -> str:
        last_error = None
        for model_name in self.models:
            try:
                # Disable internal thinking delay on Flash models for instant chat replies
                config = types.GenerateContentConfig(
                    max_output_tokens=250,
                    temperature=0.8,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=8.0,
                )
                text = (response.text or "").strip()
                if text:
                    return text
            except Exception as e:
                last_error = e
                logger.warning(f"Model {model_name} failed/slow: {type(e).__name__}")
                continue

        raise last_error or RuntimeError("All Gemini models timed out.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith("!") or not message.content.strip():
            return

        if self.ai_channels.get(message.guild.id) != message.channel.id or not self.client:
            return

        lock = self.channel_locks.setdefault(message.channel.id, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            history = self.channel_history.setdefault(message.channel.id, [])
            history.append(f"{message.author.display_name}: {message.content}")
            history = history[-6:]  # Keep last 6 messages for fast token processing
            self.channel_history[message.channel.id] = history

            prompt = (
                "You are liebe, a witty, fast-talking Discord bot. "
                "Reply in 1–3 short, punchy sentences.\n\n"
                + "\n".join(history)
                + "\nliebe:"
            )

            async with message.channel.typing():
                try:
                    reply_text = await self.generate_reply(prompt)
                    history.append(f"liebe: {reply_text}")
                    self.channel_history[message.channel.id] = history[-6:]

                    await message.channel.send(reply_text[:1900])
                except asyncio.TimeoutError:
                    await message.channel.send("Brain lag—send that again!")
                except Exception as e:
                    await message.channel.send(
                        f"Couldn't reply right now (`{type(e).__name__}`)."
                    )


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
