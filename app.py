#!/usr/bin/env python3
import csv
import io
import os
import re
from typing import Dict, Set, List

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Required env vars:
# SLACK_BOT_TOKEN = xoxb-...
# SLACK_APP_TOKEN = xapp-... (Socket Mode)
BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

EXCLUDED_USER_IDS = {
    "U040FETSCDN",
    "U09NBRAU7MG",
    "U07M27PDWN7",
    "U07HP5EREGM",
    "U03V0E6RFGA",
    "U05NNHVHQUU",
    "U09BRJQRXNJ",
}

app = App(token=BOT_TOKEN)
client = WebClient(token=BOT_TOKEN)

# ---------- Utilities ----------

MSG_URL_RE = re.compile(
    r"https?://[^/]+/archives/(?P<channel>[A-Z0-9]+)/p(?P<pts>\d{16,})"
)

def ts_from_permalink_pts(pts: str) -> str:
    # Slack permalinks put seconds+micros with no dot
    return f"{pts[:-6]}.{pts[-6:]}"

def paged(func, **kwargs):
    cursor = None
    while True:
        resp = func(cursor=cursor, **kwargs)
        yield resp
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

def keep_user(u: dict) -> bool:
    if not u:
        return False
    if u.get("is_bot") or u.get("id") == "USLACKBOT":
        return False
    if u.get("deleted"):
        return False
    return True

def user_dir_map() -> Dict[str, dict]:
    users = {}
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        for u in resp.get("members", []):
            users[u["id"]] = u
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return users

def format_name(u: dict) -> str:
    profile = (u or {}).get("profile", {}) or {}
    display = profile.get("display_name_normalized") or profile.get("display_name")
    real = profile.get("real_name_normalized") or profile.get("real_name")
    if display and display != real:
        return f"{display} ({real})"
    return display or real or (u or {}).get("name") or (u or {}).get("id", "unknown")

def channel_members(channel: str, users: Dict[str, dict]) -> Set[str]:
    ids = set()
    for resp in paged(client.conversations_members, channel=channel, limit=1000):
        for uid in resp.get("members", []):
            if keep_user(users.get(uid)):
                ids.add(uid)
    return ids

def fetch_message(channel: str, ts: str) -> dict:
    resp = client.conversations_history(channel=channel, latest=ts, inclusive=True, limit=1)
    msgs = resp.get("messages", [])
    if not msgs or msgs[0].get("ts") != ts:
        raise RuntimeError("Message not found at that timestamp.")
    return msgs[0]

def reactors(channel: str, ts: str) -> Set[str]:
    try:
        r = client.reactions_get(channel=channel, timestamp=ts)
        out = set()
        for rxn in (r.get("message", {}) or {}).get("reactions", []) or []:
            out.update(rxn.get("users", []) or [])
        return out
    except SlackApiError:
        # fallback read from message body
        msg = fetch_message(channel, ts)
        out = set()
        for rxn in msg.get("reactions", []) or []:
            out.update(rxn.get("users", []) or [])
        return out

def repliers(channel: str, ts: str) -> Set[str]:
    s = set()
    for resp in paged(client.conversations_replies, channel=channel, ts=ts, limit=200):
        for m in resp.get("messages", []):
            if m.get("user") and not m.get("subtype"):
                s.add(m["user"])
    # remove parent author
    try:
        parent = fetch_message(channel, ts).get("user")
        if parent in s:
            s.discard(parent)
    except Exception:
        pass
    return s

def make_csv(non_engagers: List[str], users: Dict[str, dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "name"])
    for uid in non_engagers:
        w.writerow([uid, format_name(users.get(uid))])
    return buf.getvalue().encode("utf-8")

def summarize(names: List[str], limit=20) -> str:
    shown = names[:limit]
    extra = len(names) - len(shown)
    body = "\n".join([f"• {n}" for n in shown])
    if extra > 0:
        body += f"\n…and {extra} more"
    return body

