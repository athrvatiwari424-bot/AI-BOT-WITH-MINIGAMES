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
        # Minimum allowed server deadline is 10s (10000ms)
        self.client = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=10000),
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
                for guild_id, channel_id in await cursor.fetchall():
                    self.ai_channels[guild_id] = channel_id

    @app_commands.command(
        name="setaichat",
        description="Set a specific channel for fun AI chat, quick Q&A, and simple math.",
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
            await interaction.response.send_message("AI chat has been disabled.")
        else:
            await interaction.response.send_message(
                "No AI chat channel was set for this server.", ephemeral=True
            )

    async def generate_reply(self, prompt: str) -> str:
        errors = []
        for model_name in self.models:
            try:
                config = types.GenerateContentConfig(
                    max_output_tokens=220,
                    temperature=0.8,
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
                errors.append(f"{model_name}: empty response")
            except Exception as e:
                detail = f"{model_name} -> {type(e).__name__}: {e}"
                logger.error(detail)
                errors.append(detail)
                continue

        raise RuntimeError(" | ".join(errors) if errors else "No Gemini response")

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
            history.append(f"{message.author.display_name}: {message.content.strip()}")
            history = history[-5:]
            self.channel_history[message.channel.id] = history

            prompt = (
                "You are liebe, a fun, chill Discord bot for casual chat, quick questions, "
                "and simple math. Keep replies short (1–3 sentences).\n\n"
                + "\n".join(history)
                + "\nliebe:"
            )

            async with message.channel.typing():
                try:
                    reply_text = await self.generate_reply(prompt)
                    history.append(f"liebe: {reply_text}")
                    self.channel_history[message.channel.id] = history[-5:]
                    await message.channel.send(reply_text[:1900])
                except asyncio.TimeoutError:
                    await message.channel.send("Quick brain freeze—try sending that again!")
                except Exception as e:
                    await message.channel.send(f"Couldn't reply: `{str(e)[:300]}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
