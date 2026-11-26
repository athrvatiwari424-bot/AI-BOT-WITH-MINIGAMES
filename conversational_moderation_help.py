"""Help embed for conversational moderation commands."""

import re

import discord
from discord.ext import commands


HELP_PATTERN = re.compile(r"^\s*(?:liebe[\s,]+)?staffhelp\s*$", re.IGNORECASE)


class ConversationalModerationHelp(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not HELP_PATTERN.fullmatch(message.content):
            return

        member = message.author
        if not isinstance(member, discord.Member):
            return
        perms = member.guild_permissions
        allowed = member.id == message.guild.owner_id or any(getattr(perms, name, False) for name in ("administrator", "manage_guild", "moderate_members", "kick_members", "ban_members", "manage_messages", "manage_roles", "manage_channels"))
        if not allowed:
            return

        embed = discord.Embed(
            title="Liebe · Staff Help",
            description=(
                "Moderation commands work in any server text channel. Start with the command, "
                "or say `Liebe, <command>`. Use a member or role mention where shown. "
                "Commands require moderator status and the matching Discord permissions; "
                "role hierarchy is enforced."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Member punishments",
            value=(
                "`ban @user [reason]` — permanently ban.\n"
                "`tempban @user 7d [reason]` — temporary ban; units: `s`, `m`, `h`, `d`.\n"
                "`unban USER_ID [reason]` — unban by ID.\n"
                "`softban @user [reason]` — remove recent messages and kick.\n"
                "`massban @user @user [reason]` — ban up to 10 mentioned users.\n"
                "`kick @user [reason]` — kick. `mute @user 10m [reason]` — timeout.\n"
                "`unmute @user [reason]` — remove timeout and configured mute role."
            ),
            inline=False,
        )
        embed.add_field(
            name="Warnings and cases",
            value=(
                "`warn @user [reason]` — record a warning.\n"
                "`warnings @user` / `infractions @user` — list warning cases.\n"
                "`removewarn CASE_ID` — remove a warning.\n"
                "`clearwarn @user` — clear warnings.\n"
                "`reason CASE_ID new reason` — update a case reason."
            ),
            inline=False,
        )
        embed.add_field(
            name="Roles",
            value=(
                "`createrole VIP #ff0000 hoist:true` — create a colored role.\n"
                "`delrole @role` — delete a role.\n"
                "`role @user @role` — toggle a role.\n"
                "`addrole @user @role` / `removerole @user @role`.\n"
                "`role all @role` / `role humans @role` / `role bots @role` — bulk add (up to 100).\n"
                "`rolecolor @role #ff0000` — change role color."
            ),
            inline=False,
        )
        embed.add_field(
            name="Message cleanup (pinned messages are kept)",
            value=(
                "`purge 25` — purge recent messages (maximum 100).\n"
                "`purge user @user 25` / `purge bot 25`.\n"
                '`purge contains "text" 25` — matching text.\n'
                "`purge links 25` / `purge images 25` / `purge files 25`.\n"
                "`purge embeds 25` / `purge emoji 25` / `purge reactions 25`.\n"
                "`cleanup 50` — Carl-bot messages and `!` command-trigger messages."
            ),
            inline=False,
        )
        embed.add_field(
            name="Channels and setup",
            value=(
                "`lockdown [#channel] [duration]` / `unlockdown [#channel]`.\n"
                "`lockdown server [duration]` / `unlockdown server`.\n"
                "`slowmode 30s [#channel]` — set 0s–6h.\n"
                "`muterole @role` / `muterole create [name]` — configure mute role.\n"
                "`modlog #channel` — set moderation log. `modrole @role` — moderator role.\n"
                "`modonly` / `unmodonly` — restrict or restore bot commands here."
            ),
            inline=False,
        )
        embed.add_field(
            name="Information",
            value=(
                "`whois @user` / `userinfo @user` — member details and warning count.\n"
                "`serverinfo` — server details."
            ),
            inline=False,
        )
        embed.set_footer(text="Punishment actions are logged when a mod-log channel is configured.")

        try:
            await message.reply(
                embed=embed,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            try:
                await message.channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversationalModerationHelp(bot))
