import asyncio
import os
import random
import re
import threading
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# --- Keep-Alive Web Server for Render ---
app = Flask("")


@app.route("/")
def home():
  return "NOTTYAMERICA is Online!"


def run_web():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = threading.Thread(target=run_web)
  t.start()


# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.invites = True

bot = commands.Bot(command_prefix=".", intents=intents)

# ----------------------------------------------------
# CONFIGURATION & MEMORY CACHES
# ----------------------------------------------------
BOT_OWNER_ID = 859302948172639485

invites_cache = {}
snipe_cache = {}
afk_users = {}
message_counts = {}
invite_counts = {}


def is_bot_owner():
  async def predicate(ctx):
    if ctx.author.id != BOT_OWNER_ID:
      await ctx.send("Hey! Only the legendary owner can use this command.")
      return False
    return True

  return commands.check(predicate)


@bot.event
async def on_ready():
  try:
    await bot.load_extension("minigames")
    print("Loaded 50+ Minigames Extension!")
  except Exception as e:
    print(f"Minigames failed or already loaded: {e}")
    try:
    synced = await bot.tree.sync()
    print(f"Successfully synced {len(synced)} slash command(s) globally!")
  except Exception as e:
    print(f"Failed to sync slash commands: {e}")

  for guild in bot.guilds:
    try:
      invs = await guild.invites()
      invites_cache[guild.id] = invs
      if guild.id not in invite_counts:
        invite_counts[guild.id] = {}
      for inv in invs:
        if inv.inviter:
          invite_counts[guild.id][inv.inviter.id] = (
              invite_counts[guild.id].get(inv.inviter.id, 0) + inv.uses
          )
    except Exception:
      pass

  print(f"NOTTYAMERICA is online and ready! Prefix: '.' and '/'")
  print(f"Logged in as: {bot.user.name}")


@bot.event
async def on_invite_create(invite):
  invites_cache[invite.guild.id] = await invite.guild.invites()


@bot.event
async def on_invite_delete(invite):
  invites_cache[invite.guild.id] = await invite.guild.invites()


@bot.event
async def on_member_join(member):
  try:
    channel = member.guild.system_channel
    if not channel:
      for c in member.guild.text_channels:
        if c.permissions_for(member.guild.me).send_messages:
          channel = c
          break
    if not channel:
      return

    old_invites = invites_cache.get(member.guild.id, [])
    new_invites = await member.guild.invites()
    invites_cache[member.guild.id] = new_invites

    inviter = None
    for new_inv in new_invites:
      for old_inv in old_invites:
        if new_inv.code == old_inv.code and new_inv.uses > old_inv.uses:
          inviter = new_inv.inviter
          break
      if inviter:
        break

    if inviter:
      if member.guild.id not in invite_counts:
        invite_counts[member.guild.id] = {}
      invite_counts[member.guild.id][inviter.id] = (
          invite_counts[member.guild.id].get(inviter.id, 0) + 1
      )

    embed = discord.Embed(
        title="👋 New Member Joined!",
        description=f"Welcome **{member.name}** to the server!",
        color=discord.Color.green(),
    )
    if inviter:
      embed.add_field(
          name="📥 Invited By", value=f"**{inviter.name}**", inline=False
      )
    else:
      embed.add_field(
          name="📥 Invited By", value="Unknown / Custom Link", inline=False
      )

    embed.set_footer(text="Have a good time in chat!")
    await channel.send(embed=embed)
  except Exception as e:
    print(f"Error handling member join: {e}")


@bot.event
async def on_message_delete(message):
  if message.author.bot:
    return

  snipe_cache[message.channel.id] = {
      "author": (
          f"{message.author.name}#{message.author.discriminator}"
          if message.author.discriminator != "0"
          else message.author.name
      ),
      "avatar": message.author.display_avatar.url,
      "content": message.content or "[Embed or Attachment]",
      "time": message.created_at,
  }


