import os
import json
import time
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------- Конфигурация GigaChat ----------
AUTH_KEY = os.environ.get("GIGACHAT_AUTH_KEY")
CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET")
SCOPE = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
INSECURE_TLS = os.environ.get("GIGACHAT_INSECURE_TLS", "1") == "1"
BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

# Кеш токена
_token_cache = {"access_token": None, "expires_at": 0}

def get_access_token():
    """Получить или обновить access token GigaChat."""
    global _token_cache
    
    # Если токен ещё жив, возвращаем его
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    print("🔄 Запрашиваю новый токен GigaChat...")
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Authorization": f"Basic {AUTH_KEY}",
        "RqUID": CLIENT_ID,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {"scope": SCOPE}
    
    try:
        resp = requests.post(
            url, 
            headers=headers, 
            data=payload, 
            verify=False,  # INSECURE_TLS
            timeout=15
        )
        print(f"📡 OAuth ответ: статус {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"❌ Тело ответа: {resp.text}")
            raise Exception(f"OAuth вернул {resp.status_code}: {resp.text[:200]}")
        
        data = resp.json()
        print(f"✅ Токен получен, expires_in = {data.get('expires_in', 'НЕТ ПОЛЯ')}")
        
        _token_cache["access_token"] = data["access_token"]
        # Используем expires_in если есть, иначе дефолт 30 минут
        expires_in = data.get("expires_in", 1800)
        _token_cache["expires_at"] = time.time() + expires_in - 60
        
        return _token_cache["access_token"]
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка сети при получении токена: {e}")
        raise
    except KeyError as e:
        print(f"❌ В ответе нет поля access_token: {e}")
        print(f"📄 Тело ответа: {resp.text if 'resp' in locals() else 'нет ответа'}")
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
    
    print(f"📤 Отправляю запрос в GigaChat...")
    resp = requests.post(
        url, 
        headers=headers, 
        json=payload, 
        verify=False, 
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ GigaChat API ошибка: {resp.status_code}")
        print(f"📄 Тело: {resp.text[:300]}")
        resp.raise_for_status()
    
    data = resp.json()
    print(f"✅ Ответ получен, длина: {len(data.get('choices', [{}])[0].get('message', {}).get('content', ''))} символов")
    return data

# ---------- Промпты ----------
SYSTEM_PROMPT = (
    "Ты — креативный и остроумный генератор отмазок «ОтмазОК». "
    "Твоя задача: придумывать уморительные, неожиданные, иногда абсурдные, "
    "но всегда стильные отговорки на любую жизненную ситуацию. "
    "Отвечай только самой отмазкой (1-3 предложения), без лишних слов и пояснений. "
    "Используй живой русский язык, юмор, отсылки к поп-культуре. "
    "Если категория — начальник, пусть звучит деловито-нелепо; "
    "если партнёр — романтично-смешно; "
    "если друзья — по-свойски; "
    "если школа/универ — креативно-ученически."
)

def build_prompt(category=None, user_prompt=None):
    """Собрать user-сообщение для GigaChat."""
    category_map = {
        "boss": "Придумай отмазку для начальника, почему я опоздал / не пришёл на работу.",
        "partner": "Придумай отмазку для любимого человека: забыл важную дату или не пришёл на свидание.",
        "friends": "Придумай отмазку для друзей, почему не пришёл на встречу / тусовку.",
        "school": "Придумай отмазку для учителя / преподавателя: не сделал домашку, опоздал.",
        "random": "Придумай совершенно случайную, максимально креативную и смешную отмазку на любой случай."
    }
    
    if category and category in category_map:
        user_content = category_map[category]
    elif user_prompt:
        user_content = f"Пользователь описал ситуацию: «{user_prompt}». Придумай подходящую отмазку."
    else:
        user_content = "Придумай универсальную отмазку."
    
    return user_content

# ---------- Маршруты ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "OtmazOK backend",
        "gigachat_configured": bool(AUTH_KEY)
    })

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    user_prompt = data.get("prompt")

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
        
        # Убираем возможные кавычки и лишние префиксы
        excuse = excuse.strip('"').strip("'").strip()
        
        return jsonify({
            "excuse": excuse,
            "category": category,
            "prompt": user_prompt
        })
    except Exception as e:
        print(f"❌ Ошибка генерации: {e}")
        return jsonify({"error": f"Ошибка генерации: {str(e)}"}), 500

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
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
