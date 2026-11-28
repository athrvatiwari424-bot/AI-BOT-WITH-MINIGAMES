# Liebe Bot - Beta v1.031

This update is based on the latest expanded-games v1.03 project.

## Echo
- `/echo` now offers two output formats: normal bot-authored message or embed.
- The embed no longer says who invoked the command.
- Natural text `echo <message>` sends a normal message.
- Echo command usage is recorded in the mod log and, when configured, the separate bot log.

## AI chat
- Mentioning Liebe triggers AI chat in any guild text channel; `/setaichat` is no longer required for mention-triggered replies.
- A bare mention now receives a short prompt asking what the member needs.
- The configured AI channel still works as before.
- Existing three Gemini environment keys and model configuration are unchanged.

## Logging
- `/message-log <channel>` configures deleted and edited message logs.
- `/mod-log <channel>` configures command usage and command error logs.
- `/bot-log <channel>` configures bot-specific logs, including echo usage.
- `/bot-update-log [enabled]` must be run inside the configured mod-log channel. It enables/disables automatic version announcements there.
- Game commands are excluded from mod-log command activity.
- Logs use embeds with Discord timestamps and date/time footers.
- Cached message text, attachments, photo/file URLs, embed links and available forwarded-message snapshots are included.

## Tickets
- New `tickets.py` extension.
- `/ticket-setup <channel>` creates a panel and default Support, Sponsorship, General Help and Other categories.
- Buttons create private ticket channels under the matching category.
- `/ticket-edit <title> <description>` edits the panel embed.
- `/ticket-category <type> <category>` maps a ticket type to an existing category.
- Ticket owners and staff with Manage Channels/Administrator access can close tickets. Closing restricts the owner from sending and renames the channel; it does not delete it.
- Ticket panels and open tickets are persistent across restarts.

## Server templates
- New `server_templates.py` extension.
- `/template-copy <source>` accepts a source server ID (Liebe must be in that server) or an official Discord template URL. `discordtemplates.me` pages are supported when they expose an official Discord template link.
- Import requires administrator permission and confirmation.
- The importer is create-only: it does not delete or overwrite existing target roles/channels.
- It imports role names/colors/selected permissions and category/text/announcement/voice channel structure with role-based channel overwrites where available.
- Administrator permission is stripped from imported roles.
- Arbitrary website formats, message history, integrations, webhooks, emoji, member assignments, forum/stage channels and all other server data are not universally importable.

## Important logging limitations
- Discord does not provide the contents of a deleted message after the fact. Liebe caches messages while online; deleted messages sent before startup or not cached can only be logged as deletion events without their content.
- Attachment URLs and forwarded snapshots are logged only when Discord includes them in cached/raw message data. Some forwarded-message details are not exposed by Discord.
- Update announcements are opt-in per server and are posted once when `BOT_VERSION` changes in `logging_system.py`.
- There is no separate global "community enabled" switch in this project; configuring the log commands is the opt-in.

## Deployment
- No new third-party dependencies were added.
- `bot.py` now loads `logging_system`, `tickets`, and `server_templates`.
- Keep the existing `DISCORD_TOKEN` and Gemini API environment variables private; no key changes are required.