@bot.event
async def on_message(message):
  if message.author.bot or not message.guild:
    return

  g_id = message.guild.id
  if g_id not in message_counts:
    message_counts[g_id] = {}
  message_counts[g_id][message.author.id] = (
      message_counts[g_id].get(message.author.id, 0) + 1
  )

  if message.author.id in afk_users:
    afk_data = afk_users.pop(message.author.id)
    try:
      await message.author.edit(nick=afk_data["old_nick"])
    except Exception:
      pass

    embed = discord.Embed(
        title="Welcome Back! 👋",
        description=(
            f"Welcome back {message.author.mention}, I removed your AFK status!"
        ),
        color=discord.Color.green(),
    )
    await message.channel.send(embed=embed)

  if message.mentions:
    for mentioned in message.mentions:
      if mentioned.id in afk_users:
        reason = afk_users[mentioned.id]["reason"]
        embed = discord.Embed(
            title="Saint Notty",
            description=(
                f"⚠️ **{mentioned.name}** is currently AFK!\n**Reason:**"
                f" {reason}"
            ),
            color=discord.Color.gold(),
        )
        await message.channel.send(embed=embed)
        break

  await bot.process_commands(message)


def parse_duration(time_str: str):
  time_str = time_str.lower().strip()
  match = re.match(r"^(\d+)([s|m|h|d])$", time_str)
  if not match:
    return None

  amount = int(match.group(1))
  unit = match.group(2)

  if unit == "s":
    return discord.timedelta(seconds=amount)
  elif unit == "m":
    return discord.timedelta(minutes=amount)
  elif unit == "h":
    return discord.timedelta(hours=amount)
  elif unit == "d":
    return discord.timedelta(days=amount)
  return None


# --- COMMANDS ---
@bot.command(name="gaytest")
async def gaytest_prefix(ctx, member: discord.Member = None):
  target = member or ctx.author
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="🏳️‍🌈 Gay Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** gay! 🌈",
      color=discord.Color.magenta(),
  )
  await ctx.send(embed=embed)


@bot.tree.command(
    name="gaytest", description="Calculate a user's gay percentage (0-250%)."
)
async def gaytest_slash(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member or interaction.user
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="🏳️‍🌈 Gay Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** gay! 🌈",
      color=discord.Color.magenta(),
  )
  await interaction.response.send_message(embed=embed)


@bot.command(name="lesbiantest")
async def lesbiantest_prefix(ctx, member: discord.Member = None):
  target = member or ctx.author
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="👩‍❤️‍👩 Lesbian Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** lesbian! ✨",
      color=discord.Color.purple(),
  )
  await ctx.send(embed=embed)


@bot.tree.command(
    name="lesbiantest",
    description="Calculate a user's lesbian percentage (0-250%).",
)
async def lesbiantest_slash(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member or interaction.user
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="👩‍❤️‍👩 Lesbian Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** lesbian! ✨",
      color=discord.Color.purple(),
  )
  await interaction.response.send_message(embed=embed)


@bot.command(name="baldtest")
async def baldtest_prefix(ctx, member: discord.Member = None):
  target = member or ctx.author
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="👨‍🦲 Bald Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** bald! 🧑‍🦲",
      color=discord.Color.gold(),
  )
  await ctx.send(embed=embed)


