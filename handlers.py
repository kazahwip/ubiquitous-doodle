from __future__ import annotations

import asyncio
import random
import uuid
from pathlib import Path
from time import monotonic

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup

try:
    from .config import Settings
    from .llm import LLMAPIError, NScaleClient
    from .logger import ChannelLogger
    from .storage import InMemoryStorage, SessionData
except ImportError:
    from config import Settings
    from llm import LLMAPIError, NScaleClient
    from logger import ChannelLogger
    from storage import InMemoryStorage, SessionData


class ChatState(StatesGroup):
    in_dialog = State()


BTN_START = '🔥 Начать чат'
BTN_ABOUT = 'ℹ️ О боте'
BTN_SUPPORT = '🆘 Поддержка'
BTN_SUBSCRIPTION = '💎 Подписка'
BTN_REFERRAL = '🎁 Рефералы'
BTN_PAYMENT_SENT = '✅ Отправил деньги, проверьте'
BTN_BACK_MENU = '⬅️ В меню'
BTN_NEXT = '➡️ Следующий собеседник'
BTN_END = '❌ Завершить диалог'

DAILY_DIALOG_LIMIT = 3
SUBSCRIPTION_PRICE_RUB = 500
PAYMENT_REQUISITES = '2200701789834873'
PAYMENT_BANK = 'Т-банк'
def resolve_menu_image_path() -> Path | None:
    current_file = Path(__file__).resolve()
    candidates = [
        current_file.parent / 'image.png',  # flat layout: /app/handlers.py + /app/image.png
        current_file.parent.parent / 'image.png',  # package layout: /app/bot/handlers.py + /app/image.png
        Path.cwd() / 'image.png',  # runtime cwd fallback
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

WELCOME_TEXT = (
    '✨ <b>Анонимный чат</b>\n\n'
    'Нажми <b>🔥 Начать чат</b>, и я найду собеседника за пару секунд 😉\n\n'
    '<i>Приватно, легко и без регистрации.</i>'
)

ABOUT_TEXT = (
    'ℹ️ <b>О боте</b>\n\n'
    'Это анонимный чат, где можно свободно общаться и знакомиться в легкой атмосфере 💬\n\n'
    '• без регистрации\n'
    '• быстрый старт\n'
    '• приватный формат общения'
)

SUPPORT_TEXT = (
    '🆘 <b>Поддержка</b>\n\n'
    'Есть вопрос, баг или идея по улучшению?\n'
    'Напиши в Telegram: <a href="https://t.me/socialbleed">@socialbleed</a>\n\n'
    'Мы на связи и поможем 🤝'
)

SEARCHING_TEXT = '🔎 <b>Ищу собеседника...</b>'

DIALOG_FOUND_TEXT = (
    '💘 <b>Собеседник найден</b>\n'
    'Он уже онлайн 🔥\n\n'
    'Напиши первым сообщением и начнем 😉'
)

FALLBACK_TEXT = (
    '👋 Нажми <b>🔥 Начать чат</b>, и я подберу тебе собеседника прямо сейчас 💬'
)



def search_delay_seconds() -> float:
    return random.uniform(3.0, 6.0)


def typing_duration_seconds(reply_text: str) -> float:
    text_len = len((reply_text or '').strip())
    delay = 0.9 + (text_len * 0.035)
    return max(1.0, min(delay, 14.0))


async def send_typing_for(message: Message, seconds: float) -> None:
    end = monotonic() + seconds
    while True:
        left = end - monotonic()
        if left <= 0:
            return
        try:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        except Exception:
            return
        await asyncio.sleep(min(4.0, left))



def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_START)],
            [KeyboardButton(text=BTN_SUBSCRIPTION), KeyboardButton(text=BTN_REFERRAL)],
            [KeyboardButton(text=BTN_ABOUT), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )



def chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_NEXT), KeyboardButton(text=BTN_END)]],
        resize_keyboard=True,
    )



def subscription_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_PAYMENT_SENT)], [KeyboardButton(text=BTN_BACK_MENU)]],
        resize_keyboard=True,
    )


def limit_reached_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SUBSCRIPTION)], [KeyboardButton(text=BTN_BACK_MENU)]],
        resize_keyboard=True,
    )



def parse_referrer_id(start_text: str) -> int | None:
    parts = (start_text or '').split(maxsplit=1)
    if len(parts) < 2:
        return None

    payload = parts[1].strip()
    if payload.startswith('ref_'):
        raw_id = payload[4:]
    else:
        raw_id = payload

    if not raw_id.isdigit():
        return None
    return int(raw_id)



def user_status_text(storage: InMemoryStorage, user_id: int) -> str:
    referrals = storage.referral_count(user_id)
    has_sub = storage.has_subscription(user_id)
    used_dialogs = storage.dialog_starts_today(user_id)
    limit = storage.dialog_limit_for_user(user_id, base_limit=DAILY_DIALOG_LIMIT)

    if has_sub:
        limit_text = 'безлимит'
    else:
        limit_text = f'{used_dialogs}/{limit}'

    return (
        '<b>Твой статус</b>\n'
        f'• Подписка: {"активна ✅" if has_sub else "не активна ❌"}\n'
        f'• Лимит диалогов сегодня: {limit_text}\n'
        f'• Приглашено рефералов: {referrals}\n'
        f'• Бонус к лимиту: +{referrals}'
    )



