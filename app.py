import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps

app = Flask(__name__)
CORS(app)  # разрешаем запросы с любого источника

# ---------- Конфигурация GigaChat ----------
AUTH_KEY = os.environ.get("GIGACHAT_AUTH_KEY")
CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET")
SCOPE = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
INSECURE_TLS = os.environ.get("GIGACHAT_INSECURE_TLS", "1") == "1"
BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

# Глобальный кеш токена (простой, без refresh)
_token_cache = {"access_token": None, "expires_at": 0}

def get_access_token():
    """Получить или обновить access token GigaChat."""
    global _token_cache
    import time
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Authorization": f"Basic {AUTH_KEY}",
        "RqUID": CLIENT_ID,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {"scope": SCOPE}
    # INSECURE_TLS=1 – отключаем проверку сертификата (только для тестов!)
    verify = not INSECURE_TLS
    try:
        resp = requests.post(url, headers=headers, data=payload, verify=verify)
        resp.raise_for_status()
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data["expires_in"] - 60
        return _token_cache["access_token"]
    except Exception as e:
        print(f"Ошибка получения токена: {e}")
        raise

def gigachat_request(messages, temperature=0.9, max_tokens=300):
    """Отправить запрос в GigaChat API."""
    token = get_access_token()
    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "GigaChat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.95
    }
    resp = requests.post(url, headers=headers, json=payload, verify=not INSECURE_TLS)
    resp.raise_for_status()
    return resp.json()

# ---------- Промпты ----------
SYSTEM_PROMPT = (
    "Ты — креативный и остроумный генератор отмазок «ОтмазОК». "
    "Твоя задача: придумывать уморительные, неожиданные, иногда абсурдные, "
    "но всегда стильные отговорки на любую жизненную ситуацию. "
    "Отвечай только самой отмазкой, без лишних слов и пояснений. "
    "Используй живой русский язык, юмор, отсылки к поп-культуре. "
    "Если категория — начальник, пусть звучит деловито-нелепо; "
    "если партнёр — романтично-смешно; "
    "если друзья — по-свойски; "
    "если школа/универ — креативно-ученически."
)

def build_prompt(category=None, user_prompt=None):
    """Собрать user‑сообщение для GigaChat."""
    if category:
        category_map = {
            "boss": "Придумай отмазку для начальника, почему я опоздал / не пришёл на работу.",
            "partner": "Придумай отмазку для любимого человека: забыл важную дату или не пришёл на свидание.",
            "friends": "Придумай отмазку для друзей, почему не пришёл на встречу / тусовку.",
            "school": "Придумай отмазку для учителя / преподавателя: не сделал домашку, опоздал.",
            "random": "Придумай совершенно случайную, максимально креативную отмазку на любой случай."
        }
        user_content = category_map.get(category, category_map["random"])
    elif user_prompt:
        user_content = f"Пользователь описал ситуацию: «{user_prompt}». Придумай подходящую отмазку."
    else:
        user_content = "Придумай универсальную отмазку."
    return user_content

# ---------- Маршруты ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "OtmazOK backend"})

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    category = data.get("category")       # boss, partner, friends, school, random
    user_prompt = data.get("prompt")      # свободный текст

    if not category and not user_prompt:
        return jsonify({"error": "Укажите category или prompt"}), 400

    user_content = build_prompt(category, user_prompt)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]

    try:
        result = gigachat_request(messages)
        excuse = result["choices"][0]["message"]["content"].strip()
        return jsonify({"excuse": excuse, "category": category, "prompt": user_prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/categories", methods=["GET"])
def list_categories():
    return jsonify({
        "categories": [
            {"id": "boss", "name": "Для начальника", "icon": "👔"},
            {"id": "partner", "name": "Для партнёра", "icon": "💔"},
            {"id": "friends", "name": "Перед друзьями", "icon": "🍻"},
            {"id": "school", "name": "Учителю/преподу", "icon": "📚"},
            {"id": "random", "name": "Случайная гениальность", "icon": "🎲"}
        ]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)