@bot.tree.command(
    name="baldtest", description="Calculate a user's bald percentage (0-250%)."
)
async def baldtest_slash(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member or interaction.user
  percentage = random.randint(0, 250)
  embed = discord.Embed(
      title="👨‍🦲 Bald Rate Calculator",
      description=f"**{target.name}** is **{percentage}%** bald! 🧑‍🦲",
      color=discord.Color.gold(),
  )
  await interaction.response.send_message(embed=embed)


@bot.command(name="lb", aliases=["leaderboard"])
async def lb_prefix(ctx, category: str = "messages"):
  category = category.lower().strip()
  guild_id = ctx.guild.id
  if category in ["msg", "messages", "message"]:
    counts = message_counts.get(guild_id, {})
    title = "💬 Message Leaderboard"
    unit_label = "messages"
  elif category in ["inv", "invites", "invite"]:
    counts = invite_counts.get(guild_id, {})
    title = "📥 Invite Leaderboard"
    unit_label = "invites"
  else:
    await ctx.send("❌ Invalid category! Use `.lb messages` or `.lb invites`.")
    return

  if not counts:
    await ctx.send(f"📊 No data recorded yet for {category} leaderboard!")
    return

  sorted_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
  embed = discord.Embed(title=title, color=discord.Color.purple())
  description_lines = [
      f"**#{idx}** <@{user_id}> — **{count}** {unit_label}"
      for idx, (user_id, count) in enumerate(sorted_users, 1)
  ]
  embed.description = "\n".join(description_lines)
  embed.set_footer(text=f"Requested by {ctx.author.name}")
  await ctx.send(embed=embed)


@bot.tree.command(name="lb", description="Display server leaderboards.")
@app_commands.choices(
    category=[
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="Invites", value="invites"),
    ]
)
async def lb_slash(
    interaction: discord.Interaction, category: app_commands.Choice[str]
):
  guild_id = interaction.guild.id
  cat_val = category.value
  counts = (
      message_counts.get(guild_id, {})
      if cat_val == "messages"
      else invite_counts.get(guild_id, {})
  )
  unit_label = "messages" if cat_val == "messages" else "invites"
  title = "💬 Message Leaderboard" if cat_val == "messages" else "📥 Invite Leaderboard"

  if not counts:
    await interaction.response.send_message(
        f"📊 No data recorded yet for {cat_val} leaderboard!", ephemeral=True
    )
    return

  sorted_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
  embed = discord.Embed(title=title, color=discord.Color.purple())
  description_lines = [
      f"**#{idx}** <@{user_id}> — **{count}** {unit_label}"
      for idx, (user_id, count) in enumerate(sorted_users, 1)
  ]
  embed.description = "\n".join(description_lines)
  embed.set_footer(text=f"Requested by {interaction.user.name}")
  await interaction.response.send_message(embed=embed)


@bot.command(name="afk")
async def afk_prefix(ctx, *, reason: str = "AFK"):
  old_nick = ctx.author.display_name
  afk_users[ctx.author.id] = {"reason": reason, "old_nick": old_nick}
  try:
    await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
  except Exception:
    pass
  embed = discord.Embed(
      title="Saint Notty",
      description=(
          f"**AFK Set!**\nYou are now AFK in this server.\n**Reason:** {reason}"
      ),
      color=discord.Color.blue(),
  )
  await ctx.send(embed=embed)


@bot.tree.command(name="afk", description="Set your AFK status.")
async def afk_slash(interaction: discord.Interaction, reason: str = "AFK"):
  old_nick = interaction.user.display_name
  afk_users[interaction.user.id] = {"reason": reason, "old_nick": old_nick}
  try:
    await interaction.user.edit(nick=f"[AFK] {interaction.user.display_name}")
  except Exception:
    pass
  embed = discord.Embed(
      title="Saint Notty",
      description=(
          f"**AFK Set!**\nYou are now AFK in this server.\n**Reason:** {reason}"
      ),
      color=discord.Color.blue(),
  )
  await interaction.response.send_message(embed=embed)


@bot.command(name="praise")
@is_bot_owner()
async def praise_prefix(ctx):
  await ctx.send(f"All hail <@{BOT_OWNER_ID}>! Absolute perfection! ✨")


@bot.tree.command(
    name="praise", description="Shows appreciation for the supreme owner."
)
async def praise_slash(interaction: discord.Interaction):
  if interaction.user.id != BOT_OWNER_ID:
    await interaction.response.send_message(
        "Hey! Only the legendary owner can use this command.", ephemeral=True
    )
    return
  await interaction.response.send_message(
      f"All hail <@{BOT_OWNER_ID}>! Absolute perfection! ✨"
  )


@bot.command(name="snipe", aliases=["revertdelete"])
async def snipe_prefix(ctx):
  sniped_msg = snipe_cache.get(ctx.channel.id)
  if not sniped_msg:
    await ctx.send("❌ No recently deleted messages to snipe here!")
    return
  embed = discord.Embed(
      title="🗑️ Sniped Deleted Message",
      description=sniped_msg["content"],
      color=discord.Color.red(),
  )
  embed.set_author(name=sniped_msg["author"], icon_url=sniped_msg["avatar"])
  await ctx.send(embed=embed)


