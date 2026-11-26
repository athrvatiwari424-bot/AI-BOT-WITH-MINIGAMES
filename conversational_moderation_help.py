"""Public help embed for conversational moderation commands."""

import re

import discord
from discord.ext import commands


HELP_PREFIX = re.compile(r"^\s*(?:liebe[\s,]+)?help\s*$", re.IGNORECASE)


class ConversationalModerationHelp(commands.Cog):
    """Explain the moderation phrases and required usage in a Discord embed."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not HELP_PREFIX.fullmatch(message.content):
            return

        embed = discord.Embed(
            title="Liebe · Conversational Moderation Help",
            description=(
                "Commands work in any server text chat. Start with the command, or say "
                "`Liebe, <command>`. Use the examples as written. Moderation commands "
                "require moderator status and the matching Discord permissions; the bot "
                "also checks role hierarchy. AI chat and its memory are separate."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Bans, kicks, and mute",
            value=(
                "`ban @member [reason]` — permanently ban.\n"
                "`tempban @member 1d [reason]` — temporary ban; durations use `s`, `m`, `h`, or `d`.\n"
                "`softban @member [reason]` — remove up to 24 hours of recent messages, then unban (kicks).\n"
                "`massban @member @member ... [reason]` — ban up to 10 mentioned members.\n"
                "`kick @member [reason]` — remove a member.\n"
                "`mute @member` / `unmute @member` — add/remove the configured mute role."
            ),
            inline=False,
        )
        embed.add_field(
            name="Warnings",
            value=(
                "`warn @member [reason]` — record a warning and show its case ID.\n"
                "`removewarn CASE_ID` — remove one warning.\n"
                "`clearwarn @member` — remove that member's warnings."
            ),
            inline=False,
        )
        embed.add_field(
            name="Message cleanup (up to 100 messages; default 25 for filters)",
            value=(
                "`purge 25` — delete recent messages.\n"
                "`purge user @member 25` / `purge bot 25` — filter by author.\n"
                "`purge contains ""spoiler text"" 25` — match a phrase.\n"
                "`purge links 25`, `purge images 25`, `purge files 25`, `purge embeds 25`, `purge emoji 25`\n"
                "`purge reactions 25` — clear reactions without deleting messages.\n"
                "`cleanup 50` — remove Carl-bot messages and this bot's `!` command triggers."
            ),
            inline=False,
        )
        embed.add_field(
            name="Lockdown and moderation setup",
            value=(
                "`lockdown` / `unlockdown` — lock/restore the current text channel.\n"
                "`lockdown server` / `unlockdown server` — lock/restore accessible server text channels.\n"
                "`muterole @role` — set an existing mute role; `muterole create` creates/configures one.\n"
                "`muterole update` — apply mute restrictions to current channels; future channels are handled automatically.\n"
                "`modrole @role` — designate the moderator role.\n"
                "`modonly` / `unmodonly` — restrict/restore `!` bot commands in this channel."
            ),
            inline=False,
        )
        embed.set_footer(text="For durations, use compact units (e.g. 30m, 2h, 7d). Never use a command unless authorized.")
        try:
            await message.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:
                await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationHelp(bot))
