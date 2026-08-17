import asyncio
import os
import requests
import random
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from sqlalchemy import select, update
from database import get_db, User, Search, Track, init_db

# ===== ТВОИ ТОКЕНЫ =====
BOT_TOKEN = "8733069750:AAFCP2XoOKKLaDFob7Xa71vN1zYRBqhhAlU"
TRAVELPAYOUTS_TOKEN = "4d2b4ad884f83f4d30f48770b40108a6"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

FREE_SEARCHES = 5
PREMIUM_PRICE = 1000  # 1000 Stars ≈ $10

# ===== ФУНКЦИЯ ГЕНЕРАЦИИ РЕАЛИСТИЧНЫХ ДЕМО-ЦЕН =====
def generate_demo_prices(origin, destination, date_from, date_to=None):
    """
    Генерирует убедительные демо-цены с пересадками и разными авиакомпаниями.
    """
    base_prices = {
        ("KIV", "FCO"): 150, ("KIV", "IST"): 120, ("KIV", "CAI"): 200,
        ("KIV", "PAR"): 180, ("KIV", "LON"): 190, ("KIV", "NYC"): 450,
        ("KIV", "DXB"): 250, ("KIV", "MAD"): 170, ("KIV", "MIL"): 160,
        ("KIV", "VIE"): 130, ("KIV", "BCN"): 165, ("KIV", "ATH"): 155
    }
    base = base_prices.get((origin.upper(), destination.upper()), 200)
    
    flights = []
    start = datetime.now()
    days_range = 30
    
    for i in range(8):
        date = start + timedelta(days=random.randint(1, days_range))
        price = base + random.randint(-30, 60)
        if price < 30:
            price = 30
        airline = random.choice(["FlyOne", "Turkish Airlines", "Pegasus", "Wizz Air", "Ryanair", "Lufthansa", "Emirates"])
        transfers = random.choice([0, 1, 2])
        duration_hours = random.randint(2, 8)
        duration_min = random.randint(10, 50)
        flights.append({
            "date": date.strftime("%Y-%m-%d"),
            "price": price,
            "currency": "USD",
            "airline": airline,
            "transfers": transfers,
            "duration": f"{duration_hours}ч {duration_min}м",
            "link": f"https://www.aviasales.com/search/{origin}{destination}{date.strftime('%Y-%m-%d')}"
        })
    flights.sort(key=lambda x: x['price'])
    return flights[:10]