@bot.tree.command(
    name="snipe", description="Shows the last deleted message in this channel."
)
async def snipe_slash(interaction: discord.Interaction):
  sniped_msg = snipe_cache.get(interaction.channel.id)
  if not sniped_msg:
    await interaction.response.send_message(
        "❌ No recently deleted messages to snipe here!", ephemeral=True
    )
    return
  embed = discord.Embed(
      title="🗑️ Sniped Deleted Message",
      description=sniped_msg["content"],
      color=discord.Color.red(),
  )
  embed.set_author(name=sniped_msg["author"], icon_url=sniped_msg["avatar"])
  await interaction.response.send_message(embed=embed)


@bot.command(name="guess")
async def guess_prefix(ctx):
  await ctx.send(
      "🎮 **Guessing Game!** I'm thinking of a number between 1 and 10 (15"
      " seconds)!"
  )
  secret = random.randint(1, 10)
  try:
    msg = await bot.wait_for(
        "message",
        timeout=15.0,
        check=lambda m: m.author == ctx.author
        and m.channel == ctx.channel
        and m.content.isdigit(),
    )
    if int(msg.content) == secret:
      await ctx.send(f"🎉 Spot on, {ctx.author.mention}!")
    else:
      await ctx.send(f"❌ Wrong! It was **{secret}**.")
  except asyncio.TimeoutError:
    await ctx.send(f"⌛ Time's up! It was **{secret}**.")


@bot.tree.command(name="guess", description="Play a number guessing game!")
async def guess_slash(interaction: discord.Interaction):
  secret = random.randint(1, 10)
  await interaction.response.send_message(
      "🎮 **Guessing Game Started!** Type a number between 1 and 10 in chat!"
  )
  try:
    msg = await bot.wait_for(
        "message",
        timeout=15.0,
        check=lambda m: m.author == interaction.user
        and m.channel == interaction.channel
        and m.content.isdigit(),
    )
    if int(msg.content) == secret:
      await interaction.followup.send(f"🎉 Spot on, {interaction.user.mention}!")
    else:
      await interaction.followup.send(f"❌ Wrong! It was **{secret}**.")
  except asyncio.TimeoutError:
    await interaction.followup.send(f"⌛ Time's up! It was **{secret}**.")


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick_prefix(ctx, member: discord.Member, *, reason: str = None):
  await member.kick(reason=reason)
  await ctx.send(
      f"👢 **{member.name}** has been kicked. Reason: {reason or 'None'}"
  )


@bot.tree.command(name="kick", description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_slash(
    interaction: discord.Interaction, member: discord.Member, reason: str = None
):
  await member.kick(reason=reason)
  await interaction.response.send_message(
      f"👢 **{member.name}** has been kicked. Reason: {reason or 'None'}"
  )


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban_prefix(ctx, member: discord.Member, *, reason: str = None):
  await member.ban(reason=reason)
  await ctx.send(
      f"🔨 **{member.name}** has been banned. Reason: {reason or 'None'}"
  )


@bot.tree.command(name="ban", description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_slash(
    interaction: discord.Interaction, member: discord.Member, reason: str = None
):
  await member.ban(reason=reason)
  await interaction.response.send_message(
      f"🔨 **{member.name}** has been banned. Reason: {reason or 'None'}"
  )


@bot.command(name="purge", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def purge_prefix(ctx, amount: int):
  deleted = await ctx.channel.purge(limit=amount + 1)
  msg = await ctx.send(f"🧹 Deleted **{len(deleted)-1}** messages.")
  await asyncio.sleep(3)
  await msg.delete()


@bot.tree.command(name="purge", description="Bulk delete messages.")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge_slash(interaction: discord.Interaction, amount: int):
  await interaction.response.defer(ephemeral=True)
  deleted = await interaction.channel.purge(limit=amount)
  await interaction.followup.send(
      f"🧹 Deleted **{len(deleted)}** messages.", ephemeral=True
  )


if __name__ == "__main__":
  keep_alive()
  token = os.environ.get("DISCORD_TOKEN")
  bot.run(token)

