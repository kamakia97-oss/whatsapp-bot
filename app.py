import os
import re
import time
import threading
import requests
from flask import Flask, request, jsonify
from anthropic import Anthropic

app = Flask(__name__)
claude       = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
INSTANCE_ID  = os.environ.get("ULTRAMSG_INSTANCE_ID", "instance166781")
ULTRA_TOKEN  = os.environ.get("ULTRAMSG_TOKEN")
OWNER_NUMBER = os.environ.get("OWNER_NUMBER")
RENDER_URL   = os.environ.get("RENDER_URL", "https://whatsapp-bot-1-ld65.onrender.com")

conversations = {}
active_chats  = set()
processed_ids = set()

SYSTEM_PROMPT = (
    "You are acting AS the owner of this WhatsApp number. "
    "Reply to their friends naturally, as if you ARE that person. "
    "NEVER reveal you are an AI or bot ever. "
    "Reply in WHATEVER language the friend uses. "
    "Match their TONE and ENERGY naturally. "
    "Keep replies SHORT like real WhatsApp messages. "
    "Use emojis naturally but not too much. "
    "Sound like a real human friend ALWAYS."
)


def send_message(phone, message):
    phone = re.sub(r"[^\d]", "", phone)
    try:
        resp = requests.post(
            "https://api.ultramsg.com/" + INSTANCE_ID + "/messages/chat",
            data={
                "token": ULTRA_TOKEN,
                "to": phone,
                "body": message,
                "priority": 1
            },
            timeout=10
        )
        print("Sent to " + phone + ": " + str(resp.status_code))
    except Exception as e:
        print("Send error: " + str(e))


def send_to_owner(message):
    if OWNER_NUMBER:
        send_message(OWNER_NUMBER, message)


def keep_alive():
    print("Keep-alive started...")
    while True:
        time.sleep(300)
        try:
            requests.get(RENDER_URL + "/ping", timeout=10)
            print("Keep-alive ping sent")
        except Exception as e:
            print("Keep-alive error: " + str(e))


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


def handle_owner(message):
    msg = message.strip()

    if msg.lower() == "/help":
        send_to_owner(
            "Bot Commands:\n\n"
            "Send a number to start chatting\n"
            "Example: 0712345678\n\n"
            "/stop 0712345678 - Stop chat\n"
            "/list - See active chats\n"
            "/clear 0712345678 - Clear history\n"
            "/status - Bot status\n"
            "/help - This menu"
        )
        return

    if msg.lower() == "/status":
        send_to_owner(
            "Bot Status:\n\n"
            "Active chats: " + str(len(active_chats)) + "\n"
            "Conversations: " + str(len(conversations)) + "\n"
            "Messages processed: " + str(len(processed_ids)) + "\n"
            "Bot is running!"
        )
        return

    if msg.lower() == "/list":
        if active_chats:
            chats = "\n".join(["+" + p for p in active_chats])
            send_to_owner("Active chats:\n" + chats)
        else:
            send_to_owner("No active chats right now.")
        return

    if msg.lower().startswith("/stop"):
        phone = extract_phone(msg.replace("/stop", ""))
        if phone:
            active_chats.discard(phone)
            conversations.pop(phone, None)
            send_to_owner("Stopped chat with +" + phone)
        return

    if msg.lower().startswith("/clear"):
        phone = extract_phone(msg.replace("/clear", ""))
        if phone and phone in conversations:
            conversations.pop(phone)
            send_to_owner("Cleared history for +" + phone)
        return

    phone = extract_phone(msg)
    if phone:
        send_to_owner("Starting chat with +" + phone + "...")
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                system="Generate a short casual friendly WhatsApp opening message to reconnect with someone. Just the message only.",
                messages=[{"role": "user", "content": "Start"}]
            )
            opener = response.content[0].text
            if phone not in conversations:
                conversations[phone] = []
            conversations[phone].append({"role": "assistant", "content": opener})
            active_chats.add(phone)
            send_message(phone, opener)
            send_to_owner("Started chat with +" + phone + "\nMessage: " + opener)
        except Exception as e:
            send_to_owner("Error starting chat: " + str(e))


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict()
    if not data:
        return jsonify({"status": "ok"})

    print("Incoming: " + str(data))

    try:
        sender   = data.get("from", data.get("sender", ""))
        message  = data.get("body", data.get("message", ""))
        msg_id   = data.get("id", "")
        msg_type = data.get("type", "chat")
        from_me  = data.get("fromMe", False)

        if not message or not sender:
            return jsonify({"status": "ok"})

        if msg_type not in ["chat", ""]:
            return jsonify({"status": "ok"})

        if from_me:
            return jsonify({"status": "ok"})

        if msg_id and msg_id in processed_ids:
            return jsonify({"status": "ok"})
        if msg_id:
            processed_ids.add(msg_id)

        print("Message from " + sender + ": " + message)

        if is_owner(sender):
            handle_owner(message)
        else:
            reply = get_ai_reply(sender, message)
            send_message(sender, reply)
            print("Replied to " + sender)

    except Exception as e:
        print("Webhook error: " + str(e))

    return jsonify({"status": "ok"})


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "Bot is running!",
        "active_chats": len(active_chats),
        "conversations": len(conversations)
    })


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive!"})


threading.Thread(target=keep_alive, daemon=True).start()
print("WhatsApp Bot started!")

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
