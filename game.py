"""Simple game management structures for Hand Cricket bot."""

import random


class GameType:
  SINGLE = "SINGLE"
  MULTI = "MULTI"
  DOUBLE = "DOUBLE"
  RUNRACE = "RUNRACE"


class SingleGame:

  def __init__(self, ctx, bot):
    self.type = GameType.SINGLE
    self.player = ctx.author
    self.channel = ctx.channel
    self.bot = bot

  @classmethod
  def create(cls, ctx, bot):
    return cls(ctx=ctx, bot=bot)


class MultiplayerGame:

  def __init__(self, ctx, bot):
    self.type = GameType.MULTI
    self.host = ctx.author.id
    self.channel = ctx.channel
    self.bot = bot
    self.players = [ctx.author]

  @classmethod
  def create(cls, ctx, bot):
    return cls(ctx=ctx, bot=bot)


class DoubleGame:

  def __init__(self, ctx, player, bot):
    self.type = GameType.DOUBLE
    self.players = [ctx.author, player]
    self.channel = ctx.channel
    self.bot = bot

  @classmethod
  def create(cls, ctx, player, bot):
    return cls(ctx=ctx, player=player, bot=bot)


class RunRaceGame:

  def __init__(self, ctx, bot):
    self.type = GameType.RUNRACE
    self.host = ctx.author.id
    self.channel = ctx.channel
    self.bot = bot
    self.players = [ctx.author]

  @classmethod
  def create(cls, ctx, bot):
    return cls(ctx=ctx, bot=bot)
