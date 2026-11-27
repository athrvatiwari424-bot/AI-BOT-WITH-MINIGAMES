# Liebe Bot update notes

## What's included

### Minigames
- Added `/games`, a unified public game center with a game selector.
- Tic-Tac-Toe and Connect 4 now support both AI matches and friend challenges with accept/decline.
- Added Rock Paper Scissors, High-Low (no currency or bets), Hangman, Word Scramble, Trivia, and Emoji Decode.
- Added `/profile`, `/achievements`, and `/serverstats`.
- Added persistent per-server player stats and achievements in `bot_data.db`.
- No XP, levels, or economy system was added.
- Kept `/tictactoe`, `/connect4`, and `/highlow` available.

### Security and server controls
- Revalidated target hierarchy and permissions when punishment modals are submitted.
- Limited purge modal input to 1–100 messages and rechecked permissions at submission.
- Restricted reaction-role setup from assigning privileged roles to members.
- Added runtime Administrator checks to AI-chat configuration commands.
- Emergency `/button red` now saves each channel's original @everyone permission values; `/button green` restores those saved values instead of blindly clearing existing overwrites.
- Kept `/nuke` confirmation restricted to the person who initiated it and rechecks permissions at confirmation.

### Privacy and legal text
- Updated the privacy policy to disclose game records, achievements, and AI memory summaries.
- Updated the Terms of Service date/version.

## Files changed
- `minigames.py`
- `moderation.py`
- `community_features.py`
- `ai_chat.py`
- `privacy.md`
- `liebe-bot-legal`

All other uploaded project files are included unchanged.

## Deployment
1. Download and extract the ZIP.
2. Replace the matching files in your GitHub repository with the extracted files.
3. Commit and push the changes.
4. Let your host redeploy. No new Python package is required.
5. After the bot starts, Discord may take a little time to refresh globally synced slash commands.

The new minigame tables are created automatically in `bot_data.db`; existing database records are not intentionally cleared.

## Verification notes
- All uploaded Python files passed Python syntax compilation.
- The new minigame SQLite schema and upsert statements passed a local SQLite test.
- A live Discord interaction test could not be run in this environment because `discord.py` and the other runtime packages are not installed here. Test the new UI commands in a private test server before enabling them in a large server.
