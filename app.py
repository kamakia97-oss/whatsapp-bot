import os
import re
import time
import threading
import requests
from flask import Flask, request, jsonify
from anthropic import Anthropic

app = Flask(__name__)
claude = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
WHAPI_TOKEN  = os.environ.get("WHAPI_TOKEN")
WHAPI_URL    = "https://gate.whapi.cloud/messages/text"
WHAPI_BASE   = "https://gate.whapi.cloud"
OWNER_NUMBER = os.environ.get("OWNER_NUMBER")
RENDER_URL   = os.environ.get("RENDER_URL", "https://whatsapp-bot-0xk2.onrender.com")

conversations = {}
active_chats  = set()
processed_ids = set()  # Track processed message IDs to avoid duplicates

SYSTEM_PROMPT = """You are acting AS the owner of this WhatsApp number.
Reply to their friends naturally, as if you ARE that person.
NEVER reveal you are an AI or bot.
Reply in WHATEVER language the friend uses.
Match their TONE and ENERGY.
Keep replies SHORT like real WhatsApp messages.
Sound like a real human friend ALWAYS."""

# ── WHAPI HEADERS ─────────────────────────────────────────────
def get_headers():
    return {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }

# ── SEND MESSAGE ──────────────────────────────────────────────
def send_message(phone, message):
    phone = phone.replace("@s.whatsapp.net", "").replace("@c.us", "")
    payload = {
        "to": f"{phone}@s.whatsapp.net",
        "body": message
    }
    try:
        resp = requests.post(
            f"{WHAPI_BASE}/messages/text",
            json=payload,
            headers=get_headers(),
            timeout=10
        )
        print(f"📤 Sent to {phone}: {resp.status_code}")
    except Exception as e:
        print(f"❌ Send error: {e}")

def send_to_owner(message):
    if OWNER_NUMBER:
        send_message(OWNER_NUMBER, message)

# ── POLL WHAPI FOR NEW MESSAGES EVERY SECOND ──────────────────
def poll_messages():
    print("🔄 Message polling started — checking every second...")
    while True:
        try:
            resp = requests.get(
                f"{WHAPI_BASE}/messages/list/incoming",
                headers=get_headers(),
                params={"count": 20},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                messages = data.get("messages", [])
                for msg in messages:
                    msg_id = msg.get("id", "")
                    # Skip already processed messages
                    if msg_id in processed_ids:
                        continue
                    processed_ids.add(msg_id)
                    # Skip our own messages
                    if msg.get("from_me"):
                        continue
                    sender  = msg.get("chat_id", "")
                    message = msg.get("text", {}).get("body", "")
                    if not message or not sender:
                        continue
                    print(f"📩 New message from {sender}: {message}")
                    process_message(sender, message)
            else:
                print(f"⚠️ Poll error: {resp.status_code}")
        except Exception as e:
            print(f"❌ Poll error: {e}")
        time.sleep(1)  # Check every second

# ── KEEP ALIVE — Ping every 5 minutes ─────────────────────────
def keep_alive():
    print("💓 Keep-alive started...")
    while True:
        time.sleep(300)
        try:
            requests.get(f"{RENDER_URL}/ping", timeout=10)
            print("✅ Keep-alive ping sent")
        except Exception as e:
            print(f"⚠️ Keep-alive error: {e}")

# ── PROCESS MESSAGE ───────────────────────────────────────────
def process_message(sender, message):
    if is_owner(sender):
        handle_owner(message)
    else:
        try:
            reply = get_ai_reply(sender, message)
            send_message(sender, reply)
        except Exception as e:
            print(f"❌ Reply error: {e}")

# ── AI REPLY ──────────────────────────────────────────────────
def get_ai_reply(sender, message):
    if sender not in conversations:
        conversations[sender] = []
    conversations[sender].append({"role": "user", "content": message})
    if len(conversations[sender]) > 20:
        conversations[sender] = conversations[sender][-20:]
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=conversations[sender]
    )
    reply = response.content[0].text
    conversations[sender].append({"role": "assistant", "content": reply})
    return reply

