import os
import json
import requests
import random
import emoji
from flask import Flask, request

app = Flask(__name__)

# --- الإعدادات الآمنة (يتم جلبها من إعدادات Render) ---
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'mostapha1') # قيمة افتراضية إذا لم تجدها
ADMIN_FB_ID = os.environ.get('ADMIN_FB_ID')
DATA_FILE = '/opt/render/project/src/djezzy_fb_data.json' # مسار الحفظ في Render (اختياري)

# --- إدارة البيانات ---
def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

def save_db(db):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(db, f, indent=4)
    except: pass

# --- وظائف Djezzy API ---
def send_otp(msisdn):
    url = 'https://apim.djezzy.dz/oauth2/registration'
    payload = f'msisdn={msisdn}&client_id=6E6CwTkp8H1CyQxraPmcEJPQ7xka&scope=smsotp'
    headers = {'User-Agent': 'Djezzy/2.6.7', 'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        res = requests.post(url, data=payload, headers=headers, timeout=10)
        return res.status_code == 200
    except: return False

def verify_otp(msisdn, otp):
    url = 'https://apim.djezzy.dz/oauth2/token'
    payload = f'otp={otp}&mobileNumber={msisdn}&scope=openid&client_id=6E6CwTkp8H1CyQxraPmcEJPQ7xka&client_secret=MVpXHW_ImuMsxKIwrJpoVVMHjRsa&grant_type=mobile'
    headers = {'User-Agent': 'Djezzy/2.6.7', 'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        res = requests.post(url, data=payload, headers=headers, timeout=10)
        return res.json() if res.status_code == 200 else None
    except: return None

def apply_walkwin_2gb(msisdn, token):
    url = f'https://apim.djezzy.dz/djezzy-api/api/v1/subscribers/{msisdn}/subscription-product'
    payload = {
        'data': {
            'id': 'GIFTWALKWIN', 'type': 'products',
            'meta': {'services': {'steps': 10000, 'code': 'GIFTWALKWIN2GO', 'id': 'WALKWIN'}}
        }
    }
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'User-Agent': 'Djezzy/2.6.7'}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15).json()
        if 'message' in res and "successfully" in res['message']:
            return True, "✅ مبروك! تم تفعيل هدية المشي 2GB بنجاح. استمتع بها! 🎉"
        return False, "⚠️ عذراً، لم نتمكن من التفعيل. تأكد من باقة فليكسي أو أنك استهلكت الهدية أسبوعياً."
    except: return False, "❌ حدث خطأ تقني، حاول لاحقاً."

# --- وظائف الإرسال ---
def send_text(sid, text):
    if not PAGE_ACCESS_TOKEN: return
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    requests.post(url, json={"recipient": {"id": sid}, "message": {"text": text}})

def send_main_menu(sid):
    if not PAGE_ACCESS_TOKEN: return
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": sid},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "🎉 رائع! تم تسجيل دخولك بنجاح.\n\n⚠️ تذكير: يجب توفر باقة فليكسي محددة لتفعيل الهدية.",
                    "buttons": [{"type": "postback", "title": "🏃 تفعيل هدية 2GB", "payload": "ACTIVATE_2GB"}]
                }
            }
        }
    }
    requests.post(url, json=payload)

# --- معالجة الـ Webhook ---
@app.route("/", methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "OK", 200

@app.route("/", methods=['POST'])
def webhook():
    data = request.get_json()
    db = load_db()
    
    if data.get("object") == "page":
        for entry in data["entry"]:
            for event in entry.get("messaging", []):
                sid = str(event["sender"]["id"])
                user = db.get(sid, {"state": "START"})

                if "postback" in event:
                    payload = event["postback"]["payload"]
                    if payload == "ACTIVATE_2GB" and "token" in user:
                        send_text(sid, "⏳ جاري المعالجة...")
                        success, msg = apply_walkwin_2gb(user["msisdn"], user["token"])
                        send_text(sid, msg)
                        
                        if success and ADMIN_FB_ID:
                            notify_msg = f"🔔 مبروك مدير! مستخدم جديد فعل الهدية بنجاح:\n📞 الرقم: {user['msisdn']}\n🆔 أيدي المستخدم: {sid}"
                            send_text(ADMIN_FB_ID, notify_msg)

                elif "message" in event and "text" in event["message"]:
                    text = event["message"]["text"].strip()
                    if all(char in emoji.EMOJI_DATA for char in text):
                        send_text(sid, text)
                        continue

                    if text.startswith("07") and len(text) == 10:
                        msisdn = "213" + text[1:]
                        if send_otp(msisdn):
                            db[sid] = {"msisdn": msisdn, "state": "AWAITING_OTP"}
                            send_text(sid, "🔢 وصلك رمز OTP، أرسله هنا:")
                        else: send_text(sid, "❌ فشل إرسال الرمز.")
                    
                    elif user.get("state") == "AWAITING_OTP" and text.isdigit():
                        res = verify_otp(user["msisdn"], text)
                        if res:
                            db[sid].update({"token": res['access_token'], "state": "VERIFIED"})
                            send_main_menu(sid)
                        else: send_text(sid, "❌ الرمز غير صحيح.")

                    else:
                        info_msg = (
                            "استغفر الله، والله أكبر، والحمد لله ❤️\n\n"
                            "📲 ارسل رقمك لمحاولة تفعيل هدية 2GB 🤩\n\n"
                            "⚠️ يجب أن تكون مشتركاً في باقة فليكسي من جيزي.\n\n"
                            "لا تنسى دعم صفحة kito لتوفر المزيد من الميزات الرائعة 🥳"
                        )
                        send_text(sid, info_msg)

    save_db(db)
    return "ok", 200

if __name__ == "__main__":
    # هذا السطر مهم جداً ليعمل البوت على Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