def compute_nonengagers(channel: str, ts: str):
    users = user_dir_map()
    pop = channel_members(channel, users)
    msg = fetch_message(channel, ts)
    author = msg.get("user")

    engaged = set(reactors(channel, ts)) | set(repliers(channel, ts))
    if author:
        engaged.add(author)

    engaged = {uid for uid in engaged if uid in pop}
    pop = {uid for uid in pop if uid not in EXCLUDED_USER_IDS}
    non = sorted(pop - engaged)
    names = [format_name(users.get(uid)) for uid in non]
    return {
        "population_ids": pop,
        "engaged_ids": engaged,
        "non_ids": non,
        "non_names": names,
    }

# ---------- Message Shortcut: "Find non-engagers" ----------
# In Slack App config, create a Message Shortcut with callback_id = find_non_engagers
@app.shortcut("find_non_engagers")
def on_shortcut(ack, body, logger):
    ack()  # acknowledge immediately (required)
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    try:
        result = compute_nonengagers(channel, ts)
        names = result["non_names"]
        pop = len(result["population_ids"])
        engaged = len(result["engaged_ids"])
        non_ct = len(result["non_ids"])

        # DM the requester a summary
        dm = client.conversations_open(users=[user_id])["channel"]["id"]
        client.chat_postMessage(
            channel=dm,
            text=(
                f"*Non-engagers for <https://app.slack.com/client/{team_id}/{channel}/thread/{channel}-{ts.replace('.', '')}|this message>*\n"
                f"*Members considered:* {pop}  ·  *Engaged:* {engaged}  ·  *Non-engagers:* {non_ct}\n\n"
                f"{summarize(names)}" if names else "🎉 Everyone engaged (reacted or replied)!"
            )
        )

        # Upload full CSV privately via DM
        if names:
            csv_bytes = make_csv(result["non_ids"], user_dir_map())
            client.files_upload_v2(
                channel=dm,  # DM channel we opened above
                filename="non_engagers.csv",
                title="Non-engagers",
                file=csv_bytes,
            )


    except Exception as e:
        logger.exception(e)
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text=f"Sorry, I couldn’t compute that: `{e}`"
        )

# ---------- Slash Command: /nonengagers <permalink> ----------
# Add a Slash Command in your Slack app settings with command `/nonengagers`
@app.command("/nonengagers")
def handle_cmd(ack, body, respond, logger):
    ack()
    text = (body.get("text") or "").strip()
    m = MSG_URL_RE.search(text)
    if not m:
        respond(
            "Usage: `/nonengagers <message link>`\n"
            "Tip: Long-press a message → *Copy link* and paste here."
        )
        return

    channel = m.group("channel")
    ts = ts_from_permalink_pts(m.group("pts"))

    try:
        result = compute_nonengagers(channel, ts)
        pop = len(result["population_ids"])
        engaged = len(result["engaged_ids"])
        non_ct = len(result["non_ids"])
        names = result["non_names"]

        summary = f"*Members considered:* {pop}  ·  *Engaged:* {engaged}  ·  *Non-engagers:* {non_ct}"

        dm = client.conversations_open(users=[body["user_id"]])["channel"]["id"]
        
        if names:
            preview = summarize(names)
            # Nudge in-channel ephemerally, but send details privately
            respond("I’ve DMed you the results (CSV + summary).")
            client.chat_postMessage(
                channel=dm,
                text=f"{summary}\n\n{preview}"
            )
            csv_bytes = make_csv(result["non_ids"], user_dir_map())
            client.files_upload_v2(
                channel=dm,
                filename="non_engagers.csv",
                title="Non-engagers",
                file=csv_bytes,
            )
        else:
            respond(f"{summary}\n\n🎉 Everyone engaged (reacted or replied)!")

    except Exception as e:
        logger.exception(e)
        respond(f"Sorry, I couldn’t compute that: `{e}`")

# ---------- Entrypoint ----------
if __name__ == "__main__":
    # Socket Mode = no public URL needed
    SocketModeHandler(app, APP_TOKEN).start()