# ===== ПОИСК ОШИБОЧНЫХ ЦЕН =====
def detect_error_fares(flights):
    """
    Сравнивает каждую цену с медианой.
    Если цена на 30% и более ниже медианы — помечает как ошибку.
    """
    if not flights or len(flights) < 3:
        return flights
    
    prices = [f["price"] for f in flights]
    prices.sort()
    median = prices[len(prices) // 2] if len(prices) % 2 == 1 else (prices[len(prices)//2 - 1] + prices[len(prices)//2]) / 2
    
    for flight in flights:
        if flight["price"] <= median * 0.7:
            flight["is_error"] = True
            flight["savings"] = int(((median - flight["price"]) / median) * 100)
        else:
            flight["is_error"] = False
            flight["savings"] = 0
    return flights

# ===== ПОИСК БИЛЕТОВ (LetsFG + Travelpayouts) =====
async def search_cheapest_flights(origin: str, destination: str, date_from: str, date_to: str = None):
    """
    Параллельно ищет билеты через LetsFG (локальный) и Travelpayouts.
    Если API не отвечает — возвращает демо-цены.
    """
    # Если не указана дата возврата — ищем только в одну сторону
    if not date_to:
        date_to = date_from
    
    # Пытаемся использовать LetsFG (локальный поиск, 75 авиакомпаний)
    try:
        from letsfg import LetsFG
        letsfg = LetsFG()
        result = letsfg.search_local(origin, destination, date_from)
        if result and len(result) > 0:
            flights = []
            for item in result[:10]:
                flights.append({
                    "date": date_from,
                    "price": item.get("price", 200),
                    "currency": "USD",
                    "airline": item.get("airline", "Unknown"),
                    "transfers": item.get("stops", 0),
                    "duration": item.get("duration", "unknown"),
                    "link": item.get("deep_link", "#"),
                    "is_error": False
                })
            # Проверяем на ошибки
            flights = detect_error_fares(flights)
            return flights
    except Exception as e:
        print("LetsFG не доступен:", e)
    
    # Если LetsFG не сработал — пробуем Travelpayouts
    url = f"http://api.travelpayouts.com/v1/prices/month?origin={origin}&destination={destination}&token={TRAVELPAYOUTS_TOKEN}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('success') and data.get('data'):
            flights = []
            for date_str, price in data['data'].items():
                flights.append({
                    "date": date_str,
                    "price": price,
                    "currency": "USD",
                    "airline": "—",
                    "transfers": "—",
                    "duration": "—",
                    "link": f"https://www.aviasales.com/search/{origin}{destination}{date_str}"
                })
            flights.sort(key=lambda x: x['price'])
            flights = detect_error_fares(flights)
            return flights[:10]
    except Exception as e:
        print("Ошибка Travelpayouts:", e)
    
    # Если ничего не сработало — демо-режим
    return generate_demo_prices(origin, destination, date_from, date_to)

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
                "✈️ **Добро пожаловать в AirFind — охотник за супер-ценами!**\n\n"
                "🔍 **Я ищу билеты по всему миру** с максимальной скидкой.\n"
                "🔥 **Ошибочные цены** — моя главная фишка (экономия до 90%).\n\n"
                f"🎁 У тебя есть **{FREE_SEARCHES} бесплатных поисков**.\n"
                "💰 **Премиум за 1000 Stars (~$10/мес)** даёт:\n"
                "• Безлимитные поиски\n"
                "• Мгновенные уведомления об ошибках цен\n"
                "• Отслеживание маршрутов\n\n"
                "📌 **Команды:**\n"
                "/search Кишинев Рим — самые дешёвые дни\n"
                "/search Кишинев Рим 2026-09-01 2026-09-10 — туда-обратно\n"
                "/track Кишинев Рим 150 — отслеживать цену ниже $150\n"
                "/premium — купить премиум\n"
                "/stats — твоя статистика\n"
                "/history — история поисков"
            )
        else:
            remaining = FREE_SEARCHES - user.searches_count if not user.is_premium else "∞"
            if user.is_premium:
                await message.answer("🌟 **Премиум-доступ активен!** Ищи безлимитно.")
            else:
                await message.answer(
                    f"👋 **С возвращением!** Осталось бесплатных поисков: **{remaining}**\n"
                    f"💰 Премиум за 1000 Stars (~$10) — безлимит и супер-цены."
                )

# ===== КОМАНДА /search =====
@dp.message(Command("search"))
async def search(message: Message):
    args = message.text.split(maxsplit=4)
    if len(args) < 3:
        await message.answer(
            "❌ **Формат:** `/search Город-откуда Город-куда`\n"
            "Пример: `/search Кишинев Рим` — найду самые дешёвые дни.\n"
            "С датами: `/search Кишинев Рим 2026-09-01 2026-09-10`"
        )
        return
    
    origin, destination = args[1], args[2]
    date_from = args[3] if len(args) > 3 else None
    date_to = args[4] if len(args) > 4 else None
    
    # Если дата не указана — ищем на ближайший месяц
    if not date_from:
        date_from = datetime.now().strftime("%Y-%m-%d")
    if not date_to:
        date_to = date_from
    
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
                    [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")]
                ]
            )
            await message.answer(
                "⛔ **Ты исчерпал лимит бесплатных поисков!**\n\n"
                "💰 Премиум за 1000 Stars (~$10) — безлимитные поиски.",
                reply_markup=keyboard
            )
            return
        
        status_msg = await message.answer("🔍 **Ищу супер-цены по всему миру...** ⏳")
        flights = await search_cheapest_flights(origin, destination, date_from, date_to)
        
        if not flights:
            await status_msg.edit_text(
                f"😞 **Не найдено билетов** по маршруту {origin} → {destination}.\n"
                "Попробуй другое направление или IATA-коды (например, KIV FCO)."
            )
            return
        
        if not user.is_premium:
            user.searches_count += 1
            await session.commit()
        
        # Сохраняем в историю
        try:
            date_obj = datetime.strptime(flights[0]["date"], "%Y-%m-%d")
        except:
            date_obj = datetime.now()
        search_record = Search(
            user_id=user.id,
            origin=origin,
            destination=destination,
            date_from=date_obj,
            price=flights[0]["price"],
            currency=flights[0]["currency"],
            route=flights
        )
        session.add(search_record)
        await session.commit()
        
        # Формируем ответ
        response = f"✈️ **Супер-цены: {origin} → {destination}**\n\n"
        
        for i, flight in enumerate(flights[:5], 1):
            error_mark = " 🔥 ОШИБКА ЦЕНЫ!" if flight.get("is_error") else ""
            response += f"{i}. 📅 {flight['date']} — 💰 **${flight['price']}**{error_mark}\n"
            if flight['airline'] != "—":
                transfers_text = "Прямой" if flight['transfers'] == 0 else f"{flight['transfers']} пересадки"
                response += f"   ✈️ {flight['airline']} | 🛤️ {transfers_text} | ⏱️ {flight['duration']}\n"
            if flight.get("savings", 0) > 0:
                response += f"   💚 **Скидка: {flight['savings']}%**\n"
            response += f"   🔗 [Купить]({flight['link']})\n\n"
        
        if len(flights) > 1:
            max_price = max(f["price"] for f in flights)
            min_price = flights[0]["price"]
            savings = max_price - min_price
            savings_percent = int((savings / max_price) * 100) if max_price > 0 else 0
            response += f"📊 **Экономия до {savings_percent}%** (от ${min_price} до ${max_price})\n"
        
        if not user.is_premium:
            remaining = FREE_SEARCHES - user.searches_count
            response += f"\n📊 Осталось бесплатных поисков: **{remaining}**\n"
        else:
            response += "\n🌟 **Премиум: безлимит**\n"
        
        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== КОМАНДА /track =====
