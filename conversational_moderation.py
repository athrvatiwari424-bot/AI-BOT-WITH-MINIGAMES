"""Route explicit conversational moderation requests outside the AI-chat channel.

The permission-checked action implementations remain on AIChatCog so existing
behavior, state (snipe caches, pending confirmations, statistics), and safety
checks are shared rather than duplicated. This cog only provides the global
message entry point.
"""

import re

import discord
from discord.ext import commands


class ConversationalModerationCog(commands.Cog):
    """Make the existing explicit moderation phrases available in any channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user:
            return

        ai_chat = self.bot.get_cog("AIChatCog")
        if ai_chat is None:
            return

        bot_mention = rf"<@!?{self.bot.user.id}>"
        mentioned = (
            any(user.id == self.bot.user.id for user in message.mentions)
            or bool(re.search(bot_mention, message.content))
        )
        # AIChatCog already dispatches moderation in its configured channel and
        # when Liebe is mentioned. Avoid handling those messages twice.
        if ai_chat.ai_channels.get(message.guild.id) == message.channel.id or mentioned:
            return

        content = re.sub(bot_mention, "", message.content).strip()
        if not content:
            return

        await ai_chat.try_ai_mod_command(message, content)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationCog(bot))