def subscription_text(storage: InMemoryStorage, user_id: int) -> str:
    status = user_status_text(storage, user_id)
    return (
        '💎 <b>Подписка</b>\n\n'
        f'Цена: <b>{SUBSCRIPTION_PRICE_RUB} ₽</b>\n'
        '<b>Реквизиты для оплаты:</b>\n'
        f'• Карта: <code>{PAYMENT_REQUISITES}</code>\n'
        f'• Банк: {PAYMENT_BANK}\n\n'
        'С подпиской лимит диалогов <b>без ограничений</b>.\n\n'
        'Чтобы купить: переведи 500 ₽ и нажми кнопку ниже. '
        'Бот автоматически проверит оплату и активирует подписку.\n\n'
        f'{status}'
    )



def referral_text(storage: InMemoryStorage, user_id: int, bot_username: str | None) -> str:
    referrals = storage.referral_count(user_id)
    limit = storage.dialog_limit_for_user(user_id, base_limit=DAILY_DIALOG_LIMIT)

    if bot_username:
        link = f'https://t.me/{bot_username}?start=ref_{user_id}'
        link_text = f'<code>{link}</code>'
    else:
        link_text = 'Ссылка временно недоступна. Повтори попытку позже.'

    return (
        '🎁 <b>Реферальная система</b>\n\n'
        'За каждого приглашенного пользователя ты получаешь +1 диалог в день.\n'
        f'Уже приглашено: <b>{referrals}</b>\n'
        f'Текущий лимит без подписки: <b>{limit}</b> диалогов/день\n\n'
        'Твоя реферальная ссылка:\n'
        f'{link_text}'
    )



