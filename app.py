import os
import re
import requests
from flask import Flask, request, jsonify
from anthropic import Anthropic

app = Flask(__name__)
claude = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
WHAPI_TOKEN  = os.environ.get("WHAPI_TOKEN")
WHAPI_URL    = "https://gate.whapi.cloud/messages/text"
OWNER_NUMBER = os.environ.get("OWNER_NUMBER")
conversations = {}
active_chats  = set()

SYSTEM_PROMPT = """You are acting AS the owner of this WhatsApp number.
Reply to their friends naturally, as if you ARE that person.
NEVER reveal you are an AI or bot.
Reply in WHATEVER language the friend uses.
Match their TONE and ENERGY.
Keep replies SHORT like real WhatsApp messages.
Sound like a real human friend ALWAYS."""

def send_message(phone, message):
    headers = {"Authorization": f"Bearer {WHAPI_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": f"{phone}@s.whatsapp.net" if "@" not in phone else phone, "body": message}
    try:
        requests.post(WHAPI_URL, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def send_to_owner(message):
    if OWNER_NUMBER:
        send_message(OWNER_NUMBER, message)

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

def is_owner(sender):
    if not OWNER_NUMBER:
        return False
    s = re.sub(r"[^\d]", "", sender)
    o = re.sub(r"[^\d]", "", OWNER_NUMBER)
    return s.endswith(o) or o.endswith(s)

def handle_owner(message):
    msg = message.strip()
    if msg.lower() == "/help":
        send_to_owner("🤖 Bot Commands:\n\nSend a number → Start chatting\n/stop 0712345678 → Stop chat\n/list → Active chats\n/clear 0712345678 → Clear history\n/help → This menu")
        return
    if msg.lower() == "/list":
        send_to_owner(f"📋 Active chats:\n" + "\n".join([f"+{p}" for p in active_chats]) if active_chats else "No active chats.")
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

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ok"})
    try:
        for msg in data.get("messages", []):
            if msg.get("from_me"):
                continue
            sender  = msg.get("chat_id", "")
            message = msg.get("text", {}).get("body", "")
            if not message or not sender:
                continue
            if is_owner(sender):
                handle_owner(message)
                continue
            try:
                reply = get_ai_reply(sender, message)
                phone = sender.replace("@s.whatsapp.net", "").replace("@c.us", "")
                send_message(phone, reply)
            except Exception as e:
                print(f"Reply error: {e}")
    except Exception as e:
        print(f"Webhook error: {e}")
    return jsonify({"status": "ok"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Bot is running!", "active_chats": len(active_chats)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
