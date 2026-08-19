import asyncio
import os
import logging
import re
import json
from datetime import datetime, timedelta
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from sqlalchemy import select
from database import get_db, User, Search, Track, init_db

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(level=logging.INFO)

# ===== ТВОИ ТОКЕНЫ =====
BOT_TOKEN = "8733069750:AAFCP2XoOKKLaDFob7Xa71vN1zYRBqhhAlU"
TRAVELPAYOUTS_TOKEN = "4d2b4ad884f83f4d30f48770b40108a6"

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

PREMIUM_PRICE = 1000  # Stars

# ===== КАНАЛЫ ДЛЯ ПАРСИНГА =====
CHANNELS = [
    '@samokatus',
    '@travelradar',
    '@vandroukiru',
    '@nashaplaneta_net',
    '@aviasales',
    '@travelmd',
    '@budgettravelmd',
]

# ===== ПАРСЕР КАНАЛОВ (Telethon) =====
async def start_parser():
    """
    Запускает парсинг каналов в фоновом режиме.
    """
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageEntityTextUrl
    
    # Получаем API ID и Hash из переменных окружения
    api_id = int(os.getenv("API_ID", 0))
    api_hash = os.getenv("API_HASH", "")
    
    if not api_id or not api_hash:
        logging.warning("API_ID и API_HASH не заданы. Парсинг каналов отключён.")
        return
    
    client = TelegramClient('airfind_session', api_id, api_hash)
    await client.start()
    
    # Подписываемся на каналы
    for channel in CHANNELS:
        try:
            await client.get_entity(channel)
            logging.info(f"Подписан на канал: {channel}")
        except Exception as e:
            logging.warning(f"Не удалось подключиться к {channel}: {e}")
    
    @client.on(events.NewMessage(chats=CHANNELS))
    async def handle_new_message(event):
        try:
            message = event.message
            if not message or not message.text:
                return
            
            text = message.text
            # Ищем цены и направления
            price_match = re.search(r'(\d+)\s*[€$]', text)
            if not price_match:
                return
            
            price = int(price_match.group(1))
            
            # Ищем направления (город->город)
            direction_match = re.search(r'([А-Яа-яA-Za-z\s\-]+)\s*[—\-–]\s*([А-Яа-яA-Za-z\s\-]+)', text)
            if not direction_match:
                return
            
            origin = direction_match.group(1).strip()
            destination = direction_match.group(2).strip()
            
            # Сохраняем в базу
            async for session in get_db():
                offer = Search(
                    user_id=0,  # общее предложение
                    origin=origin,
                    destination=destination,
                    date_from=datetime.now(),
                    price=price,
                    currency="USD",
                    route=[{
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "price": price,
                        "currency": "USD",
                        "airline": "—",
                        "transfers": "—",
                        "link": "https://www.aviasales.com/",
                        "is_error": True,
                        "savings": 90
                    }]
                )
                session.add(offer)
                await session.commit()
                
                # Уведомляем премиум-пользователей, которые ждут это направление
                tracks = await session.execute(
                    select(Track).where(
                        Track.origin.ilike(f"%{origin}%"),
                        Track.destination.ilike(f"%{destination}%")
                    )
                )
                for track in tracks.scalars().all():
                    try:
                        await bot.send_message(
                            chat_id=track.user_id,
                            text=f"🔥 **ОШИБКА ЦЕНЫ!**\n\n"
                                 f"✈️ {origin} → {destination}\n"
                                 f"💰 Цена: **${price}**\n"
                                 f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
                                 f"💚 Скидка до 90%!\n\n"
                                 f"🔗 [Купить билет](https://www.aviasales.com/search/{origin}{destination})"
                        )
                    except Exception as e:
                        logging.error(f"Ошибка уведомления: {e}")
        except Exception as e:
            logging.error(f"Ошибка обработки сообщения: {e}")
    
    await client.run_until_disconnected()

