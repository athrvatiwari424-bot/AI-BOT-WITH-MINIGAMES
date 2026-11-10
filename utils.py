import math
import discord

BASICRED = 0xE74C3C
MAYABLUE = 0x4C9EEB
BASICGREEN = 0x2ECC71

misc_emojis = {
    'rtj': '✅'
}

class GameType:
    SINGLE = "Single"
    DOUBLE = "Double"
    MULTI = "Multiplayer"
    RUNRACE = "RunRace"

class Innings:
    ONE = 1
    TWO = 2

def pz(number):
    return "s" if number != 1 else ""

def overs(balls):
    full_overs = balls // 6
    remaining_balls = balls % 6
    return f"{full_overs}.{remaining_balls}"

def spacing(text, max_len=12):
    return text[:max_len].ljust(max_len)

async def check_for_milestone(name, channel, prev_score, curr_score, bot):
    if prev_score < 50 <= curr_score:
        try:
            await channel.send(f"🎉 **{name}** reached a half-century (50 runs)! 👏")
        except Exception:
            pass
    elif prev_score < 100 <= curr_score:
        try:
            await channel.send(f"🎉🎉 **{name}** scored a CENTURY (100 runs)! 👑")
        except Exception:
            pass

async def check_for_hattrick(name, timeline, channel, wickets, is_multi, bot):
    if len(timeline) >= 3 and list(timeline)[-3:] == ["W", "W", "W"]:
        try:
            await channel.send(f"🔥 **HAT-TRICK!** **{name}** took 3 wickets in 3 balls!")
        except Exception:
            pass
        return True
    return False

def check_for_other_games(bot, user):
    for game in bot.games.values():
        if user in game.players:
            return True
    return False

async def send_message(bot, ctx, user=None, content=None, embed=None):
    target = ctx or user
    if target:
        try:
            return await target.send(content=content, embed=embed)
        except discord.Forbidden:
            pass
    return None

# Scorecard visual template coordinate placeholders
template1 = {
    'font_sizes': [24, 18, 14],
    'coordinates': [(20, 20), (20, 80), (20, 120), (20, 150), (20, 200), (20, 240), (20, 280), (20, 320), (20, 360), (20, 400), (20, 440)],
    'colour': (255, 255, 255),
    'spacing': [4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
    'newline': ['\n', '\n', '\n', '\n', '\n']
}
template2 = template1
template3 = template1
