        from telethon import TelegramClient, events
        api_id = int(os.getenv("API_ID", 0))
        api_hash = os.getenv("API_HASH", "")
        if not api_id or not api_hash:
            logging.warning("⚠️ Парсер каналов отключён (не заданы API_ID и API_HASH)")
            return

        client = TelegramClient('airfind_session', api_id, api_hash)
        await client.start()
        logging.info("✅ Telethon запущен, подключаюсь к каналам...")

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

                price_match = re.search(r'(\d+)\s*[€$]', text)
                if not price_match:
                    return
                price = int(price_match.group(1))

                direction_match = re.search(r'([А-Яа-яA-Za-z\s\-]+)\s*[—\-–]\s*([А-Яа-яA-Za-z\s\-]+)', text)
                if not direction_match:
                    return
                origin = direction_match.group(1).strip()
                destination = direction_match.group(2).strip()

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
                            "link": "https://www.aviasales.com/",
                            "is_error": True,
                            "savings": 90
                        }]
                    )
                    session.add(offer)
                    await session.commit()
                    logging.info(f"✅ Сохранено: {origin} → {destination} за ${price}")

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
    except Exception as e:
        logging.error(f"❌ Ошибка запуска парсера: {e}")

# ===== КОМАНДА /get_premium =====
@dp.message(Command("get_premium"))
async def get_premium(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.is_premium = True
            user.premium_until = datetime.now() + timedelta(days=365)
            await session.commit()
            await message.answer(
                "✅ **Премиум-доступ активирован на 365 дней!** 🎉\n\n"
                "Теперь ты можешь:\n"
                "• Использовать все функции бота\n"
                "• Получать уведомления об ошибках цен\n"
                "• Отслеживать маршруты\n\n"
                "🔥 Твоя экономия начинается прямо сейчас!"
            )
        else:
            await message.answer("❌ Пользователь не найден. Сначала используй `/start`.")

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
            "✅ **Мгновенные уведомления** об ошибках цен\n"
            "✅ **Безлимитный поиск**\n"
            "✅ **Отслеживание маршрутов**\n"
            "✅ **Экономия до 90%**\n\n"
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
            "Пример: `/search Кишинев Рим`"
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
                response += f"   ✈️ {flight.get('airline', '—')} | 🛤️ {flight.get('transfers', '—')} пересадок\n"
                if flight.get('is_error'):
                    response += "   🔥 **ОШИБКА ЦЕНЫ! Скидка до 90%**\n"
                response += f"   🔗 [Купить билет]({flight.get('link', 'https://www.aviasales.com/')})\n\n"
        await status_msg.edit_text(response, parse_mode="Markdown", disable_web_page_preview=True)

# ===== КОМАНДА /addoffer (ТОЛЬКО ДЛЯ АДМИНА) =====
@dp.message(Command("addoffer"))
async def add_offer(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    
    args = message.text.split(maxsplit=5)
    if len(args) < 6:
        await message.answer(
            "❌ **Формат:** `/addoffer Город-откуда Город-куда Цена Дата Ссылка`\n"
            "Пример: `/addoffer Кишинев Рим 50 2026-09-01 https://aviasales.com/...`"
        )
        return
    
    origin, destination, price, date, link = args[1], args[2], args[3], args[4], args[5]
    
    try:
        price = float(price)
    except ValueError:
        await message.answer("❌ Цена должна быть числом.")
        return
    
    async for session in get_db():
        offer = Search(
            user_id=0,
            origin=origin,
            destination=destination,
            date_from=datetime.strptime(date, "%Y-%m-%d"),
            price=price,
            currency="USD",
            route=[{
                "date": date,
                "price": price,
                "currency": "USD",
                "airline": "—",
                "transfers": "—",
                "link": link,
                "is_error": True,
                "savings": 90
            }]
        )
        session.add(offer)
        await session.commit()
        await message.answer(f"✅ Предложение добавлено: {origin} → {destination} за ${price}")

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
        "✅ **Мгновенные уведомления** об ошибках цен\n"
        "✅ **Безлимитный поиск**\n"
        "✅ **Отслеживание маршрутов**\n"
        "✅ **Экономия до 90%**\n\n"
        "Нажми кнопку ниже, чтобы оплатить через Telegram Stars.",
        reply_markup=keyboard
    )

# ===== ОПЛАТА =====
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
                "Теперь ты будешь получать уведомления об ошибках цен!\n"
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

# ===== КОМАНДА /track =====
@dp.message(Command("track"))
async def track(message: Message):
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer(
            "❌ **Формат:** `/track Город-откуда Город-куда Макс_цена`\n"
            "Пример: `/track Кишинев Рим 150`"
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

# ===== ВЕБ-СЕРВЕР =====
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
    asyncio.create_task(start_web_server())
    if os.getenv("API_ID") and os.getenv("API_HASH"):
        asyncio.create_task(start_parser())
        print("✅ Парсер каналов запущен!")
    else:
        print("⚠️ Парсер каналов отключён (не заданы API_ID и API_HASH)")
    print("✅ AirFind 2.0 бот запущен!")
    print("📌 Доступные команды: /start, /search, /premium, /stats, /track, /get_premium, /addoffer")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


                
