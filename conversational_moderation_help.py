"""Help embed for conversational moderation commands."""

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
            title="Liebe · Moderation Help",
            description=(
                "Moderation commands work in any server text channel. "
                "Start directly with the command or say `Liebe, <command>`. "
                "Moderator permissions and role hierarchy are required."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Member punishments",
            value=(
                "`ban @user [reason]` — permanently ban\n"
                "`tempban @user 7d [reason]` — temporarily ban\n"
                "`unban USER_ID [reason]` — unban by Discord ID\n"
                "`softban @user [reason]` — ban and immediately unban\n"
                "`massban @user @user [reason]` — ban up to 10 users\n"
                "`kick @user [reason]` — kick\n"
                "`mute @user 10m [reason]` — timeout\n"
                "`unmute @user [reason]` — remove timeout"
            ),
            inline=False,
        )

        embed.add_field(
            name="Warnings",
            value=(
                "`warn @user [reason]` — add warning\n"
                "`warnings @user` / `infractions @user` — list warnings\n"
                "`removewarn CASE_ID` — remove a warning\n"
                "`clearwarn @user` — remove all warnings\n"
                "`reason CASE_ID new reason` — update case reason"
            ),
            inline=False,
        )

        embed.add_field(
            name="Roles",
            value=(
                "`createrole VIP #ff0000 hoist:true` — create role\n"
                "`delrole @role` — delete role\n"
                "`role @user @role` — toggle role\n"
                "`addrole @user @role` — add role\n"
                "`removerole @user @role` — remove role\n"
                "`role all @role` / `role humans @role` / `role bots @role`\n"
                "`rolecolor @role #ff0000` — change role color"
            ),
            inline=False,
        )

        embed.add_field(
            name="Cleanup",
            value=(
                "`purge 25` — bulk purge\n"
                "`purge user @user 25`\n"
                "`purge bot 25`\n"
                "`purge contains \"text\" 25`\n"
                "`purge links 25` / `purge images 25` / `purge files 25`\n"
                "`purge embeds 25` / `purge emoji 25`\n"
                "`purge reactions 25`\n"
                "`cleanup 50` — remove Carl-bot and `!` command messages"
            ),
            inline=False,
        )

        embed.add_field(
            name="Channels & setup",
            value=(
                "`lockdown [#channel] [duration]` / `unlockdown [#channel]`\n"
                "`lockdown server [duration]` / `unlockdown server`\n"
                "`slowmode 30s [#channel]`\n"
                "`muterole @role` / `muterole create [name]`\n"
                "`modlog #channel` / `modrole @role`\n"
                "`modonly` / `unmodonly`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Information",
            value=(
                "`whois @user` / `userinfo @user` — member

