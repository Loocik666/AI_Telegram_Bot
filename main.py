import asyncio
import aiohttp
import sqlite3
import os
import re
from datetime import date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# --- НАСТРОЙКИ (МЕНЯТЬ ТУТ) ---
TOKEN = "ТВОЙ_ТОКЕН_БОТА"  # Замени на токен от @BotFather
MODEL_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "deepseek-r1:1.5b" 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS Users 
                      (user_id INTEGER PRIMARY KEY, 
                       requests_today INTEGER DEFAULT 0, 
                       last_date TEXT, 
                       is_sub BOOLEAN DEFAULT 0)''')
    conn.commit()
    conn.close()

async def get_user_status(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT requests_today, last_date, is_sub FROM Users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    today = str(date.today())
    if not row:
        cursor.execute("INSERT INTO Users (user_id, last_date) VALUES (?, ?)", (user_id, today))
        conn.commit()
        conn.close()
        return 0, today, 0
    conn.close()
    return row

# --- ЛОГИКА ИИ С SYSTEM PROMPT ---
async def ask_deepseek(user_text):
    system_instruction = (
        "Ты — полезный ИИ-ассистент. "
        "ОБЯЗАТЕЛЬНО отвечай только на русском языке. "
        "Будь кратким и точным."
    )
    full_prompt = f"{system_instruction}\n\nUser: {user_text}\nAssistant:"
    
    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": 0.4, "top_p": 0.9}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(MODEL_URL, json=payload) as resp:
                result = await resp.json()
                raw_response = result.get("response", "")
                # Очистка от мыслей <think>
                clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL).strip()
                return clean_response or "Не удалось получить ответ."
    except Exception as e:
        return f"Ошибка Ollama: {e}"

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Регистрируем пользователя при старте
    await get_user_status(message.from_user.id)
    
    await message.answer(
        f"Привет, {message.from_user.full_name}! 🤖\n\n"
        "Я — бот на базе DeepSeek-R1. Я работаю локально и уважаю твою приватность.\n\n"
        "📍 **Лимиты:** 10 бесплатных запросов в день.\n"
        "💰 **Безлимит:** Жми /buy, чтобы купить доступ за Звезды.\n\n"
        "Просто напиши мне любой вопрос!"
    )

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    await message.answer_invoice(
        title="Безлимитный доступ",
        description="Доступ к DeepSeek AI без ограничений на 30 дней",
        prices=[types.LabeledPrice(label="Звезды", amount=100)],
        currency="XTR",
        payload="sub_monthly",
        provider_token=""
    )

@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_pay(message: types.Message):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE Users SET is_sub = 1 WHERE user_id = ?", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("🎉 Подписка активирована! Теперь у вас безлимитный доступ.")

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---

@dp.message(F.text)
async def handle_message(message: types.Message):
    # Пропускаем, если это команда (они обработаны выше)
    if message.text.startswith('/'):
        return

    u_id = message.from_user.id
    req_today, last_date_str, is_sub = await get_user_status(u_id)
    today = str(date.today())

    # Сброс лимитов, если день сменился
    current_reqs = req_today if last_date_str == today else 0

    if is_sub or current_reqs < 10:
        await bot.send_chat_action(message.chat.id, "typing")
        ai_answer = await ask_deepseek(message.text)
        
        # Обновляем количество запросов
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET requests_today = ?, last_date = ? WHERE user_id = ?", 
                       (current_reqs + 1, today, u_id))
        conn.commit()
        conn.close()
        
        await message.answer(ai_answer)
    else:
        await message.answer("❌ Дневной лимит (10 запросов) исчерпан.\nКупите безлимит: /buy")

async def main():
    init_db()
    print(f"Бот успешно запущен на модели {MODEL_NAME}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
