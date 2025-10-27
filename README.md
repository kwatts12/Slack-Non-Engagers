# Slack-Non-Engagers
Find people in a slack channel who didn't react or reply

# Slack Non-Engagers Bot (Socket Mode)

Long-press any Slack message (mobile or desktop) and run a message shortcut to list **who did _not_ react or reply**. Also available as a slash command:  
`/nonengagers <message_link>`

## 🚀 One-Click Deploy on Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?repo=https://github.com/kwatts12/Slack-Non-Engagers/tree/main)

During deploy, Railway will prompt you for:
- `SLACK_BOT_TOKEN` (xoxb-…)
- `SLACK_APP_TOKEN` (xapp-…)

> Socket Mode means **no public URL** is required.

## 🔧 Slack App Setup

1. Create a Slack App → **Install to Workspace**
2. **OAuth & Permissions → Bot Token Scopes** add:
   - `commands`
   - `chat:write`, `files:write`
   - `users:read`
   - `conversations:read`, `conversations:history`, `conversations.members`
   - `reactions:read`
   - (Private channels: `groups:read`, `groups:history`)
3. **App-Level Token:**  
   - Settings → **Socket Mode**: ON  
   - Create an App Token with scope `connections:write`
4. **Interactivity & Shortcuts:** ON  
   - Add **Message Shortcut**  
     - Name: **Find non-engagers**  
     - Callback ID: `find_non_engagers`
5. (Optional) **Slash Command:** `/nonengagers`  
   - With Socket Mode + Bolt, you don’t need a public Request URL.
6. **Reinstall App** to apply scopes.
7. Invite the bot to channels you’ll analyze.

## 🧠 How it works

- Gets all members of the channel
- Gets users who reacted to the message
- Gets users who replied in the thread
- Counts the author as engaged
- Reports everyone else as **non-engagers**
- Sends you a DM summary and uploads a CSV in the thread

## 🏃 Local dev (optional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
python app.py
