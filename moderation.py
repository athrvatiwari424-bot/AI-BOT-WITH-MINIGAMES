import asyncio
import discord
from discord import app_commands
from discord.ext import commands


class Moderation(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @commands.hybrid_command(
      name="kick", description="Kick a member from the server."
  )
  @app_commands.describe(
      member="The member to kick", reason="Reason for kicking"
  )
  @commands.has_permissions(kick_members=True)
  async def kick(
      self,
      ctx: commands.Context,
      member: discord.Member,
      *,
      reason: str = "No reason provided",
  ):
    await member.kick(reason=reason)
    await ctx.send(f"👢 Kicked **{member.display_name}**. Reason: {reason}")

  @commands.hybrid_command(
      name="ban", description="Ban a member from the server."
  )
  @app_commands.describe(
      member="The member to ban", reason="Reason for banning"
  )
  @commands.has_permissions(ban_members=True)
  async def ban(
      self,
      ctx: commands.Context,
      member: discord.Member,
      *,
      reason: str = "No reason provided",
  ):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Banned **{member.display_name}**. Reason: {reason}")

  @commands.hybrid_command(
      name="unban", description="Unban a user by their user ID."
  )
  @app_commands.describe(
      user_id="The Discord ID of the user", reason="Reason for unbanning"
  )
  @commands.has_permissions(ban_members=True)
  async def unban(
      self,
      ctx: commands.Context,
      user_id: str,
      *,
      reason: str = "No reason provided",
  ):
    try:
      user = await self.bot.fetch_user(int(user_id))
      await ctx.guild.unban(user, reason=reason)
      await ctx.send(f"🕊️ Unbanned **{user.name}**.")
    except Exception as e:
      await ctx.send(
          f"❌ Could not unban user. Check the ID: {e}", ephemeral=True
      )

  @commands.hybrid_command(
      name="timeout", description="Timeout (mute) a member for a set duration."
  )
  @app_commands.describe(
      member="The member to timeout",
      minutes="Duration in minutes",
      reason="Reason",
  )
  @commands.has_permissions(moderate_members=True)
  async def timeout(
      self,
      ctx: commands.Context,
      member: discord.Member,
      minutes: int,
      *,
      reason: str = "No reason",
  ):
    duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(
        f"🔇 Timed out **{member.display_name}** for {minutes} minute(s)."
    )

  @commands.hybrid_command(
      name="untimeout", description="Remove timeout from a member."
  )
  @app_commands.describe(member="The member to remove timeout from")
  @commands.has_permissions(moderate_members=True)
  async def untimeout(self, ctx: commands.Context, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"🔊 Removed timeout from **{member.display_name}**.")

  @commands.hybrid_command(
      name="purge",
      description="Clear a specified number of messages from chat.",
  )
  @app_commands.describe(amount="Number of messages to delete (1-100)")
  @commands.has_permissions(manage_messages=True)
  async def purge(self, ctx: commands.Context, amount: int):
    if amount < 1 or amount > 100:
      return await ctx.send(
          "Please provide a number between 1 and 100.", ephemeral=True
      )
    if ctx.interaction:
      await ctx.interaction.response.defer(ephemeral=True)
      deleted = await ctx.channel.purge(limit=amount)
      await ctx.interaction.followup.send(
          f"🧹 Cleared {len(deleted)} messages!", ephemeral=True
      )
    else:
      await ctx.message.delete()
      deleted = await ctx.channel.purge(limit=amount)
      msg = await ctx.send(f"🧹 Cleared {len(deleted)} messages!")
      await asyncio.sleep(3)
      try:
        await msg.delete()
      except Exception:
        pass

  @commands.hybrid_command(
      name="nuke",
      description="Clone and wipe a channel clean instantly (Nuke channel).",
  )
  @commands.has_permissions(manage_channels=True)
  async def nuke(self, ctx: commands.Context):
    channel = ctx.channel
    position = channel.position
    new_channel = await channel.clone(
        reason=f"Channel nuked by {ctx.author}"
    )
    await channel.delete()
    await new_channel.edit(position=position)
    await new_channel.send(
        f"💥 Channel has been nuked by {ctx.author.mention}!"
    )

  @commands.hybrid_command(
      name="slowmode", description="Set channel slowmode delay."
  )
  @app_commands.describe(seconds="Seconds of slowmode (0 to disable)")
  @commands.has_permissions(manage_channels=True)
  async def slowmode(self, ctx: commands.Context, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
      await ctx.send("⏱️ Slowmode has been disabled.")
    else:
      await ctx.send(f"⏱️ Slowmode set to {seconds} second(s).")

  @commands.hybrid_command(name="roleadd", description="Give a role to a member.")
  @app_commands.describe(member="Target member", role="The role to assign")
  @commands.has_permissions(manage_roles=True)
  async def roleadd(
      self, ctx: commands.Context, member: discord.Member, role: discord.Role
  ):
    await member.add_roles(role)
    await ctx.send(
        f"✅ Added role **{role.name}** to **{member.display_name}**."
    )

  @commands.hybrid_command(
      name="roleremove", description="Remove a role from a member."
  )
  @app_commands.describe(member="Target member", role="The role to remove")
  @commands.has_permissions(manage_roles=True)
  async def roleremove(
      self, ctx: commands.Context, member: discord.Member, role: discord.Role
  ):
    await member.remove_roles(role)
    await ctx.send(
        f"❌ Removed role **{role.name}** from **{member.display_name}**."
    )


async def setup(bot):
  await bot.add_cog(Moderation(bot))
