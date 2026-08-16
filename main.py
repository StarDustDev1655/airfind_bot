import asyncio
import os
import requests
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from database import get_db, User, Search, init_db

# ===== ТВОИ ТОКЕНЫ (УЖЕ ВСТАВЛЕНЫ) =====
BOT_TOKEN = "8733069750:AAFCP2XoOKKLaDFob7Xa71vN1zYRBqhhAlU"
TRAVELPAYOUTS_TOKEN = "4d2b4ad884f83f4d30f48770b40108a6"

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

FREE_SEARCHES = 5
PREMIUM_PRICE = 10

# ===== ФУНКЦИЯ ПОИСКА САМЫХ ДЕШЁВЫХ БИЛЕТОВ ЗА 60 ДНЕЙ =====
async def search_cheapest_flights(origin: str, destination: str):
    """
    Ищет самые дешёвые билеты по направлению на ближайшие 60 дней.
    Возвращает список до 10 вариантов, отсортированных по цене.
    Если API не работает — возвращает демо-данные.
    """
    if not TRAVELPAYOUTS_TOKEN:
        # Демо-режим
        return [
            {"date": "2026-09-15", "price": 49, "currency": "USD", "airline": "FlyOne (лоукостер)", "transfers": 0, "duration": "2ч 15м", "link": "#"},
            {"date": "2026-09-22", "price": 67, "currency": "USD", "airline": "Turkish Airlines", "transfers": 1, "duration": "4ч 20м", "link": "#"},
            {"date": "2026-10-05", "price": 89, "currency": "USD", "airline": "Pegasus", "transfers": 1, "duration": "5ч 10м", "link": "#"},
        ]
    
    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    
    url = "https://api.travelpayouts.com/graphql/v1/query"
    headers = {"Content-Type": "application/json", "X-Access-Token": TRAVELPAYOUTS_TOKEN}
    query = f"""
    {{
      prices_one_way(
        params: {{
          origin: "{origin}"
          destination: "{destination}"
          depart_date: "{start_date}"
          return_date: "{end_date}"
        }}
        paging: {{ limit: 20 }}
        sorting: VALUE_ASC
      ) {{
        departure_at
        value
        currency
        trip_duration
        transfers
        airline
        ticket_link
      }}
    }}
    """
    try:
        response = requests.post(url, json={"query": query}, headers=headers)
        data = response.json()
        if "errors" in data or not data.get("data", {}).get("prices_one_way"):
            return None
        flights_data = data["data"]["prices_one_way"]
        result = []
        for flight in flights_data:
            result.append({
                "date": flight["departure_at"][:10] if flight.get("departure_at") else "дата неизвестна",
                "price": flight["value"],
                "currency": flight.get("currency", "USD"),
                "airline": flight.get("airline", "Неизвестно"),
                "transfers": flight.get("transfers", 0),
                "duration": flight.get("trip_duration", "неизвестно"),
                "link": flight.get("ticket_link", "https://www.aviasales.com/")
            })
        return result[:10]  # Топ-10 самых дешёвых
    except Exception as e:
        print("Ошибка API:", e)
        return None

# ===== КОМАНДА /start =====
@dp.message(Command("start"))
async def start(message: Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name
            )
            session.add(new_user)
            await session.commit()
            await message.answer(
                "✈️ **Добро пожаловать в AirFind — твой охотник за дешёвыми билетами!**\n\n"
                f"🎁 У тебя есть {FREE_SEARCHES} бесплатных поисков.\n"
                "💰 **Премиум за $10/мес** даёт:\n"
                "• Безлимитные поиски\n"
                "• Самые дешёвые билеты за 2 месяца\n"
                "• Сравнение цен и экономия до 70%\n"
                "• Сложные маршруты с пересадками\n"
                "• Лоукостеры (Ryanair, Wizz Air, FlyOne и др.)\n\n"
                "🔍 Просто напиши: `/search Кишинев Рим`\n"
                "📊 Статистика: `/stats`"
            )
        else:
            remaining = FREE_SEARCHES - user.searches_count if not user.is_premium else "∞"
            if user.is_premium:
                await message.answer("🌟 **Премиум-доступ активен!** Ищи безлимитно.")
            else:
                await message.answer(
                    f"👋 **С возвращением!** Осталось бесплатных поисков: **{remaining}**\n"
                    f"💰 Премиум за ${PREMIUM_PRICE}/мес — безлимит и эксклюзивные фичи."
                )