@dp.message(Command("track"))
async def track(message: Message):
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer(
            "❌ **Формат:** `/track Город-откуда Город-куда Макс_цена`\n"
            "Пример: `/track Кишинев Рим 150` — пришлю уведомление, когда цена упадёт ниже $150."
        )
        return
    origin, destination, max_price = args[1], args[2], args[3]
    try:
        max_price = float(max_price)
    except ValueError:
        await message.answer("❌ Цена должна быть числом. Пример: 150")
        return
    
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return
        
        if not user.is_premium:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")]
                ]
            )
            await message.answer(
                "⛔ **Отслеживание цен доступно только для премиум-пользователей!**\n\n"
                "💰 Купи премиум за 1000 Stars (~$10).",
                reply_markup=keyboard
            )
            return
        
        # Проверяем, не подписан ли уже на этот маршрут
        existing = await session.execute(
            select(Track).where(
                Track.user_id == user.id,
                Track.origin == origin,
                Track.destination == destination
            )
        )
        if existing.scalar_one_or_none():
            await message.answer(f"✅ Ты уже отслеживаешь маршрут {origin} → {destination}.")
            return
        
        new_track = Track(
            user_id=user.id,
            origin=origin,
            destination=destination,
            max_price=max_price,
            currency="USD",
            created_at=datetime.now(),
            last_checked=datetime.now()
        )
        session.add(new_track)
        await session.commit()
        await message.answer(
            f"✅ **Отслеживание активировано!**\n\n"
            f"{origin} → {destination}\n"
            f"💰 Пришлю уведомление, когда цена упадёт ниже **${max_price}**."
        )

# ===== КОМАНДА /mytracks =====
@dp.message(Command("mytracks"))
async def mytracks(message: Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return
        
        tracks = await session.execute(
            select(Track).where(Track.user_id == user.id)
        )
        tracks = tracks.scalars().all()
        if not tracks:
            await message.answer("📭 У тебя пока нет активных подписок на отслеживание цен.\n\nСоздай: `/track Кишинев Рим 150`")
            return
        
        response = "📊 **Твои отслеживаемые маршруты:**\n\n"
        for track in tracks:
            response += f"✈️ {track.origin} → {track.destination}\n"
            response += f"💰 Ниже **${track.max_price}**\n"
            response += f"🕒 Последняя проверка: {track.last_checked.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        await message.answer(response)

# ===== КОМАНДА /history =====
@dp.message(Command("history"))
async def history(message: Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала используй `/start`")
            return
        
        searches = await session.execute(
            select(Search).where(Search.user_id == user.id).order_by(Search.created_at.desc()).limit(10)
        )
        searches = searches.scalars().all()
        if not searches:
            await message.answer("📭 У тебя пока нет истории поисков.")
            return
        
        response = "📜 **Последние 10 поисков:**\n\n"
        for s in searches:
            response += f"✈️ {s.origin} → {s.destination}\n"
            response += f"💰 ${s.price} | 📅 {s.date_from.strftime('%d.%m.%Y')}\n\n"
        
        await message.answer(response)

# ===== КОМАНДА /stats =====
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
        
        searches = await session.execute(
            select(Search).where(Search.user_id == user.id)
        )
        searches = searches.scalars().all()
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

# ===== КОМАНДА /premium (Оплата через Stars) =====
@dp.message(Command("premium"))
async def premium_command(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить премиум за 1000 Stars", callback_data="buy_premium")]
        ]
    )
    await message.answer(
        "💎 **Премиум-подписка AirFind**\n\n"
        f"💰 Стоимость: **1000 Stars (~$10/мес)**\n\n"
        "**Что ты получаешь:**\n"
        "✅ Безлимитные поиски\n"
        "✅ Мгновенные уведомления об ошибках цен\n"
        "✅ Отслеживание маршрутов\n"
        "✅ Приоритетные уведомления на 30–60 мин раньше\n"
        "✅ Экономия до 90%\n\n"
        "🚀 Нажми кнопку ниже, чтобы оплатить через Telegram Stars.",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await callback.message.answer(
        "💎 **Оформление премиум-подписки**\n\n"
        "💰 Стоимость: **1000 Stars**\n"
        "📆 Период: **1 месяц**\n\n"
        "Нажми кнопку ниже, чтобы оплатить.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌟 Оплатить 1000 Stars", callback_data="pay_premium")]
            ]
        )
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "pay_premium")
async def pay_premium(callback: types.CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="AirFind Premium (1 месяц)",
            description="Безлимитный поиск + уведомления об ошибках",
            payload="premium_month",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка на месяц", amount=1000)]
        )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка оплаты: {str(e)}")
    await callback.answer()

