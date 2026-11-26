"""Public help embed for conversational moderation commands."""

import re

import discord
from discord.ext import commands

HELP_PATTERN = re.compile(r"^\s*(?:liebe[\s,]+)?help\s*$", re.IGNORECASE)


class ConversationalModerationHelp(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not HELP_PATTERN.fullmatch(message.content):
            return
        embed = discord.Embed(
            title="Liebe · Conversational Moderation Help",
            description=(
                "Use these phrases in any server text chat; `Liebe,` before a command is optional. "
                "Only moderators can run moderation actions. Discord permissions and role hierarchy "
                "are checked. AI chat and memory remain separate."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Bans, kicks & mute", value=(
            "`ban @member [reason]` — permanently ban.\n"
            "`tempban @member 1d [reason]` — temporary ban; use `s`, `m`, `h`, or `d`.\n"
            "`softban @member [reason]` — remove the last 24h of messages, then unban/kick.\n"
            "`massban @member @member ... [reason]` — up to 10 mentioned members.\n"
            "`kick @member [reason]` — kick. `mute @member` / `unmute @member` — use mute role."
        ), inline=False)
        embed.add_field(name="Warnings", value=(
            "`warn @member [reason]` — log a warning and return case ID.\n"
            "`removewarn CASE_ID` — remove one case. `clearwarn @member` — clear their warnings."
        ), inline=False)
        embed.add_field(name="Cleanup (up to 100 messages; filtered commands default to 25)", value=(
            "`purge 25` — recent messages. `purge user @member 25` / `purge bot 25`.\n"
            '`purge contains "phrase" 25` — matching text.\n'
            "`purge links 25`, `purge images 25`, `purge files 25`, `purge embeds 25`, `purge emoji 25`.\n"
            "`purge reactions 25` — remove reactions without deleting messages.\n"
            "`cleanup 50` — Carl-bot messages and `!` command-trigger messages."
        ), inline=False)
        embed.add_field(name="Lockdown & setup", value=(
            "`lockdown` / `unlockdown` — current channel. Add `server` to apply across accessible text channels.\n"
            "`muterole @role` — select existing role; `muterole create` — create/configure; `muterole update` — refresh restrictions.\n"
            "`modrole @role` — designate moderators. `modonly` / `unmodonly` — restrict/restore bot commands here."
        ), inline=False)
        embed.set_footer(text="Example: Liebe, tempban @member 2d repeated spam | Use only with authorization.")
        try:
            await message.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            try:
                await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationHelp(bot))