# ── IS OWNER ──────────────────────────────────────────────────
def is_owner(sender):
    if not OWNER_NUMBER:
        return False
    s = re.sub(r"[^\d]", "", sender)
    o = re.sub(r"[^\d]", "", OWNER_NUMBER)
    return s.endswith(o) or o.endswith(s)

# ── EXTRACT PHONE ─────────────────────────────────────────────
def extract_phone(text):
    cleaned = re.sub(r"[\s\-\(\)\+]", "", text)
    match = re.search(r"\d{10,15}", cleaned)
    if match:
        number = match.group()
        if len(number) == 10 and number.startswith("7"):
            number = "254" + number
        if len(number) == 10 and number.startswith("0"):
            number = "254" + number[1:]
        return number
    return None

# ── OWNER COMMANDS ────────────────────────────────────────────
def handle_owner(message):
    msg = message.strip()
    if msg.lower() == "/help":
        send_to_owner(
            "🤖 Bot Commands:\n\n"
            "Send a number → Start chatting\n"
            "Example: 0712345678\n\n"
            "/stop 0712345678 → Stop chat\n"
            "/list → Active chats\n"
            "/clear 0712345678 → Clear history\n"
            "/status → Bot status\n"
            "/help → This menu"
        )
        return
    if msg.lower() == "/status":
        send_to_owner(
            f"✅ Bot is running!\n"
            f"💬 Active chats: {len(active_chats)}\n"
            f"📝 Conversations: {len(conversations)}\n"
            f"📨 Processed messages: {len(processed_ids)}"
        )
        return
    if msg.lower() == "/list":
        if active_chats:
            chats = "\n".join([f"+{p}" for p in active_chats])
            send_to_owner(f"📋 Active chats:\n{chats}")
        else:
            send_to_owner("No active chats.")
        return
    if msg.lower().startswith("/stop"):
        phone = extract_phone(msg.replace("/stop", ""))
        if phone:
            active_chats.discard(phone)
            send_to_owner(f"⛔ Stopped +{phone}")
        return
    if msg.lower().startswith("/clear"):
        phone = extract_phone(msg.replace("/clear", ""))
        if phone and phone in conversations:
            conversations.pop(phone)
            send_to_owner(f"🗑️ Cleared +{phone}")
        return
    phone = extract_phone(msg)
    if phone:
        send_to_owner(f"📲 Starting chat with +{phone}...")
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            system="Generate a short friendly WhatsApp opening message to reconnect with someone. Just the message only.",
            messages=[{"role": "user", "content": "Start"}]
        )
        opener = response.content[0].text
        if phone not in conversations:
            conversations[phone] = []
        conversations[phone].append({"role": "assistant", "content": opener})
        active_chats.add(phone)
        send_message(phone, opener)
        send_to_owner(f"✅ Started chat with +{phone}\nMessage: \"{opener}\"")

# ── ROUTES ────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    """Receives messages from Whapi webhook"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ok"})
    try:
        for msg in data.get("messages", []):
            msg_id = msg.get("id", "")
            if msg_id in processed_ids:
                continue
            processed_ids.add(msg_id)
            if msg.get("from_me"):
                continue
            sender  = msg.get("chat_id", "")
            message = msg.get("text", {}).get("body", "")
            print(f"📩 Webhook message from {sender}: {message}")
            if not message or not sender:
                continue
            process_message(sender, message)
    except Exception as e:
        print(f"❌ Webhook error: {e}")
    return jsonify({"status": "ok"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "✅ Bot is running!",
        "active_chats": len(active_chats),
        "conversations": len(conversations),
        "processed_messages": len(processed_ids)
    })

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive!"})

# ── START BACKGROUND THREADS ──────────────────────────────────
poll_thread = threading.Thread(target=poll_messages)
poll_thread.daemon = True
poll_thread.start()

alive_thread = threading.Thread(target=keep_alive)
alive_thread.daemon = True
alive_thread.start()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
