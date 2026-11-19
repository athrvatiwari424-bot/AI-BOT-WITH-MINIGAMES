import os
import discord
from discord import app_commands
from discord.ext import commands
from google import genai


class AIChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Maps guild_id -> designated channel_id
        self.ai_channels: dict[int, int] = {}
        # Per-channel recent chat history for context
        self.channel_history: dict[int, list[str]] = {}

        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.model_name = "gemini-3.8-flash"

    @app_commands.command(
        name="setaichat",
        description="Set a specific channel where the bot will chat using Gemini AI.",
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
                "GEMINI_API_KEY is not configured in the environment variables.",
                ephemeral=True,
            )

        self.ai_channels[interaction.guild.id] = channel.id
        self.channel_history[channel.id] = []
        await interaction.response.send_message(
            f"AI chat is now enabled in {channel.mention} using `{self.model_name}`."
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
            await interaction.response.send_message("AI chat has been disabled.")
        else:
            await interaction.response.send_message(
                "No AI chat channel was set for this server.", ephemeral=True
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, and commands
        if message.author.bot or not message.guild:
            return
        if message.content.startswith("!") or not message.content.strip():
            return

        designated_channel_id = self.ai_channels.get(message.guild.id)
        if designated_channel_id != message.channel.id:
            return

        if not self.client:
            return

        history = self.channel_history.setdefault(message.channel.id, [])
        history.append(f"{message.author.display_name}: {message.content}")
        history = history[-10:]  # Keep last 10 messages to stay light on tokens
        self.channel_history[message.channel.id] = history

        prompt = (
            "You are a helpful, friendly Discord bot chatting in a server channel. "
            "Keep responses concise and suitable for Discord (under 1800 characters).\n\n"
            "Recent conversation:\n"
            + "\n".join(history)
            + "\nAssistant:"
        )

        async with message.channel.typing():
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                reply_text = (response.text or "").strip()
                if not reply_text:
                    return

                history.append(f"Assistant: {reply_text}")
                self.channel_history[message.channel.id] = history[-10:]

                # Split if over Discord's 2000-character message limit
                for i in range(0, len(reply_text), 1900):
                    await message.channel.send(reply_text[i : i + 1900])

            except Exception as e:
                await message.channel.send(
                    f"Couldn't generate an AI reply right now (`{type(e).__name__}`)."
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