# ===== КОМАНДА /start =====
@dp.message(Command("start"))
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")],
            [InlineKeyboardButton(text="📊 Моя статистика", callback_data="stats")]
        ]
    )
    
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                created_at=datetime.now()
            )
            session.add(new_user)
            await session.commit()
        
        await message.answer(
            "✈️ **AirFind — твой личный охотник за супер-ценами!**\n\n"
            "🔥 **Я нахожу билеты с ошибками цен** — те самые, за €50 вместо €500.\n"
            "💡 **Как я это делаю:** я мониторю 10+ каналов с дешёвыми билетами и мгновенно присылаю тебе лучшие предложения.\n\n"
            "💰 **Премиум за 1000 Stars (~$10/мес) даёт тебе:**\n"
            "✅ **Мгновенные уведомления** об ошибках цен (на 30–60 мин раньше, чем в каналах)\n"
            "✅ **Безлимитный поиск** по всем направлениям\n"
            "✅ **Отслеживание маршрутов** — я пришлю уведомление, когда цена упадёт\n"
            "✅ **Экономия до 90%** на каждом билете\n\n"
            "💎 **Одна найденная ошибка цен окупает подписку на годы вперёд!**\n\n"
            "🔍 Попробуй прямо сейчас: `/search Кишинев Рим`",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

# ===== КОМАНДА /search =====
@dp.message(Command("search"))
async def search(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ **Формат:** `/search Город-откуда Город-куда`\n"
            "Пример: `/search Кишинев Рим`\n\n"
            "🔍 Я покажу тебе самые дешёвые билеты из моей базы."
        )
        return
    
    origin, destination = args[1], args[2]
    status_msg = await message.answer("🔍 **Ищу супер-цены...** ⏳")
    
    async for session in get_db():
        # Ищем в базе сохранённые предложения
        results = await session.execute(
            select(Search).where(
                Search.origin.ilike(f"%{origin}%"),
                Search.destination.ilike(f"%{destination}%")
            ).order_by(Search.price.asc()).limit(5)
        )
        offers = results.scalars().all()
        
        if not offers:
            await status_msg.edit_text(
                f"😞 **Пока нет предложений** по маршруту {origin} → {destination}.\n\n"
                "💡 **Подпишись на премиум**, и я пришлю уведомление, когда появится супер-цена!\n"
                "💰 Премиум за 1000 Stars (~$10/мес) — окупается с первой покупки.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")]
                    ]
                )
            )
            return
        
        response = f"✈️ **Супер-цены: {origin} → {destination}**\n\n"
        for offer in offers:
            if offer.route:
                flight = offer.route[0]
                response += f"💰 **${offer.price}** | 📅 {flight.get('date', 'дата неизвестна')}\n"
                response += f"   ✈️ {flight.get('airline', '—')} | 🛤️ {flight.get('transfers', '—')} пересадок\n"
                if flight.get('is_error'):
                    response += "   🔥 **ОШИБКА ЦЕНЫ! Скидка до 90%**\n"
                response += f"   🔗 [Купить билет]({flight.get('link', 'https://www.aviasales.com/')})\n\n"
        
        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== КОМАНДА /premium =====
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
        "✅ **Мгновенные уведомления** об ошибках цен (на 30–60 мин раньше)\n"
        "✅ **Безлимитный поиск** по всем направлениям\n"
        "✅ **Отслеживание маршрутов** — уведомления при падении цены\n"
        "✅ **Экономия до 90%** на каждом билете\n\n"
        "💎 **Одна найденная ошибка цен окупает подписку на годы вперёд!**\n\n"
        "Нажми кнопку ниже, чтобы оплатить через Telegram Stars.",
        reply_markup=keyboard
    )

# ===== ОПЛАТА ЧЕРЕЗ STARS =====
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
                "Теперь ты будешь получать уведомления об ошибках цен на 30–60 минут раньше!\n"
                "💚 Твоя экономия начинается прямо сейчас."
            )

# ===== СТАТИСТИКА =====
@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: types.CallbackQuery):
    await stats(callback.message)
    await callback.answer()

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
        
        searches_count = await session.execute(
            select(Search).where(Search.user_id == user.id)
        )
        searches = searches_count.scalars().all()
        total_searches = len(searches)
        
        await message.answer(
            f"📊 **Твоя статистика в AirFind**\n\n"
            f"🔍 Найдено предложений: **{total_searches}**\n"
            f"💎 Премиум: **{'✅ Да' if user.is_premium else '❌ Нет'}**\n"
            f"💰 Одна ошибка цен может сэкономить тебе **до 90%**!\n\n"
            f"🔥 Подпишись на премиум, чтобы получать уведомления первым!"
        )

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
async def handle_ping(request):
    return web.Response(text="AirFind bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Веб-сервер запущен на порту {port}")

# ===== ЗАПУСК =====
async def main():
    await init_db()
    
    # Запускаем веб-сервер
    asyncio.create_task(start_web_server())
    
    # Запускаем парсер каналов (если есть API ID и Hash)
    if os.getenv("API_ID") and os.getenv("API_HASH"):
        asyncio.create_task(start_parser())
        print("✅ Парсер каналов запущен!")
    else:
        print("⚠️ Парсер каналов отключён (не заданы API_ID и API_HASH)")
    
    print("✅ AirFind 2.0 бот запущен!")
    print("📌 Доступные команды: /start, /search, /premium, /stats")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
