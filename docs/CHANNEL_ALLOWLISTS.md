# Channel Allowlists

Restrict which Slack channels, Discord channels, or Telegram chats (and optionally which users) can interact with the bot.

## Configuration

Add to your channel config via `beehive channels set`:

```json
{
  "slack_bot_token": "xoxb-...",
  "slack_signing_secret": "...",
  "allowed_channel_ids": ["C01234ABC", "C56789XYZ"],
  "allowed_user_ids": ["U0USER1", "U0USER2"]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `allowed_channel_ids` | list of strings | Channel IDs that can use the bot. Empty or absent = allow all channels. |
| `allowed_user_ids` | list of strings | User IDs that can use the bot. Empty or absent = allow all users. |

### Behavior

- **Both empty/absent**: No restriction; any authenticated request is processed (default).
- **Only `allowed_channel_ids` set**: Only requests from those channels are processed.
- **Only `allowed_user_ids` set**: Only requests from those users are processed.
- **Both set**: Request must match both (channel in list AND user in list).

### Platform-Specific IDs

**Slack**
- Channel ID: from `event.channel` (e.g. `C01234ABC`)
- User ID: from `event.user` (e.g. `U0USER1`)

**Discord**
- Channel ID: from `channel_id` in interaction (e.g. `123456789012345678`)
- User ID: from `member.user.id` or `user.id` (e.g. `987654321098765432`)

**Telegram**
- Channel/Chat ID: from `message.chat.id` (e.g. `-1001234567890`)
- User ID: from `message.from.id` (e.g. `123456789`)

## Example

```bash
# Allow only specific Slack channels
beehive channels set slack '{
  "slack_bot_token": "xoxb-...",
  "slack_signing_secret": "...",
  "allowed_channel_ids": ["C0TEAMOPS", "C0SUPPORT"]
}'

# Allow only specific Discord users
beehive channels set discord '{
  "discord_bot_token": "...",
  "discord_public_key": "...",
  "allowed_user_ids": ["123456789", "987654321"]
}'
```

## Denied Requests

- **Slack/Telegram**: Denied requests are silently ignored (no reply). This avoids leaking allowlist existence.
- **Discord**: User sees an ephemeral message: "You do not have access to this bot."
