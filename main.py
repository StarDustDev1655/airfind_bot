import asyncio
import os
import requests
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from database import get_db, User, Search, init_db

# ===== ТВОИ ТОКЕНЫ =====
BOT_TOKEN = "8733069750:AAFCP2XoOKKLaDFob7Xa71vN1zYRBqhhAlU"
TRAVELPAYOUTS_TOKEN = "4d2b4ad884f83f4d30f48770b40108a6"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

FREE_SEARCHES = 5
PREMIUM_PRICE = 10

# ===== НОВАЯ ФУНКЦИЯ ПОИСКА (REST API) =====
async def search_cheapest_flights(origin: str, destination: str):
    """
    Ищет минимальные цены на каждый день в ближайшем месяце.
    Использует простой REST-запрос (работает надёжнее GraphQL).
    """
    if not TRAVELPAYOUTS_TOKEN:
        # Демо-режим
        return [
            {"date": "2026-09-15", "price": 49, "currency": "USD", "airline": "FlyOne", "transfers": 0, "duration": "2ч 15м", "link": "#"},
            {"date": "2026-09-22", "price": 67, "currency": "USD", "airline": "Turkish Airlines", "transfers": 1, "duration": "4ч 20м", "link": "#"},
            {"date": "2026-10-05", "price": 89, "currency": "USD", "airline": "Pegasus", "transfers": 1, "duration": "5ч 10м", "link": "#"},
        ]
    
    url = f"http://api.travelpayouts.com/v1/prices/month?origin={origin}&destination={destination}&token={TRAVELPAYOUTS_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        # Проверка ответа
        if not data.get('success') or not data.get('data'):
            print("API вернул ошибку:", data)
            return None
        
        flights = []
        for date_str, price in data['data'].items():
            # price — это минимальная цена на эту дату
            flights.append({
                "date": date_str,
                "price": price,
                "currency": "USD",
                "airline": "—",
                "transfers": "—",
                "duration": "—",
                "link": f"https://www.aviasales.com/search/{origin}{destination}{date_str}"
            })
        
        # Сортируем по цене (от дешёвых к дорогим)
        flights.sort(key=lambda x: x['price'])
        return flights[:10]  # Топ-10 самых дешёвых дней
    except Exception as e:
        print("Ошибка при запросе к API:", e)
        return None

# ===== КОМАНДА /search =====
@dp.message(Command("search"))
async def search(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ **Формат:** `/search Город-откуда Город-куда`\n"
            "Пример: `/search Кишинев Рим`\n"
            "Я найду самые дешёвые дни для перелёта в ближайший месяц.\n"
            "⚠️ Для точного поиска используй IATA-коды (например, KIV FCO)."
        )
        return
    origin, destination = args[1], args[2]

    async for session in get_db():
        # Проверка пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return

        # Лимиты
        if not user.is_premium and user.searches_count >= FREE_SEARCHES:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Купить премиум за $10", callback_data="buy_premium")]
                ]
            )
            await message.answer(
                "⛔ **Ты исчерпал лимит бесплатных поисков!**\n\n"
                f"💰 **Премиум за ${PREMIUM_PRICE}/мес** — безлимитные поиски и лучшие цены.",
                reply_markup=keyboard
            )
            return

        status_msg = await message.answer("🔍 **Ищу самые дешёвые дни для перелёта...** ⏳")
        flights = await search_cheapest_flights(origin, destination)

        if not flights:
            await status_msg.edit_text(
                f"😞 **Не найдено билетов** по маршруту {origin} → {destination}.\n"
                "Попробуй другое направление или используй IATA-коды (например, KIV FCO).\n"
                "Если проблема повторяется — возможно, API-ключ ещё не активирован (подожди до 24 часов)."
            )
            return

        # Увеличиваем счётчик
        if not user.is_premium:
            user.searches_count += 1
            await session.commit()

        # Сохраняем в историю
        cheapest = flights[0]
        try:
            date_obj = datetime.strptime(cheapest["date"], "%Y-%m-%d")
        except:
            date_obj = datetime.now()
        search_record = Search(
            user_id=user.id,
            origin=origin,
            destination=destination,
            date_from=date_obj,
            price=cheapest["price"],
            currency=cheapest["currency"],
            route=flights
        )
        session.add(search_record)
        await session.commit()

        # Формируем ответ
        response = f"✈️ **Самые дешёвые дни для {origin} → {destination}**\n\n"
        for i, flight in enumerate(flights[:5], 1):
            response += f"{i}. 📅 {flight['date']} — 💰 **${flight['price']}**\n"
            if flight['airline'] != "—":
                response += f"   ✈️ {flight['airline']} | 🛤️ {flight['transfers']} пересадок | ⏱️ {flight['duration']}\n"
            response += f"   🔗 [Посмотреть билеты]({flight['link']})\n\n"

        if len(flights) > 1:
            max_price = max(f["price"] for f in flights)
            min_price = flights[0]["price"]
            savings = max_price - min_price
            savings_percent = int((savings / max_price) * 100) if max_price > 0 else 0
            response += f"📊 **Разница в цене:** от ${min_price} до ${max_price} (экономия до {savings_percent}%)\n"

        if not user.is_premium:
            remaining = FREE_SEARCHES - user.searches_count
            response += f"\n📊 Осталось бесплатных поисков: **{remaining}**\n"
        else:
            response += "\n🌟 **Премиум-доступ: безлимит**\n"

        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== ОСТАЛЬНЫЕ КОМАНДЫ (start, stats, premium, help) остаются без изменений =====
# Я их не вставляю, чтобы не загромождать, но они должны быть в коде.
# Полный файл я приложу ниже.
