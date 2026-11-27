"""Liebe's expanded game library. No external packages beyond discord.py/aiosqlite."""
from __future__ import annotations
import asyncio, random, string, time
from dataclasses import dataclass
import discord
from discord import app_commands
from discord.ext import commands

# New games are grouped so the Discord select menu never exceeds its 25-option limit.
CATALOG = {
    "Board & Strategy": ["Chess", "Checkers", "Battleship", "Ludo", "Snakes & Ladders"],
    "Cards & Classics": ["UNO", "Blackjack", "2048", "Minesweeper", "Memory Match"],
    "Words & Puzzles": ["Wordle", "Who Am I?", "Word Chain", "Sentence Builder", "Typing Race"],
    "Party & Multiplayer": ["Would You Rather", "Reaction Speed", "Number Guessing Race", "Math Battle", "Mafia / Werewolf"],
    "Quizzes & Challenges": ["Quiz Battle", "Geography Quiz", "Movie & Anime Quiz", "Flag Guessing", "Riddle Battle"],
}

QUIZZES = {
    "Geography Quiz": [
        ("What is the capital of Japan?", ["Seoul", "Tokyo", "Beijing", "Bangkok"], 1),
        ("Which is the largest ocean?", ["Atlantic", "Indian", "Pacific", "Arctic"], 2),
        ("The Nile flows into which sea?", ["Red Sea", "Arabian Sea", "Mediterranean Sea", "Black Sea"], 2),
        ("Which country has the city of Barcelona?", ["Portugal", "Spain", "Italy", "France"], 1),
        ("Mount Everest lies in which mountain range?", ["Andes", "Alps", "Himalayas", "Rockies"], 2),
    ],
    "Movie & Anime Quiz": [
        ("In Naruto, what is Naruto's signature technique?", ["Chidori", "Rasengan", "Bankai", "Kamehameha"], 1),
        ("Which film features the kingdom of Arendelle?", ["Moana", "Frozen", "Tangled", "Brave"], 1),
        ("In One Piece, what is Luffy's dream?", ["Become Hokage", "Find the One Piece and become Pirate King", "Become a Marine", "Find the Dragon Balls"], 1),
        ("Which anime features the Survey Corps?", ["Bleach", "Demon Slayer", "Attack on Titan", "Jujutsu Kaisen"], 2),
        ("Who is the wizarding-school headmaster in much of Harry Potter?", ["Snape", "Dumbledore", "Hagrid", "Sirius"], 1),
    ],
    "Quiz Battle": [
        ("What is the chemical symbol for gold?", ["Ag", "Au", "Fe", "Gd"], 1),
        ("How many sides does a hexagon have?", ["5", "6", "7", "8"], 1),
        ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Mercury"], 1),
        ("What is the largest mammal?", ["Elephant", "Blue whale", "Giraffe", "Orca"], 1),
        ("How many players are on the field for one football team?", ["9", "10", "11", "12"], 2),
    ],
}
FLAGS = [("🇮🇳", "India"), ("🇯🇵", "Japan"), ("🇧🇷", "Brazil"), ("🇨🇦", "Canada"), ("🇫🇷", "France"), ("🇦🇺", "Australia"), ("🇩🇪", "Germany"), ("🇿🇦", "South Africa")]
RIDDLES = [("I have keys but no locks, space but no room. What am I?", "keyboard"), ("What has to be broken before you can use it?", "egg"), ("What gets wetter as it dries?", "towel"), ("What has a face and two hands but no arms or legs?", "clock"), ("What has many teeth but cannot bite?", "comb")]
WHO = [("I am a planet famous for my rings.", "saturn"), ("I am a web language that gives pages structure.", "html"), ("I am the fastest land animal.", "cheetah"), ("I am the fictional detective who lives at 221B Baker Street.", "sherlock holmes"), ("I am the largest hot desert on Earth.", "sahara")]
WYRS = [("Explore the ocean depths or visit outer space?", "🌊 Ocean", "🚀 Space"), ("Have a dragon companion or a robot assistant?", "🐉 Dragon", "🤖 Robot"), ("Live in a fantasy castle or a futuristic city?", "🏰 Castle", "🌆 Future city"), ("Master every instrument or every language?", "🎸 Instruments", "🗣️ Languages")]
WORDS = ["GALAXY", "PYTHON", "DISCORD", "CRICKET", "DIAMOND", "PUZZLE", "ORBIT", "CASTLE", "PLANET"]

async def _record(guild_id: int, user_id: int, game: str, result: str = "win"):
    try:
        from minigames import record_result
        return await record_result(guild_id, user_id, game, result)
    except Exception:
        return []

