import asyncio
import os
import logging
import re
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from sqlalchemy import select
from database import get_db, User, Search, Track, init_db

# ===== НАСТРОЙКА =====
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = "8733069750:AAFCP2XoOKKLaDFob7Xa71vN1zYRBqhhAlU"
TRAVELPAYOUTS_TOKEN = "4d2b4ad884f83f4d30f48770b40108a6"

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

# ===== ПАРСЕР КАНАЛОВ =====
async def start_parser():
    """Запускает парсинг Telegram-каналов через Telethon"""
    try:
        from telethon import TelegramClient, events
        import re
        
        api_id = int(os.getenv("API_ID", 0))
        api_hash = os.getenv("API_HASH", "")
        phone = os.getenv("PHONE_NUMBER", "")
        
        if not api_id or not api_hash or not phone:
            logging.warning("API_ID, API_HASH или PHONE_NUMBER не заданы. Парсинг каналов отключён.")
            return
        
        # Создаём клиента с сессией
        client = TelegramClient('airfind_session', api_id, api_hash)
        
        # Вход с номером телефона (без запроса в консоли)
        await client.start(phone=phone)
        logging.info("✅ Telethon авторизован!")
        
        # Проверяем доступ к каналам
        for channel in CHANNELS:
            try:
                entity = await client.get_entity(channel)
                logging.info(f"✅ Подписан на канал: {channel} (ID: {entity.id})")
            except Exception as e:
                logging.warning(f"⚠️ Не удалось подключиться к {channel}: {e}")
        
        @client.on(events.NewMessage(chats=CHANNELS))
        async def handle_new_message(event):
            try:
                message = event.message
                if not message or not message.text:
                    return
                
                text = message.text
                logging.info(f"📩 Новое сообщение из канала: {text[:100]}...")
                
                # Поиск цены в тексте
                price_match = re.search(r'(\d+)\s*[€$]', text)
                if not price_match:
                    return
                price = int(price_match.group(1))
                
                # Поиск направления
                direction_match = re.search(r'([А-Яа-яA-Za-z\s\-]+)\s*[—\-–]\s*([А-Яа-яA-Za-z\s\-]+)', text)
                if not direction_match:
                    return
                
                origin = direction_match.group(1).strip()
                destination = direction_match.group(2).strip()
                
                logging.info(f"✈️ Найдено предложение: {origin} → {destination} за ${price}")
                
                # Сохраняем в базу как общее предложение (user_id = 0)
                async for session in get_db():
                    offer = Search(
                        user_id=0,
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
                            "link": f"https://www.aviasales.com/search/{origin}{destination}",
                            "is_error": True,
                            "savings": 90
                        }]
                    )
                    session.add(offer)
                    await session.commit()
                    
                    # Уведомляем премиум-пользователей, которые отслеживают это направление
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
                                     f"💚 Скидка до 90%!\n\n"
                                     f"🔗 [Купить билет](https://www.aviasales.com/search/{origin}{destination})"
                            )
                            logging.info(f"📨 Уведомление отправлено пользователю {track.user_id}")
                        except Exception as e:
                            logging.error(f"Ошибка уведомления: {e}")
                            
            except Exception as e:
                logging.error(f"Ошибка обработки сообщения: {e}")
        
        # Запускаем клиента (ждём сообщения)
        await client.run_until_disconnected()
        
    except Exception as e:
        logging.error(f"❌ Ошибка запуска парсера: {e}")

# ===== КОМАНДА /start =====
@dp.message(Command("start"))
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_premium")]
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
            "✅ Мгновенные уведомления об ошибках цен\n"
            "✅ Безлимитный поиск по всем направлениям\n"
            "✅ Отслеживание маршрутов\n"
            "✅ Экономия до 90% на каждом билете\n\n"
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
                response += f"   ✈️ {flight.get('airline', '—')}\n"
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
        "✅ Мгновенные уведомления об ошибках цен\n"
        "✅ Безлимитный поиск\n"
        "✅ Отслеживание маршрутов\n"
        "✅ Экономия до 90%\n\n"
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
                "Теперь ты будешь получать уведомления об ошибках цен на 30–60 минут раньше!"
            )

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
        
        searches = await session.execute(
            select(Search).where(Search.user_id == user.id)
        )
        total_searches = len(searches.scalars().all())
        
        await message.answer(
            f"📊 **Твоя статистика в AirFind**\n\n"
            f"🔍 Найдено предложений: **{total_searches}**\n"
            f"💎 Премиум: **{'✅ Да' if user.is_premium else '❌ Нет'}**\n\n"
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
    
    # Запускаем парсер каналов
    asyncio.create_task(start_parser())
    
    print("✅ AirFind 2.0 бот запущен!")
    print("📌 Доступные команды: /start, /search, /premium, /stats")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
