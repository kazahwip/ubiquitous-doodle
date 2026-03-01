from __future__ import annotations

from html import escape
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest


logger = logging.getLogger(__name__)
UTC = timezone.utc


class ChannelLogger:
    def __init__(self, bot: Bot, channel_id: int) -> None:
        self.bot = bot
        self.channel_id = channel_id

    async def startup(self, user_id: int, username: str | None) -> None:
        text = (
            '🟢 Новый запуск\n'
            f'👤 ID: {user_id}\n'
            f'🪪 Username: @{username if username else "—"}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def dialog_started(self, user_id: int, session_id: str) -> None:
        text = (
            '💬 Начат диалог\n'
            f'👤 ID: {user_id}\n'
            f'🆔 Сессия: {session_id}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def dialog_finished(self, user_id: int, session_id: str, messages_count: int) -> None:
        text = (
            '🔴 Диалог завершен\n'
            f'👤 ID: {user_id}\n'
            f'🆔 Сессия: {session_id}\n'
            f'🔥 Сообщений: {messages_count}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def api_error(self, user_id: int, error: str) -> None:
        text = (
            '⚠️ Ошибка API\n'
            f'👤 ID: {user_id}\n'
            f'❗ Детали: {error[:500]}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def payment_request(self, user_id: int, username: str | None) -> None:
        text = (
            '💳 Заявка на проверку оплаты\n'
            f'👤 ID: {user_id}\n'
            f'🪪 Username: @{username if username else "—"}\n'
            '💰 Тариф: 500 RUB\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def subscription_granted(
        self,
        admin_id: int,
        target_id: int,
        target_username: str | None = None,
    ) -> None:
        text = (
            '✅ Подписка выдана\n'
            f'🛡️ Админ ID: {admin_id}\n'
            f'👤 Пользователь ID: {target_id}\n'
            f'🪪 Username: @{target_username if target_username else "—"}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def referral_registered(
        self,
        inviter_id: int,
        invited_id: int,
        invited_username: str | None = None,
    ) -> None:
        text = (
            '🎁 Новый реферал\n'
            f'👤 Инвайтер ID: {inviter_id}\n'
            f'👥 Приглашенный ID: {invited_id}\n'
            f'🪪 Username приглашенного: @{invited_username if invited_username else "—"}\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(text)

    async def chat_user_message(
        self,
        user_id: int,
        username: str | None,
        session_id: str,
        text: str,
    ) -> None:
        safe_text = self._safe_text(text)
        payload = (
            '🗨️ Сообщение пользователя\n'
            f'👤 ID: {user_id}\n'
            f'🪪 Username: @{username if username else "—"}\n'
            f'🆔 Сессия: {session_id}\n'
            f'💬 Текст:\n<pre>{safe_text}</pre>\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(payload)

    async def chat_assistant_message(
        self,
        user_id: int,
        username: str | None,
        session_id: str,
        text: str,
    ) -> None:
        safe_text = self._safe_text(text)
        payload = (
            '🤖 Ответ нейросети\n'
            f'👤 ID: {user_id}\n'
            f'🪪 Username: @{username if username else "—"}\n'
            f'🆔 Сессия: {session_id}\n'
            f'💬 Текст:\n<pre>{safe_text}</pre>\n'
            f'📅 Время: {self._now()}'
        )
        await self._send(payload)

    async def _send(self, text: str) -> None:
        if not self.channel_id:
            return
        try:
            await self.bot.send_message(self.channel_id, text)
        except TelegramBadRequest as exc:
            logger.warning('Failed to send log to channel: %s', exc)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')

    @staticmethod
    def _safe_text(text: str, limit: int = 3000) -> str:
        normalized = (text or '').strip() or '—'
        if len(normalized) > limit:
            normalized = f'{normalized[:limit]}… [truncated]'
        return escape(normalized)