def user_router(
    settings: Settings,
    storage: InMemoryStorage,
    llm: NScaleClient,
    channel_logger: ChannelLogger,
) -> Router:
    router = Router(name='user')

    async def send_menu_screen(message: Message, text: str) -> None:
        menu_image_path = resolve_menu_image_path()
        if menu_image_path is not None:
            try:
                await message.answer_photo(
                    photo=FSInputFile(menu_image_path),
                    caption=text,
                    reply_markup=main_menu_keyboard(),
                )
                return
            except Exception:
                pass
        await message.answer(text, reply_markup=main_menu_keyboard())

    async def start_dialog(message: Message, state: FSMContext) -> None:
        user_id = message.from_user.id
        allowed, used, limit = storage.can_start_dialog(user_id, base_limit=DAILY_DIALOG_LIMIT)
        if not allowed:
            await state.clear()
            await message.answer(
                (
                    '⛔️ Лимит диалогов на сегодня исчерпан.\n'
                    f'Сегодня: {used}/{limit}.\n\n'
                    f'Оформи подписку за {SUBSCRIPTION_PRICE_RUB} ₽, чтобы снять ограничение.'
                ),
                reply_markup=limit_reached_keyboard(),
            )
            return

        session = storage.get_session(user_id)
        if session:
            session.active = False
            await channel_logger.dialog_finished(user_id, session.session_id, session.messages_count)

        new_session = SessionData(session_id=str(uuid.uuid4()), user_id=user_id)
        storage.set_session(user_id, new_session)
        storage.track_dialog_start(user_id)
        await state.set_state(ChatState.in_dialog)

        await channel_logger.dialog_started(user_id, new_session.session_id)
        await message.answer(SEARCHING_TEXT)
        await asyncio.sleep(search_delay_seconds())
        await message.answer(DIALOG_FOUND_TEXT, reply_markup=chat_keyboard())

    async def ensure_chat_session(message: Message, state: FSMContext) -> SessionData | None:
        session = storage.get_session(message.from_user.id)
        if session:
            return session
        await state.clear()
        await message.answer('Сессия завершена. Нажми <b>🔥 Начать чат</b>, чтобы открыть новую.')
        return None

    async def check_message_rate_limit(message: Message) -> bool:
        user_id = message.from_user.id
        if storage.is_rate_limited(
            user_id,
            limit=settings.rate_limit_messages,
            period_seconds=settings.rate_limit_period,
        ):
            await message.answer('⏳ Слишком быстро 😉 Подожди пару секунд и продолжим.')
            return False
        return True

    async def ask_llm_and_reply(
        message: Message,
        session: SessionData,
        user_content: str,
    ) -> None:
        user_id = message.from_user.id
        session.history.append({'role': 'user', 'content': user_content})

        try:
            reply = await llm.generate_reply(session.history)
        except LLMAPIError as exc:
            await channel_logger.api_error(user_id, str(exc))
            if str(exc) == 'NSCALE_RATE_LIMIT':
                await message.answer('⚠️ Сервис временно перегружен. Попробуй еще раз через минуту.')
                return
            if str(exc) == 'NSCALE_MODEL_NOT_FOUND':
                await message.answer('⚙️ Модель сейчас недоступна. Проверь NSCALE_MODEL в .env.')
                return
            if str(exc) == 'NSCALE_AUTH_ERROR':
                await message.answer('🔑 Проблема с ключом NSCALE. Проверь NSCALE_SERVICE_TOKEN в .env.')
                return
            if str(exc) == 'NSCALE_TIMEOUT':
                await message.answer('⌛ NSCALE отвечает слишком долго. Попробуй еще раз через пару секунд.')
                return
            if str(exc) == 'PROXY_SOCKS_NOT_SUPPORTED_INSTALL_AIOHTTP_SOCKS':
                await message.answer('🧩 Нужен пакет aiohttp-socks для SOCKS5. Установи зависимости и перезапусти бота.')
                return
            await message.answer('💤 Собеседник немного занят. Давай попробуем еще раз через пару секунд.')
            return

        await send_typing_for(message, typing_duration_seconds(reply))

        session.history.append({'role': 'assistant', 'content': reply})
        storage.increment_messages(user_id)

        if len(session.history) > 30:
            session.history = session.history[-30:]

        await message.answer(reply)

    @router.message(CommandStart())
    async def command_start(message: Message, state: FSMContext) -> None:
        user = message.from_user
        storage.register_user(user.id, user.username)
        storage.track_start()
        await state.clear()

        referrer_id = parse_referrer_id(message.text or '')
        if referrer_id is not None and storage.add_referral(referrer_id, user.id):
            await channel_logger.referral_registered(referrer_id, user.id, user.username)

        await channel_logger.startup(user.id, user.username)
        await send_menu_screen(message, WELCOME_TEXT)

    @router.message(F.text == BTN_START)
    async def menu_start_dialog(message: Message, state: FSMContext) -> None:
        storage.register_user(message.from_user.id, message.from_user.username)
        await start_dialog(message, state)

    @router.message(F.text == BTN_SUBSCRIPTION)
    async def subscription_info(message: Message) -> None:
        storage.register_user(message.from_user.id, message.from_user.username)
        await message.answer(
            subscription_text(storage, message.from_user.id),
            reply_markup=subscription_keyboard(),
        )

    @router.message(F.text == BTN_PAYMENT_SENT)
    async def payment_sent(message: Message) -> None:
        storage.register_user(message.from_user.id, message.from_user.username)
        storage.track_payment_request(message.from_user.id)
        await channel_logger.payment_request(message.from_user.id, message.from_user.username)
        await send_menu_screen(
            message,
            '✅ Платеж отправлен на автоматическую проверку. После подтверждения подписка активируется.',
        )

    @router.message(F.text == BTN_REFERRAL)
    async def referral_info(message: Message) -> None:
        storage.register_user(message.from_user.id, message.from_user.username)
        bot_info = await message.bot.get_me()
        await message.answer(
            referral_text(storage, message.from_user.id, bot_info.username),
            reply_markup=main_menu_keyboard(),
        )

    @router.message(F.text == BTN_BACK_MENU)
    async def back_to_menu(message: Message, state: FSMContext) -> None:
        await state.clear()
        await send_menu_screen(message, 'Возвращаю в меню.')

    @router.message(F.text == BTN_ABOUT)
    async def about(message: Message) -> None:
        await message.answer(ABOUT_TEXT)

    @router.message(F.text == BTN_SUPPORT)
    async def support(message: Message) -> None:
        await message.answer(SUPPORT_TEXT, disable_web_page_preview=True)

    @router.message(F.text == BTN_END)
    async def end_dialog(message: Message, state: FSMContext) -> None:
        session = storage.clear_session(message.from_user.id)
        await state.clear()

        if session:
            session.active = False
            await channel_logger.dialog_finished(
                message.from_user.id,
                session.session_id,
                session.messages_count,
            )

        await send_menu_screen(message, '❌ <b>Диалог завершен</b>\n\nВозвращаю тебя в меню ✨')

    @router.message(F.text == BTN_NEXT)
    async def next_dialog(message: Message, state: FSMContext) -> None:
        old_session = storage.clear_session(message.from_user.id)
        if old_session:
            old_session.active = False
            await channel_logger.dialog_finished(
                message.from_user.id,
                old_session.session_id,
                old_session.messages_count,
            )

        await start_dialog(message, state)

    @router.message(ChatState.in_dialog, F.text)
    async def chat_message(message: Message, state: FSMContext) -> None:
        user_id = message.from_user.id
        storage.register_user(user_id, message.from_user.username)

        if not await check_message_rate_limit(message):
            return

        session = await ensure_chat_session(message, state)
        if not session:
            return

        await ask_llm_and_reply(message, session, message.text)

    @router.message()
    async def fallback(message: Message) -> None:
        await send_menu_screen(message, FALLBACK_TEXT)

    return router