class AnswerModal(discord.ui.Modal):
    def __init__(self, view: "SoloGameView", title: str, label: str = "Your answer", placeholder: str = "Type your answer"):
        super().__init__(title=title, timeout=120)
        self.game_view = view
        self.answer = discord.ui.TextInput(label=label, placeholder=placeholder, max_length=100)
        self.add_item(self.answer)
    async def on_submit(self, interaction: discord.Interaction):
        await self.game_view.submit_answer(interaction, str(self.answer.value).strip())

class SoloGameView(discord.ui.View):
    def __init__(self, owner: discord.Member, game: str):
        super().__init__(timeout=180)
        self.owner, self.game = owner, game
        self.done = False
        self.data = {}
        self.message = None
        self._build()
    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("This is someone else's game. Open `/moregames` to play your own.", ephemeral=True)
            return False
        if self.done:
            await interaction.response.send_message("This round has already ended.", ephemeral=True)
            return False
        return True
    def _add_answer(self, label="Submit answer", placeholder="Type your answer"):
        b = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, emoji="✍️")
        async def cb(i): await i.response.send_modal(AnswerModal(self, self.game, placeholder=placeholder))
        b.callback = cb; self.add_item(b)
    def _build(self):
        g = self.game
        if g in ("Wordle", "Who Am I?", "Word Chain", "Sentence Builder", "Typing Race", "Number Guessing Race", "Math Battle", "Riddle Battle", "Flag Guessing"):
            self._add_answer()
        elif g == "Would You Rather":
            self.add_item(ChoiceButton("Option A", "a")); self.add_item(ChoiceButton("Option B", "b"))
            for x in self.children: x.view_ref = self
        elif g == "Reaction Speed":
            b = discord.ui.Button(label="Wait for green…", style=discord.ButtonStyle.secondary, disabled=True)
            self.add_item(b)
            self.add_item(ReactionStartButton())
            for x in self.children: x.view_ref = self
        elif g == "2048":
            for label, direction in (("⬆️", "up"), ("⬅️", "left"), ("⬇️", "down"), ("➡️", "right")):
                b=discord.ui.Button(label=label,style=discord.ButtonStyle.primary)
                async def cb(i, d=direction): await self.move_2048(i,d)
                b.callback=cb; self.add_item(b)
            self.data["board"] = [[0,0,0,0] for _ in range(4)]; self._spawn(); self._spawn()
            self.add_item(ResetButton())
            self.children[-1].view_ref=self
        elif g == "Minesweeper":
            self.data.update(mines=set(random.sample(range(25),5)), revealed=set(), flags=set())
            for n in range(25):
                b=discord.ui.Button(label="　",style=discord.ButtonStyle.secondary,row=n//5)
                async def cb(i, idx=n): await self.reveal_mine(i,idx)
                b.callback=cb; self.add_item(b)
        elif g == "Memory Match":
            self.data.update(cards=random.sample(["🍎","🍎","🚀","🚀","🐱","🐱","⚽","⚽","🌙","🌙","🎸","🎸"],12), shown=set(), matched=set(), first=None)
            for n in range(12):
                b=discord.ui.Button(label="❔",style=discord.ButtonStyle.secondary,row=n//4)
                async def cb(i, idx=n): await self.memory_pick(i,idx)
                b.callback=cb; self.add_item(b)
        elif g == "Blackjack":
            self.data.update(player=[self._card(),self._card()], dealer=[self._card(),self._card()], ended=False)
            for label, action in (("Hit", "hit"),("Stand", "stand")):
                b=discord.ui.Button(label=label,style=discord.ButtonStyle.primary)
                async def cb(i,a=action): await self.blackjack_action(i,a)
                b.callback=cb; self.add_item(b)
        elif g == "Chess":
            self.data["board"] = [list("rnbqkbnr"),list("pppppppp"),list("........"),list("........"),list("........"),list("........"),list("PPPPPPPP"),list("RNBQKBNR")]
            self.data["turn"]="white"; self.data["selected"]=None
            self._add_answer("Enter move", "Example: e2e4")
        elif g == "Checkers":
            self.data["board"] = [["b" if (r<3 and (r+c)%2) else "r" if (r>4 and (r+c)%2) else "." for c in range(8)] for r in range(8)]
            self.data["turn"]="r"; self._add_answer("Enter move", "Example: b6c5")
        elif g == "Battleship":
            self.data.update(ships=set(random.sample(range(25),5)), shots=set(), hits=0)
            for n in range(25):
                b=discord.ui.Button(label="🌊",style=discord.ButtonStyle.primary,row=n//5)
                async def cb(i,idx=n): await self.battleship_shot(i,idx)
                b.callback=cb; self.add_item(b)
        elif g == "Ludo":
            self.data.update(position=0, turns=0)
            b=discord.ui.Button(label="🎲 Roll dice",style=discord.ButtonStyle.success)
            b.callback=self.ludo_roll; self.add_item(b)
        elif g == "Snakes & Ladders":
            self.data.update(position=0, turns=0)
            b=discord.ui.Button(label="🎲 Roll dice",style=discord.ButtonStyle.success)
            b.callback=self.snake_roll; self.add_item(b)
        elif g == "UNO":
            if "hand" not in self.data:
                colors=["🔴","🟡","🟢","🔵"]
                deck=[(c,str(v)) for c in colors for v in range(10)]
                random.shuffle(deck); self.data.update(hand=deck[:7], top=deck[7], deck=deck[8:])
            for n,(c,v) in enumerate(self.data["hand"]):
                b=discord.ui.Button(label=f"{c} {v}",style=discord.ButtonStyle.primary,row=n//5)
                async def cb(i,idx=n): await self.uno_play(i,idx)
                b.callback=cb; self.add_item(b)
            draw=discord.ui.Button(label="Draw",style=discord.ButtonStyle.secondary)
            draw.callback=self.uno_draw; self.add_item(draw)
        elif g == "Mafia / Werewolf":
            self.data.update(role=random.choice(["Villager","Detective","Doctor","Werewolf"]), revealed=False)
            b=discord.ui.Button(label="Reveal my role",style=discord.ButtonStyle.primary)
            b.callback=self.mafia_reveal; self.add_item(b)
        else:
            self._add_answer()
    def embed(self):
        g=self.game; d=self.data
        if g in QUIZZES: return discord.Embed(title=f"🧠 {g}",description=d.get("question", "Choose the correct answer."),color=discord.Color.blurple())
        if g=="Wordle": return discord.Embed(title="🟩 Wordle",description="Guess the five-letter word in six tries. Type a five-letter word.",color=discord.Color.blurple())
        if g=="Who Am I?": return discord.Embed(title="🕵️ Who Am I?",description=d["prompt"],color=discord.Color.blurple())
        if g=="Would You Rather": return discord.Embed(title="🤔 Would You Rather",description=d["prompt"]+"\n\nChoose one.",color=discord.Color.blurple())
        if g=="Typing Race": return discord.Embed(title="⌨️ Typing Race",description=f"Type this sentence exactly:\n```{d['prompt']}```",color=discord.Color.blurple())
        if g=="Number Guessing Race": return discord.Embed(title="🔢 Number Guess",description="Guess the secret number between 1 and 100.",color=discord.Color.blurple())
        if g=="Math Battle": return discord.Embed(title="➗ Math Battle",description=f"Solve: **{d['question']}**",color=discord.Color.blurple())
        if g=="Riddle Battle": return discord.Embed(title="🧩 Riddle Battle",description=d["prompt"],color=discord.Color.blurple())
        if g=="Flag Guessing": return discord.Embed(title="🏳️ Flag Guessing",description=f"Which country does this flag represent?\n\n# {d['flag']}",color=discord.Color.blurple())
        if g=="Word Chain": return discord.Embed(title="🔗 Word Chain",description="Start with any word. Each next word must begin with the last letter of the previous word. Enter a word to continue.",color=discord.Color.blurple())
        if g=="Sentence Builder": return discord.Embed(title="✍️ Sentence Builder",description="Build a sentence using all three words: **moon**, **river**, **clock**.",color=discord.Color.blurple())
        if g=="2048": return discord.Embed(title="🔢 2048",description=self._board2048()+"\nUse the arrow buttons to slide tiles. Reach 2048.",color=discord.Color.blurple())
        if g=="Minesweeper": return discord.Embed(title="💣 Minesweeper",description="Tap tiles to reveal them. Find 20 safe tiles without hitting a mine.",color=discord.Color.blurple())
        if g=="Memory Match": return discord.Embed(title="🧠 Memory Match",description="Find all six matching pairs. Tap two cards at a time.",color=discord.Color.blurple())
        if g=="Blackjack": return discord.Embed(title="🃏 Blackjack",description=f"Your hand: **{d['player']}** (total {self._total(d['player'])})\nDealer shows: **{d['dealer'][0]}**\nHit or stand.",color=discord.Color.blurple())
        if g in ("Chess","Checkers"): return discord.Embed(title=f"♟️ {g}",description=self._render_board()+"\nEnter a move like `e2e4` (Chess) or `b6c5` (Checkers). This lightweight version validates basic piece movement.",color=discord.Color.blurple())
        if g=="Battleship": return discord.Embed(title="🚢 Battleship Solo",description=f"Find the five hidden ships on the 5×5 grid. Hits: **{d['hits']}/5**",color=discord.Color.blurple())
        if g=="Ludo": return discord.Embed(title="🎲 Ludo Sprint",description=f"Your token is on square **{d['position']}/30**. Roll a six to leave home; reach 30 to win.",color=discord.Color.blurple())
        if g=="Snakes & Ladders": return discord.Embed(title="🐍 Snakes & Ladders",description=f"You are on square **{d['position']}/100**. Roll to reach 100. Snakes and ladders are active.",color=discord.Color.blurple())
        if g=="UNO": return discord.Embed(title="🃏 UNO Solo",description=f"Top card: **{d['top'][0]} {d['top'][1]}**\nYour hand: **{len(d['hand'])} cards**. Play a matching color or number, or draw.",color=discord.Color.blurple())
        if g=="Mafia / Werewolf": return discord.Embed(title="🌙 Mafia / Werewolf (Role Demo)",description="A private role assignment demo. For a real social-deduction round, invite several players in a future multiplayer lobby.",color=discord.Color.blurple())
        return discord.Embed(title=f"🎮 {g}",description="Game ready.",color=discord.Color.blurple())
    async def submit_answer(self, interaction, answer):
        g=self.game; d=self.data; a=answer.strip()
        if g=="Wordle":
            if len(a)!=5 or not a.isalpha(): return await interaction.response.send_message("Enter exactly five letters.",ephemeral=True)
            target=d.setdefault("target",random.choice(["APPLE","BRICK","CLOUD","GRAPE","PLANT","SMILE","TRAIN","WATER"]))
            d.setdefault("guesses",[]).append(a.upper())
            if a.upper()==target: return await self.finish(interaction,True,f"Correct! The word was **{target}**.")
            if len(d["guesses"])>=6: return await self.finish(interaction,False,f"Out of tries. The word was **{target}**.")
            return await interaction.response.edit_message(embed=discord.Embed(title="🟩 Wordle",description="\n".join(f"`{x}`" for x in d["guesses"])+f"\n\n{6-len(d['guesses'])} guesses left.",color=discord.Color.blurple()),view=self)
        if g=="Who Am I?": return await self.finish(interaction,a.lower()==d["answer"],f"Answer: **{d['answer'].title()}**")
        if g=="Typing Race":
            elapsed=max(0.1,time.monotonic()-d["started"]); correct=a==d["prompt"]
            return await self.finish(interaction,correct,f"{'Perfect typing!' if correct else 'Not an exact match.'} Time: **{elapsed:.2f}s**")
        if g=="Number Guessing Race":
            try: n=int(a)
            except ValueError: return await interaction.response.send_message("Enter a whole number.",ephemeral=True)
            if n==d["target"]: return await self.finish(interaction,True,f"Correct! The number was **{n}** in {d['tries']+1} guesses.")
            d["tries"]+=1
            if d["tries"]>=10: return await self.finish(interaction,False,f"No guesses left. The number was **{d['target']}**.")
            return await interaction.response.send_message(("Too low!" if n<d["target"] else "Too high!")+f" {10-d['tries']} guesses left.",ephemeral=True)
        if g=="Math Battle": return await self.finish(interaction,a==str(d["answer"]),f"Correct answer: **{d['answer']}**")
        if g=="Riddle Battle": return await self.finish(interaction,a.lower()==d["answer"],f"Answer: **{d['answer']}**")
        if g=="Flag Guessing": return await self.finish(interaction,a.lower()==d["answer"].lower(),f"Country: **{d['answer']}**")
        if g=="Word Chain":
            word=a.lower()
            if not word.isalpha() or len(word)<2: return await interaction.response.send_message("Enter a word with at least two letters.",ephemeral=True)
            previous=d.get("last")
            if previous and word[0]!=previous[-1]: return await interaction.response.send_message(f"Your word must start with **{previous[-1].upper()}**.",ephemeral=True)
            if word in d.setdefault("used",set()): return await interaction.response.send_message("That word was already used.",ephemeral=True)
            d["used"].add(word); d["last"]=word; d["count"]=d.get("count",0)+1
            if d["count"]>=10: return await self.finish(interaction,True,"You completed a chain of 10 unique words!")
            return await interaction.response.edit_message(embed=discord.Embed(title="🔗 Word Chain",description=f"Last word: **{word}**\nNext word must start with **{word[-1].upper()}**.\nWords: {d['count']}/10",color=discord.Color.blurple()),view=self)
        if g=="Sentence Builder":
            low=a.lower()
            ok=all(w in low for w in ("moon","river","clock")) and len(a.split())>=5
            return await self.finish(interaction,ok,"Your sentence must contain moon, river and clock and have at least five words." if not ok else f"Your sentence:\n> {a}")
        if g=="Chess": return await self._chess_move(interaction,a)
        if g=="Checkers": return await self._checkers_move(interaction,a)
        await interaction.response.send_message("That answer does not apply to this game.",ephemeral=True)
    async def finish(self, interaction, won, detail):
        self.done=True
        for x in self.children: x.disabled=True
        unlocked=await _record(interaction.guild_id,interaction.user.id,self.game,"win" if won else "loss") if interaction.guild_id else []
        extra="\n🏅 Achievement unlocked!" if unlocked else ""
        await interaction.response.edit_message(embed=discord.Embed(title=f"{'🏆 Victory' if won else '🎮 Round complete'} · {self.game}",description=detail+extra,color=discord.Color.green() if won else discord.Color.gold()),view=self)
    def _spawn(self):
        b=self.data["board"]; empty=[(r,c) for r in range(4) for c in range(4) if b[r][c]==0]
        if empty:
            r,c=random.choice(empty); b[r][c]=4 if random.random()<.1 else 2
    def _board2048(self): return "\n".join(" | ".join(str(x or "·").rjust(4) for x in row) for row in self.data["board"])
    async def move_2048(self,i,direction):
        b=self.data["board"]
        for r in range(4):
            line=b[r][:] if direction in ("left","right") else [b[x][r] for x in range(4)]
            if direction in ("right","down"): line.reverse()
            vals=[x for x in line if x]; out=[]; k=0
            while k<len(vals):
                if k+1<len(vals) and vals[k]==vals[k+1]: out.append(vals[k]*2); k+=2
                else: out.append(vals[k]); k+=1
            out += [0]*(4-len(out))
            if direction in ("right","down"): out.reverse()
            if direction in ("left","right"): b[r]=out
            else:
                for x in range(4): b[x][r]=out[x]
        self._spawn()
        if any(v>=2048 for row in b for v in row): return await self.finish(i,True,"You reached 2048!")
        await i.response.edit_message(embed=self.embed(),view=self)
    async def reveal_mine(self,i,idx):
        d=self.data
        if idx in d["revealed"]: return await i.response.send_message("Already revealed.",ephemeral=True)
        d["revealed"].add(idx); b=self.children[idx]
        if idx in d["mines"]:
            b.label="💣"; b.style=discord.ButtonStyle.danger
            for x in self.children: x.disabled=True
            return await self.finish(i,False,"You found a mine. Better luck next round.")
        b.label="🟩"; b.style=discord.ButtonStyle.success; b.disabled=True
        if len(d["revealed"]-d["mines"])>=20: return await self.finish(i,True,"You cleared all safe tiles!")
        await i.response.edit_message(embed=discord.Embed(title="💣 Minesweeper",description=f"Safe tiles: **{len(d['revealed'])}/20**",color=discord.Color.blurple()),view=self)
    async def memory_pick(self,i,idx):
        d=self.data
        if idx in d["matched"] or idx in d["shown"]: return await i.response.send_message("Choose a hidden card.",ephemeral=True)
        d["shown"].add(idx); self.children[idx].label=d["cards"][idx]
        if d["first"] is None: d["first"]=idx; return await i.response.edit_message(embed=self.embed(),view=self)
        first=d["first"]; d["first"]=None
        if d["cards"][first]==d["cards"][idx]:
            d["matched"].update((first,idx)); self.children[first].disabled=True; self.children[idx].disabled=True
            if len(d["matched"])==12: return await self.finish(i,True,"All six pairs matched!")
        else:
            await i.response.edit_message(embed=discord.Embed(title="🧠 Memory Match",description=f"No match. Pairs found: **{len(d['matched'])//2}/6**",color=discord.Color.blurple()),view=self)
            await asyncio.sleep(0.9)
            self.children[first].label="❔"; self.children[idx].label="❔"; d["shown"].difference_update((first,idx))
            try: await i.message.edit(view=self)
            except discord.HTTPException: pass
            return
        await i.response.edit_message(embed=discord.Embed(title="🧠 Memory Match",description=f"Pairs found: **{len(d['matched'])//2}/6**",color=discord.Color.blurple()),view=self)
    @staticmethod
    def _card(): return random.randint(1,13)
    @staticmethod
    def _total(cards):
        total=sum(11 if x==1 else min(x,10) for x in cards)
        aces=sum(1 for x in cards if x==1)
        while total>21 and aces:
            total-=10; aces-=1
        return total
    async def blackjack_action(self,i,action):
        d=self.data
        if action=="hit": d["player"].append(self._card())
        else:
            while self._total(d["dealer"])<17: d["dealer"].append(self._card())
            p, dealer=self._total(d["player"]),self._total(d["dealer"])
            win=p<=21 and (dealer>21 or p>dealer)
            draw=p==dealer
            return await self.finish(i,win,"Push." if draw else f"You: **{p}** · Dealer: **{dealer}**. {'You win!' if win else 'Dealer wins.'}")
        if self._total(d["player"])>21: return await self.finish(i,False,f"Bust! Your total was {self._total(d['player'])}.")
        await i.response.edit_message(embed=self.embed(),view=self)
    async def battleship_shot(self,i,idx):
        d=self.data
        if idx in d["shots"]: return await i.response.send_message("You already fired there.",ephemeral=True)
        d["shots"].add(idx); hit=idx in d["ships"]
        self.children[idx].label="💥" if hit else "·"; self.children[idx].style=discord.ButtonStyle.danger if hit else discord.ButtonStyle.secondary; self.children[idx].disabled=True
        if hit: d["hits"]+=1
        if d["hits"]==5: return await self.finish(i,True,"All five hidden ships found!")
        await i.response.edit_message(embed=discord.Embed(title="🚢 Battleship Solo",description=f"{'Hit!' if hit else 'Miss.'}\nHits: **{d['hits']}/5**",color=discord.Color.blurple()),view=self)
    async def ludo_roll(self,i):
        roll=random.randint(1,6); d=self.data
        if d["position"]==0 and roll==6: d["position"]=1
        elif d["position"]>0: d["position"]=min(30,d["position"]+roll)
        d["turns"]+=1
        if d["position"]>=30: return await self.finish(i,True,f"You reached home in {d['turns']} rolls!")
        await i.response.edit_message(embed=discord.Embed(title="🎲 Ludo Sprint",description=f"You rolled **{roll}**. Position: **{d['position']}/30**. {'Roll a 6 to leave home.' if d['position']==0 else 'Keep going!'}",color=discord.Color.blurple()),view=self)
    async def snake_roll(self,i):
        roll=random.randint(1,6); d=self.data; pos=min(100,d["position"]+roll)
        jumps={4:14,9:31,20:38,28:84,40:59,63:81,71:91,17:7,54:34,62:19,64:60,87:24,93:73,95:75,99:78}
        d["position"]=jumps.get(pos,pos)
        if d["position"]>=100: return await self.finish(i,True,f"You reached 100 in {d['turns']+1} rolls!")
        d["turns"]+=1
        await i.response.edit_message(embed=discord.Embed(title="🐍 Snakes & Ladders",description=f"Rolled **{roll}**. You moved to **{d['position']}**.",color=discord.Color.blurple()),view=self)
    async def uno_play(self,i,idx):
        d=self.data; card=d["hand"][idx]
        if card[0]!=d["top"][0] and card[1]!=d["top"][1]: return await i.response.send_message("Card must match color or number.",ephemeral=True)
        d["top"]=card; d["hand"].pop(idx); self.clear_items(); self._build()
        if not d["hand"]: return await self.finish(i,True,"UNO! You played your last card.")
        await i.response.edit_message(embed=self.embed(),view=self)
    async def uno_draw(self,i):
        d=self.data
        if not d["deck"]: return await i.response.send_message("The deck is empty.",ephemeral=True)
        d["hand"].append(d["deck"].pop()); self.clear_items(); self._build()
        await i.response.edit_message(embed=self.embed(),view=self)
    async def mafia_reveal(self,i):
        self.data["revealed"]=True
        await i.response.send_message(f"Your private role is **{self.data['role']}**. This is a role demo, not a full multiplayer round.",ephemeral=True)
    def _render_board(self):
        return "\n".join(" ".join(row) for row in self.data["board"])
    async def _chess_move(self,i,move):
        move=move.lower().replace(" ","")
        if len(move)!=4 or move[0] not in "abcdefgh" or move[2] not in "abcdefgh" or move[1] not in "12345678" or move[3] not in "12345678":
            return await i.response.send_message("Use coordinate notation like `e2e4`.",ephemeral=True)
        b=self.data["board"]; c1=ord(move[0])-97; r1=8-int(move[1]); c2=ord(move[2])-97; r2=8-int(move[3]); piece=b[r1][c1]
        if piece=="." or (piece.isupper()!=(self.data["turn"]=="white")): return await i.response.send_message("Select one of your own pieces.",ephemeral=True)
        # Basic piece movement validation. Check/checkmate, castling and en passant are intentionally not implemented in this lite board mode.
        dr,dc=r2-r1,c2-c1; target=b[r2][c2]
        if target!="." and target.isupper()==piece.isupper(): return await i.response.send_message("You cannot capture your own piece.",ephemeral=True)
        kind=piece.lower(); ok=False
        if kind=="n": ok=(abs(dr),abs(dc)) in ((1,2),(2,1))
        elif kind=="k": ok=max(abs(dr),abs(dc))==1
        elif kind=="r": ok=(dr==0 or dc==0) and self._clear_path(b,r1,c1,r2,c2)
        elif kind=="b": ok=abs(dr)==abs(dc) and self._clear_path(b,r1,c1,r2,c2)
        elif kind=="q": ok=(dr==0 or dc==0 or abs(dr)==abs(dc)) and self._clear_path(b,r1,c1,r2,c2)
        elif kind=="p":
            step=-1 if piece.isupper() else 1; start=6 if piece.isupper() else 1
            ok=(dc==0 and dr==step and target==".") or (dc==0 and dr==2*step and r1==start and target=="." and b[r1+step][c1]==".") or (abs(dc)==1 and dr==step and target!=".")
        if not ok: return await i.response.send_message("That move is not valid in this Chess Lite mode.",ephemeral=True)
        if target.lower()=="k": return await self.finish(i,True,"You captured the opposing king in this Chess Lite practice board.")
        b[r2][c2]=piece; b[r1][c1]="."; self.data["turn"]="black" if self.data["turn"]=="white" else "white"
        await i.response.edit_message(embed=self.embed(),view=self)
    @staticmethod
    def _clear_path(b,r1,c1,r2,c2):
        dr=(r2>r1)-(r2<r1); dc=(c2>c1)-(c2<c1); r,c=r1+dr,c1+dc
        while (r,c)!=(r2,c2):
            if b[r][c]!=".": return False
            r+=dr; c+=dc
        return True
    async def _checkers_move(self,i,move):
        move=move.lower().replace(" ","")
        if len(move)!=4 or move[0] not in "abcdefgh" or move[2] not in "abcdefgh" or move[1] not in "12345678" or move[3] not in "12345678": return await i.response.send_message("Use coordinates like `b6c5`.",ephemeral=True)
        b=self.data["board"]; c1=ord(move[0])-97; r1=8-int(move[1]); c2=ord(move[2])-97; r2=8-int(move[3]); p=b[r1][c1]
        if p=="." or p.lower()!=self.data["turn"]: return await i.response.send_message("Select one of your pieces.",ephemeral=True)
        dr,dc=r2-r1,c2-c1
        if b[r2][c2]!=".": return await i.response.send_message("Destination square is occupied.",ephemeral=True)
        step=-1 if p.lower()=="r" else 1
        if p.isupper(): step_options=(-1,1)
        else: step_options=(step,)
        if abs(dc)==1 and dr in step_options:
            pass
        elif abs(dc)==2 and dr in (2*x for x in step_options):
            jump_step=dr//2
            mr,mc=r1+jump_step,c1+(1 if dc>0 else -1)
            enemy = "b" if p.lower()=="r" else "r"
            if b[mr][mc] not in (enemy, enemy.upper()):
                return await i.response.send_message("A jump must capture an opposing piece.",ephemeral=True)
            b[mr][mc]="."
        else: return await i.response.send_message("Use a one-square diagonal move or a two-square jump over an opponent.",ephemeral=True)
        b[r2][c2]=p; b[r1][c1]="."
        if (p=="r" and r2==0) or (p=="b" and r2==7): b[r2][c2]=p.upper()
        opponent="b" if p in ("r","R") else "r"
        if not any(x.lower()==opponent for row in b for x in row): return await self.finish(i,True,"All opposing checkers have been captured.")
        self.data["turn"]=opponent
        await i.response.edit_message(embed=self.embed(),view=self)

class ChoiceButton(discord.ui.Button):
    def __init__(self,label,value): super().__init__(label=label,style=discord.ButtonStyle.primary); self.value_key=value; self.view_ref=None
    async def callback(self,i):
        v=self.view_ref; v.done=True
        if i.guild_id: await _record(i.guild_id, i.user.id, v.game, "win")
        await i.response.edit_message(embed=discord.Embed(title="🤔 Would You Rather",description=f"You chose **{self.label}**. Your choice has been recorded for this round.",color=discord.Color.green()),view=None)
class ReactionStartButton(discord.ui.Button):
    def __init__(self): super().__init__(label="Start reaction test",style=discord.ButtonStyle.success); self.view_ref=None
    async def callback(self,i):
        v=self.view_ref; self.disabled=True; wait=random.uniform(1.5,4.0); await i.response.edit_message(embed=discord.Embed(title="⚡ Reaction Speed",description="Wait for the green button...",color=discord.Color.orange()),view=v)
        await asyncio.sleep(wait)
        b=discord.ui.Button(label="CLICK NOW!",style=discord.ButtonStyle.success)
        v.clear_items(); v.add_item(b); v.data["green_at"]=time.monotonic()
        async def click(inter):
            if inter.user.id!=v.owner.id: return await inter.response.send_message("Not your test.",ephemeral=True)
            elapsed=(time.monotonic()-v.data["green_at"])*1000; v.done=True
            if inter.guild_id: await _record(inter.guild_id, inter.user.id, v.game, "win")
            await inter.response.edit_message(embed=discord.Embed(title="⚡ Reaction Result",description=f"Your reaction time: **{elapsed:.0f} ms**",color=discord.Color.green()),view=None)
        b.callback=click
        if v.message: await v.message.edit(embed=discord.Embed(title="⚡ Reaction Speed",description="CLICK!",color=discord.Color.green()),view=v)
class ResetButton(discord.ui.Button):
    def __init__(self): super().__init__(label="Reset",style=discord.ButtonStyle.secondary); self.view_ref=None
    async def callback(self,i):
        v=self.view_ref; v.data["board"]=[[0]*4 for _ in range(4)]; v._spawn(); v._spawn()
        await i.response.edit_message(embed=v.embed(),view=v)

class CategorySelect(discord.ui.Select):
    def __init__(self): super().__init__(placeholder="Choose a game category",options=[discord.SelectOption(label=k,description=f"{len(v)} games",emoji=e) for (k,v),e in zip(CATALOG.items(),["♟️","🃏","🔤","🎉","🧠"])])
    async def callback(self,i): await i.response.edit_message(embed=discord.Embed(title=f"🎮 {self.values[0]}",description="Choose a game to launch.",color=discord.Color.blurple()),view=GameSelectView(i.user,self.values[0]))
class GameSelectView(discord.ui.View):
    def __init__(self,owner,category):
        super().__init__(timeout=180); self.owner=owner; self.category=category
        self.add_item(GameSelect(category))
        back=discord.ui.Button(label="Back to categories",style=discord.ButtonStyle.secondary)
        async def cb(i): await i.response.edit_message(embed=discord.Embed(title="🎮 Liebe · More Games",description="Choose a category.",color=discord.Color.blurple()),view=MoreGamesView(owner))
        back.callback=cb; self.add_item(back)
    async def interaction_check(self,i):
        if i.user.id!=self.owner.id: await i.response.send_message("Open `/moregames` to use your own menu.",ephemeral=True); return False
        return True
class GameSelect(discord.ui.Select):
    def __init__(self, category): super().__init__(placeholder="Select a game",options=[discord.SelectOption(label=g) for g in CATALOG[category]])
    async def callback(self,i):
        # The category menu only exposes games from its selected category.
        category=self.view.category; game=self.values[0]
        if game not in CATALOG[category]: return await i.response.send_message("Choose a game from this category.",ephemeral=True)
        view=SoloGameView(i.user,game); view.message=i.message
        if game=="Who Am I?": view.data["prompt"],view.data["answer"]=random.choice(WHO)
        elif game=="Would You Rather": q,a,b=random.choice(WYRS); view.data["prompt"]=q; view.clear_items(); view.add_item(ChoiceButton(a,"a")); view.add_item(ChoiceButton(b,"b")); [setattr(x,"view_ref",view) for x in view.children]
        elif game=="Typing Race": view.data["prompt"]=random.choice(["Liebe is ready for a challenge.","Discord games bring everyone together.","Quick fingers and sharp focus win."]); view.data["started"]=time.monotonic()
        elif game=="Number Guessing Race": view.data["target"]=random.randint(1,100); view.data["tries"]=0
        elif game=="Math Battle": x,y=random.randint(2,20),random.randint(2,20); op=random.choice(["+","-","×"]); view.data["question"]=f"{x} {op} {y}"; view.data["answer"]=str(x+y if op=="+" else x-y if op=="-" else x*y)
        elif game=="Riddle Battle": view.data["prompt"],view.data["answer"]=random.choice(RIDDLES)
        elif game=="Flag Guessing": view.data["flag"],view.data["answer"]=random.choice(FLAGS)
        elif game in QUIZZES:
            q,opts,ans=random.choice(QUIZZES[game]); view.data.update(question=q,options=opts,answer=ans)
            view.clear_items()
            for n,opt in enumerate(opts):
                b=discord.ui.Button(label=opt,style=discord.ButtonStyle.primary,row=n//2)
                async def cb(inter,choice=n): await view.finish(inter,choice==view.data["answer"],f"{view.data['question']}\nCorrect answer: **{view.data['options'][view.data['answer']]}**")
                b.callback=cb; view.add_item(b)
        elif game=="Flag Guessing": pass
        elif game=="Word Chain": view.data.update(used=set(),count=0)
        elif game=="Sentence Builder": pass
        embed=view.embed()
        await i.response.edit_message(embed=embed,view=view)
class MoreGamesView(discord.ui.View):
    def __init__(self,owner): super().__init__(timeout=180); self.owner=owner; self.add_item(CategorySelect())
    async def interaction_check(self,i):
        if i.user.id!=self.owner.id: await i.response.send_message("Open `/moregames` to use your own menu.",ephemeral=True); return False
        return True

class ExtendedGames(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.guild_only()
    @app_commands.command(name="moregames",description="Open Liebe's expanded game library.")
    async def moregames(self,i:discord.Interaction):
        embed=discord.Embed(title="🎮 Liebe · More Games",description="Choose a category to explore 25 additional games. Some complex board and party games are lightweight solo editions in this release.",color=discord.Color.blurple())
        await i.response.send_message(embed=embed,view=MoreGamesView(i.user),ephemeral=True)
async def setup(bot): await bot.add_cog(ExtendedGames(bot))