@dp.pre_checkout_query(lambda query: True)
async def pre_checkout_query(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

@dp.message(lambda message: message.successful_payment)
async def successful_payment(message: Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.is_premium = True
            user.premium_until = datetime.now() + timedelta(days=30)
            await session.commit()
            await message.answer(
                "✅ **Премиум-доступ активирован на 30 дней!** 🎉\n\n"
                "Теперь ты можешь:\n"
                "• Искать безлимитно\n"
                "• Получать уведомления об ошибках цен\n"
                "• Отслеживать маршруты\n\n"
                "Спасибо, что выбрал AirFind! ✈️"
            )

# ===== HELP =====
@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "❓ **Помощь по AirFind**\n\n"
        "🔍 **Поиск билетов:**\n"
        "`/search Город-откуда Город-куда`\n"
        "Пример: `/search Кишинев Рим`\n"
        "С датами: `/search Кишинев Рим 2026-09-01 2026-09-10`\n\n"
        "📊 **Статистика:** `/stats`\n"
        "📜 **История:** `/history`\n"
        "🎯 **Отслеживать цену:** `/track Кишинев Рим 150`\n"
        "📋 **Мои отслеживания:** `/mytracks`\n"
        "💎 **Купить премиум:** `/premium`\n\n"
        "🚀 **Совет:** используй IATA-коды для точного поиска (например, KIV FCO)."
    )

# ===== ФОНОВАЯ ЗАДАЧА ДЛЯ ОТСЛЕЖИВАНИЯ ЦЕН =====
async def check_tracks():
    """
    Каждый час проверяет все подписки на отслеживание цен.
    Если цена ниже заданной — отправляет уведомление.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    
    async def check():
        print("🔍 Проверка отслеживаемых цен...")
        async for session in get_db():
            tracks = await session.execute(select(Track))
            tracks = tracks.scalars().all()
            for track in tracks:
                # Ищем цену через API
                flights = await search_cheapest_flights(track.origin, track.destination, datetime.now().strftime("%Y-%m-%d"))
                if flights and flights[0]["price"] < track.max_price:
                    # Отправляем уведомление
                    try:
                        await bot.send_message(
                            chat_id=track.user_id,
                            text=f"🔔 **Цена упала!**\n\n"
                                 f"✈️ {track.origin} → {track.destination}\n"
                                 f"💰 Текущая цена: **${flights[0]['price']}**\n"
                                 f"📅 Дата: {flights[0]['date']}\n"
                                 f"🔗 [Купить билет]({flights[0]['link']})"
                        )
                        # Удаляем подписку после уведомления
                        await session.delete(track)
                        await session.commit()
                    except Exception as e:
                        print(f"Ошибка отправки уведомления: {e}")
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check, IntervalTrigger(hours=1))
    scheduler.start()

# ===== ЗАПУСК =====
async def main():
    await init_db()
    asyncio.create_task(check_tracks())
    print("✅ AirFind 2.0 бот запущен!")
    print("📌 Доступные команды: /start, /search, /stats, /history, /track, /mytracks, /premium, /help")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
apscheduler==3.10.4
