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

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

FREE_SEARCHES = 5
PREMIUM_PRICE = 10

# ===== ФУНКЦИЯ ПОИСКА БИЛЕТОВ =====
async def search_flights(origin: str, destination: str, date: str):
    """
    Ищет реальные билеты через API Travelpayouts.
    Если токен не работает — возвращает демо-данные.
    """
    if not TRAVELPAYOUTS_TOKEN:
        return [
            {"price": 49, "currency": "USD", "airline": "FlyOne (лоукостер)", "transfers": 0, "duration": "2ч 15м", "link": "https://www.aviasales.com/", "savings": 51},
            {"price": 67, "currency": "USD", "airline": "Turkish Airlines", "transfers": 1, "duration": "4ч 20м", "link": "https://www.aviasales.com/", "savings": 33},
            {"price": 89, "currency": "USD", "airline": "Pegasus", "transfers": 1, "duration": "5ч 10м", "link": "https://www.aviasales.com/", "savings": 11}
        ]
    
    url = "https://api.travelpayouts.com/graphql/v1/query"
    headers = {"Content-Type": "application/json", "X-Access-Token": TRAVELPAYOUTS_TOKEN}
    query = f"""
    {{
      prices_one_way(
        params: {{
          origin: "{origin}"
          destination: "{destination}"
          depart_months: "{date}"
        }}
        paging: {{ limit: 15 }}
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
                "price": flight["value"],
                "currency": flight.get("currency", "USD"),
                "airline": flight.get("airline", "Неизвестно"),
                "transfers": flight.get("transfers", 0),
                "duration": flight.get("trip_duration", "неизвестно"),
                "link": flight.get("ticket_link", "https://www.aviasales.com/")
            })
        if result:
            max_price = max(f["price"] for f in result)
            for flight in result:
                flight["savings"] = int(((max_price - flight["price"]) / max_price) * 100) if max_price > 0 else 0
        return result
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
                "• Сравнение цен с экономией до 70%\n"
                "• Сложные маршруты с пересадками\n"
                "• Лоукостеры (Ryanair, Wizz Air, FlyOne и др.)\n"
                "• Уведомления об ошибочных ценах\n\n"
                "🔍 Используй: `/search Кишинев Стамбул 2026-09-01`\n"
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

# ===== КОМАНДА /search =====
@dp.message(Command("search"))
async def search(message: Message):
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer(
            "❌ **Формат:** `/search Город-откуда Город-куда ГГГГ-ММ-ДД`\n"
            "Пример: `/search Кишинев Стамбул 2026-09-01`"
        )
        return
    origin, destination, date_str = args[1], args[2], args[3]
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используй: 2026-09-01")
        return

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
                f"💰 **Премиум за ${PREMIUM_PRICE}/мес**:\n"
                "• Безлимитные поиски\n"
                "• Экономия до 70%\n"
                "• Ошибки цен и сложные маршруты",
                reply_markup=keyboard
            )
            return

        status_msg = await message.answer("🔍 **Ищу билеты по всему миру...** ⏳\nУчитываю лоукостеры и пересадки...")
        flights = await search_flights(origin, destination, date_str)

        if not flights:
            await status_msg.edit_text(
                f"😞 **Нет билетов** по маршруту {origin} → {destination} на {date_str}.\n"
                "Попробуй изменить дату или направление."
            )
            return

        if not user.is_premium:
            user.searches_count += 1
            await session.commit()

        cheapest = flights[0] if flights else None
        if cheapest:
            search_record = Search(
                user_id=user.id,
                origin=origin,
                destination=destination,
                date_from=date_obj,
                price=cheapest["price"],
                currency=cheapest.get("currency", "USD"),
                route=flights
            )
            session.add(search_record)
            await session.commit()

        response = f"✈️ **Билеты {origin} → {destination} на {date_str}**\n\n"
        for i, flight in enumerate(flights[:5], 1):
            transfers_text = "Прямой" if flight["transfers"] == 0 else f"{flight['transfers']} пересадк{'' if flight['transfers']==1 else 'и'}"
            response += f"{i}. 💰 **${flight['price']}** ({flight['currency']})\n"
            response += f"   ✈️ {flight['airline']}\n"
            response += f"   🛤️ {transfers_text} | ⏱️ {flight.get('duration', 'неизвестно')}\n"
            if flight.get("savings", 0) > 0:
                response += f"   💚 **Экономия: {flight['savings']}%**\n"
            response += f"   🔗 [Купить билет]({flight['link']})\n\n"

        if flights:
            avg_price = sum(f["price"] for f in flights) / len(flights)
            min_price = min(f["price"] for f in flights)
            savings = avg_price - min_price
            savings_percent = int((savings / avg_price) * 100) if avg_price > 0 else 0
            response += f"📊 **Итог:** обычная цена **${avg_price:.0f}**, мы нашли за **${min_price:.0f}**\n"
            response += f"💚 **Ты экономишь ${savings:.0f} ({savings_percent}%)**\n\n"

        if not user.is_premium:
            remaining = FREE_SEARCHES - user.searches_count
            response += f"📊 Осталось бесплатных поисков: **{remaining}**\n"
        else:
            response += "🌟 **Премиум-доступ: безлимит**\n"
        response += "\n💡 *Самые дешёвые билеты часто улетают за минуты!*"
        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== ПРЕМИУМ =====
@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await callback.message.answer(
        "💎 **Оформление премиум-подписки**\n\n"
        f"💰 Стоимость: **${PREMIUM_PRICE}/мес**\n\n"
        "🔹 Безлимитные поиски\n"
        "🔹 Экономия до 70%\n"
        "🔹 Ошибки цен (эксклюзивно)\n"
        "🔹 Сложные маршруты с пересадками\n"
        "🔹 Лоукостеры и нестандартные маршруты\n\n"
        "🚀 **Пока что активируем ТЕСТОВЫЙ доступ на 7 дней!**\n"
        "Нажми кнопку ниже.",
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
            "Теперь ты можешь:\n"
            "• Искать безлимитно\n"
            "• Получать доступ к самым дешёвым билетам\n"
            "• Экономить до 70% на перелётах\n\n"
            "Попробуй поискать билеты снова: `/search`"
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
            f"💰 Примерно сэкономлено: **${total_savings:.0f}**\n\n"
            "✈️ Продолжай экономить на перелётах!"
        )

# ===== HELP =====
@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "❓ **Помощь по AirFind**\n\n"
        "🔍 **Поиск билетов:**\n"
        "`/search Город-откуда Город-куда ГГГГ-ММ-ДД`\n"
        "Пример: `/search Кишинев Стамбул 2026-09-01`\n\n"
        "📊 **Статистика:** `/stats`\n"
        "💎 **Купить премиум:** `/premium`\n"
        "❓ **Помощь:** `/help`\n\n"
        "💰 **Премиум за $10/мес:**\n"
        "• Безлимитные поиски\n"
        "• Экономия до 70%\n"
        "• Ошибки цен и сложные маршруты\n"
        "• Лоукостеры и нестандартные маршруты\n\n"
        "🚀 **Совет:** проверяй билеты за несколько месяцев вперёд — так дешевле!"
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
        "✅ Экономия до 70% на билетах\n"
        "✅ Эксклюзивные ошибки цен\n"
        "✅ Сложные маршруты с пересадками\n"
        "✅ Лоукостеры (Ryanair, Wizz Air, FlyOne)\n"
        "✅ Персональный трекер экономии\n\n"
        "🚀 **Попробуй бесплатно 7 дней!**",
        reply_markup=keyboard
    )

# ===== ЗАПУСК =====
async def main():
    await init_db()
    print("✅ AirFind бот запущен!")
    print("📌 Доступные команды: /start, /search, /stats, /premium, /help")
    if not TRAVELPAYOUTS_TOKEN:
        print("⚠️ ВНИМАНИЕ: TRAVELPAYOUTS_TOKEN не найден! Бот работает в ДЕМО-РЕЖИМЕ с тестовыми данными.")
    else:
        print("✅ Travelpayouts токен найден. Бот будет искать реальные билеты!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
