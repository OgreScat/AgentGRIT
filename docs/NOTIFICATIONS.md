# Notifications

AgentGRIT escalates to a human when the bylaws flag a high-stakes action. How
that reaches you is your choice — the engine ships with **no** hardcoded,
platform-specific transport. Configure a channel with environment variables.

Notifications are **opt-in**: with no configuration, nothing is sent (the
default channel is `none`). Every channel also writes to
`logs/notifications.jsonl` so there is always a durable record.

## Choose a channel

Set `NOTIFY_CHANNEL` to one of:

| Channel | Env vars | Use it for |
|---|---|---|
| `none` | — | default; disabled |
| `log` | — | record to `logs/notifications.jsonl` only |
| `telegram` | `NOTIFY_TELEGRAM_BOT_TOKEN`, `NOTIFY_TELEGRAM_CHAT_ID` | a Telegram bot DM/group |
| `webhook` | `NOTIFY_WEBHOOK_URL` | Slack / Discord / an SMS gateway / anything that accepts `POST {"text": ...}` |
| `command` | `NOTIFY_COMMAND` | run your own script; the message is passed as the first argument |

## Telegram (recommended, cross-platform)

1. Message `@BotFather`, create a bot, copy its token.
2. Message your new bot once, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id.
3. Configure:

```bash
export NOTIFY_CHANNEL=telegram
export NOTIFY_TELEGRAM_BOT_TOKEN=123456:ABC...
export NOTIFY_TELEGRAM_CHAT_ID=987654321
```

## Webhook (Slack / Discord / SMS gateway)

```bash
export NOTIFY_CHANNEL=webhook
export NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/...
```

The body posted is `{"text": "<message>"}`. Point it at a Slack/Discord
incoming webhook, or at any SMS/email gateway that accepts JSON.

## Command (bring your own transport)

```bash
export NOTIFY_CHANNEL=command
export NOTIFY_COMMAND=/path/to/send.sh   # receives the message as $1
```

Use this to wire a platform-specific sender you control — e.g. macOS iMessage
via `osascript`, `termux-sms-send` on Android, or a corporate paging tool. Keep
that script outside the repo.

## Security note

`telegram` and `webhook` make outbound network requests. If you run AgentGRIT in
a restricted environment, prefer `command` or `log`, and treat any token or
webhook URL as a secret (never commit it — use your `.env`).