# ===== КОМАНДА /search (НОВАЯ ВЕРСИЯ — БЕЗ ДАТЫ) =====
@dp.message(Command("search"))
async def search(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ **Формат:** `/search Город-откуда Город-куда`\n"
            "Пример: `/search Кишинев Рим`\n"
            "Я найду самые дешёвые билеты на ближайшие 2 месяца."
        )
        return
    origin, destination = args[1], args[2]

    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return

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

        status_msg = await message.answer("🔍 **Ищу самые дешёвые билеты...** ⏳")
        flights = await search_cheapest_flights(origin, destination)

        if not flights:
            await status_msg.edit_text(
                f"😞 **Не найдено билетов** по маршруту {origin} → {destination}.\n"
                "Попробуй другое направление или используй IATA-коды (например, KIV FCO)."
            )
            return

        if not user.is_premium:
            user.searches_count += 1
            await session.commit()

        cheapest = flights[0]
        try:
            date_obj = datetime.strptime(cheapest["date"], "%Y-%m-%d") if cheapest["date"] != "дата неизвестна" else datetime.now()
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

        response = f"✈️ **Самые дешёвые билеты {origin} → {destination}**\n\n"
        for i, flight in enumerate(flights[:5], 1):
            transfers_text = "Прямой" if flight["transfers"] == 0 else f"{flight['transfers']} пересадк{'' if flight['transfers']==1 else 'и'}"
            response += f"{i}. 📅 {flight['date']} — 💰 **${flight['price']}** ({flight['currency']})\n"
            response += f"   ✈️ {flight['airline']} | 🛤️ {transfers_text} | ⏱️ {flight.get('duration', 'неизвестно')}\n"
            response += f"   🔗 [Купить]({flight['link']})\n\n"

        if len(flights) > 1:
            max_price = max(f["price"] for f in flights)
            min_price = flights[0]["price"]
            savings = max_price - min_price
            savings_percent = int((savings / max_price) * 100) if max_price > 0 else 0
            response += f"📊 **Экономия до {savings_percent}%** (самый дорогой ${max_price}, самый дешёвый ${min_price})\n"

        if not user.is_premium:
            remaining = FREE_SEARCHES - user.searches_count
            response += f"\n📊 Осталось бесплатных поисков: **{remaining}**\n"
        else:
            response += "\n🌟 **Премиум-доступ: безлимит**\n"

        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== ПРЕМИУМ =====
@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await callback.message.answer(
        "💎 **Оформление премиум-подписки**\n\n"
        f"💰 Стоимость: **${PREMIUM_PRICE}/мес**\n\n"
        "🔹 Безлимитные поиски\n"
        "🔹 Самые дешёвые билеты за 2 месяца\n"
        "🔹 Экономия до 70%\n"
        "🔹 Ошибки цен (эксклюзивно)\n"
        "🔹 Сложные маршруты с пересадками\n"
        "🔹 Лоукостеры\n\n"
        "🚀 **Пока что активируем ТЕСТОВЫЙ доступ на 7 дней!**",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌟 Активировать тестовый премиум", callback_data="activate_premium")]
            ]
        )
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "activate_premium")
async def activate_premium(callback: types.CallbackQuery):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback.message.answer("❌ Сначала используй `/start`")
            await callback.answer()
            return
        if user.is_premium:
            await callback.message.answer("🌟 **У тебя уже есть премиум-доступ!**")
            await callback.answer()
            return
        user.is_premium = True
        user.premium_until = datetime.now() + timedelta(days=7)
        await session.commit()
        await callback.message.answer(
            "✅ **Премиум-доступ активирован на 7 дней!** 🎉\n\n"
            "Теперь ты можешь искать безлимитно и получать самые выгодные предложения."
        )
    await callback.answer()

# ===== СТАТИСТИКА =====
@dp.message(Command("stats"))
async def stats(message: Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return
        searches_result = await session.execute(
            select(Search).where(Search.user_id == user.id)
        )
        searches = searches_result.scalars().all()
        total_searches = len(searches)
        total_savings = 0
        for search in searches:
            if search.route:
                try:
                    flights = search.route
                    if flights and len(flights) > 0:
                        avg_price = sum(f["price"] for f in flights) / len(flights)
                        min_price = min(f["price"] for f in flights)
                        total_savings += avg_price - min_price
                except:
                    pass
        await message.answer(
            f"📊 **Твоя статистика в AirFind**\n\n"
            f"🔍 Всего поисков: **{total_searches}**\n"
            f"🎁 Осталось бесплатных: **{FREE_SEARCHES - user.searches_count if not user.is_premium else '∞'}**\n"
            f"💎 Премиум: **{'✅ Да' if user.is_premium else '❌ Нет'}**\n"
            f"💰 Примерно сэкономлено: **${total_savings:.0f}**"
        )

# ===== HELP =====
@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "❓ **Помощь по AirFind**\n\n"
        "🔍 **Поиск билетов:**\n"
        "`/search Город-откуда Город-куда`\n"
        "Пример: `/search Кишинев Рим`\n\n"
        "📊 **Статистика:** `/stats`\n"
        "💎 **Купить премиум:** `/premium`\n"
        "❓ **Помощь:** `/help`\n\n"
        "🚀 **Совет:** используй IATA-коды для точного поиска (например, KIV FCO)."
    )

@dp.message(Command("premium"))
async def premium_command(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Получить премиум", callback_data="buy_premium")]
        ]
    )
    await message.answer(
        "💎 **Премиум-подписка AirFind**\n\n"
        f"💰 Стоимость: **${PREMIUM_PRICE}/мес**\n\n"
        "**Что ты получаешь:**\n"
        "✅ Безлимитные поиски\n"
        "✅ Самые дешёвые билеты за 2 месяца\n"
        "✅ Экономия до 70%\n"
        "✅ Ошибки цен (скоро)\n"
        "✅ Лоукостеры\n\n"
        "🚀 **Попробуй бесплатно 7 дней!**",
        reply_markup=keyboard
    )

# ===== ЗАПУСК =====
async def main():
    await init_db()
    print("✅ AirFind бот запущен!")
    print("📌 Доступные команды: /start, /search, /stats, /premium, /help")
    if not TRAVELPAYOUTS_TOKEN:
        print("⚠️ ВНИМАНИЕ: TRAVELPAYOUTS_TOKEN не найден! Бот работает в ДЕМО-РЕЖИМЕ.")
    else:
        print("✅ Travelpayouts токен найден. Бот ищет реальные билеты!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
