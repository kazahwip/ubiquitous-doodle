from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional


UTC = timezone.utc


@dataclass(slots=True)
class SessionData:
    session_id: str
    user_id: int
    history: List[dict[str, str]] = field(default_factory=list)
    messages_count: int = 0
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryStorage:
    def __init__(self, state_file: str = 'bot_state.json') -> None:
        self._users: set[int] = set()
        self._sessions: Dict[int, SessionData] = {}
        self._message_events: Deque[datetime] = deque()
        self._start_events: Deque[datetime] = deque()
        self._rate_limit_events: Dict[int, Deque[datetime]] = defaultdict(deque)
        self._known_usernames: Dict[str, int] = {}
        self._subscriptions: set[int] = set()
        self._dialog_starts_by_day: Dict[str, Dict[int, int]] = {}
        self._referrer_by_user: Dict[int, int] = {}
        self._referral_counts: Dict[int, int] = defaultdict(int)
        self._payment_requests: Deque[datetime] = deque()
        self._subscriptions_granted_events: Deque[datetime] = deque()
        self._payment_requests_total: int = 0
        self._subscriptions_granted_total: int = 0
        self._state_path = Path(state_file)
        self._load_state()

    def register_user(self, user_id: int, username: str | None = None) -> None:
        self._users.add(user_id)
        normalized = self._normalize_username(username)
        if normalized:
            self._known_usernames[normalized] = user_id
        self._save_state()

    def all_user_ids(self) -> list[int]:
        return list(self._users)

    def resolve_user(self, user_or_name: str) -> Optional[int]:
        value = (user_or_name or '').strip()
        if not value:
            return None
        if value.startswith('@'):
            value = value[1:]
        if value.isdigit():
            return int(value)
        return self._known_usernames.get(value.casefold())

    def track_start(self) -> None:
        self._start_events.append(datetime.now(UTC))
        self._trim_old(self._start_events, timedelta(hours=24))
        self._save_state()

    def track_dialog_start(self, user_id: int) -> None:
        day_key = self._today_key()
        bucket = self._dialog_starts_by_day.setdefault(day_key, {})
        bucket[user_id] = bucket.get(user_id, 0) + 1
        self._drop_old_dialog_days()
        self._save_state()

    def dialog_starts_today(self, user_id: int) -> int:
        return self._dialog_starts_by_day.get(self._today_key(), {}).get(user_id, 0)

    def dialog_limit_for_user(self, user_id: int, base_limit: int = 3) -> Optional[int]:
        if self.has_subscription(user_id):
            return None
        return base_limit + self.referral_count(user_id)

    def can_start_dialog(self, user_id: int, base_limit: int = 3) -> tuple[bool, int, Optional[int]]:
        used = self.dialog_starts_today(user_id)
        limit = self.dialog_limit_for_user(user_id, base_limit=base_limit)
        if limit is None:
            return True, used, None
        return used < limit, used, limit

    def has_subscription(self, user_id: int) -> bool:
        return user_id in self._subscriptions

    def grant_subscription(self, user_id: int) -> bool:
        already_had = user_id in self._subscriptions
        self._subscriptions.add(user_id)
        self._subscriptions_granted_events.append(datetime.now(UTC))
        self._subscriptions_granted_total += 1
        self._trim_old(self._subscriptions_granted_events, timedelta(hours=24))
        self._save_state()
        return not already_had

    def subscription_users_count(self) -> int:
        return len(self._subscriptions)

    def track_payment_request(self, user_id: int) -> None:
        self._users.add(user_id)
        self._payment_requests.append(datetime.now(UTC))
        self._payment_requests_total += 1
        self._trim_old(self._payment_requests, timedelta(hours=24))
        self._save_state()

    def payment_requests_24h(self) -> int:
        self._trim_old(self._payment_requests, timedelta(hours=24))
        return len(self._payment_requests)

    def add_referral(self, inviter_id: int, invited_user_id: int) -> bool:
        if inviter_id == invited_user_id:
            return False
        if invited_user_id in self._referrer_by_user:
            return False
        self._referrer_by_user[invited_user_id] = inviter_id
        self._referral_counts[inviter_id] += 1
        self._save_state()
        return True

    def referral_count(self, user_id: int) -> int:
        return self._referral_counts.get(user_id, 0)

    def set_session(self, user_id: int, session: SessionData) -> None:
        self._sessions[user_id] = session

    def get_session(self, user_id: int) -> Optional[SessionData]:
        return self._sessions.get(user_id)

    def clear_session(self, user_id: int) -> Optional[SessionData]:
        return self._sessions.pop(user_id, None)

    def increment_messages(self, user_id: int) -> None:
        session = self._sessions.get(user_id)
        if not session:
            return
        session.messages_count += 1
        self._message_events.append(datetime.now(UTC))
        self._trim_old(self._message_events, timedelta(hours=24))
        self._save_state()

    def is_rate_limited(self, user_id: int, limit: int, period_seconds: int) -> bool:
        now = datetime.now(UTC)
        bucket = self._rate_limit_events[user_id]
        period = timedelta(seconds=period_seconds)

        while bucket and now - bucket[0] > period:
            bucket.popleft()

        if len(bucket) >= limit:
            return True

        bucket.append(now)
        return False

    def stats(self) -> dict[str, int]:
        self._trim_old(self._message_events, timedelta(hours=24))
        self._trim_old(self._start_events, timedelta(hours=24))
        self._trim_old(self._payment_requests, timedelta(hours=24))
        self._trim_old(self._subscriptions_granted_events, timedelta(hours=24))

        active_dialogs = sum(1 for session in self._sessions.values() if session.active)
        return {
            'total_users': len(self._users),
            'active_dialogs': active_dialogs,
            'messages_24h': len(self._message_events),
            'starts_24h': len(self._start_events),
            'payment_requests_24h': len(self._payment_requests),
            'subscriptions_granted_24h': len(self._subscriptions_granted_events),
            'payment_requests_total': self._payment_requests_total,
            'subscriptions_granted_total': self._subscriptions_granted_total,
            'paid_users_total': len(self._subscriptions),
            'referrals_total': sum(self._referral_counts.values()),
        }

    @staticmethod
    def _trim_old(bucket: Deque[datetime], ttl: timedelta) -> None:
        now = datetime.now(UTC)
        while bucket and now - bucket[0] > ttl:
            bucket.popleft()

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding='utf-8'))
            users = raw.get('users', [])
            messages = raw.get('message_events', [])
            starts = raw.get('start_events', [])
            known_usernames = raw.get('known_usernames', {})
            subscriptions = raw.get('subscriptions', [])
            dialog_starts_by_day = raw.get('dialog_starts_by_day', {})
            referrer_by_user = raw.get('referrer_by_user', {})
            referral_counts = raw.get('referral_counts', {})
            payment_requests = raw.get('payment_requests', [])
            subscriptions_granted_events = raw.get('subscriptions_granted_events', [])
            payment_requests_total = raw.get('payment_requests_total', len(payment_requests))
            subscriptions_granted_total = raw.get(
                'subscriptions_granted_total',
                len(subscriptions_granted_events),
            )

            self._users = {int(u) for u in users}
            self._message_events = deque(self._parse_dt(x) for x in messages if self._parse_dt(x) is not None)
            self._start_events = deque(self._parse_dt(x) for x in starts if self._parse_dt(x) is not None)
            self._known_usernames = {
                str(k).casefold(): int(v)
                for k, v in known_usernames.items()
                if str(v).isdigit()
            }
            self._subscriptions = {int(x) for x in subscriptions}
            self._dialog_starts_by_day = {
                str(day): {int(uid): int(count) for uid, count in per_user.items()}
                for day, per_user in dialog_starts_by_day.items()
                if isinstance(per_user, dict)
            }
            self._drop_old_dialog_days()
            self._referrer_by_user = {int(k): int(v) for k, v in referrer_by_user.items()}
            self._referral_counts = defaultdict(
                int,
                {int(k): int(v) for k, v in referral_counts.items()},
            )
            self._payment_requests = deque(
                self._parse_dt(x) for x in payment_requests if self._parse_dt(x) is not None
            )
            self._subscriptions_granted_events = deque(
                self._parse_dt(x)
                for x in subscriptions_granted_events
                if self._parse_dt(x) is not None
            )
            self._payment_requests_total = int(payment_requests_total)
            self._subscriptions_granted_total = int(subscriptions_granted_total)
        except Exception:
            self._users = set()
            self._message_events = deque()
            self._start_events = deque()
            self._known_usernames = {}
            self._subscriptions = set()
            self._dialog_starts_by_day = {}
            self._referrer_by_user = {}
            self._referral_counts = defaultdict(int)
            self._payment_requests = deque()
            self._subscriptions_granted_events = deque()
            self._payment_requests_total = 0
            self._subscriptions_granted_total = 0

    def _save_state(self) -> None:
        try:
            payload = {
                'users': sorted(self._users),
                'message_events': [x.isoformat() for x in self._message_events],
                'start_events': [x.isoformat() for x in self._start_events],
                'known_usernames': self._known_usernames,
                'subscriptions': sorted(self._subscriptions),
                'dialog_starts_by_day': {
                    day: {str(uid): count for uid, count in per_user.items()}
                    for day, per_user in self._dialog_starts_by_day.items()
                },
                'referrer_by_user': {str(k): v for k, v in self._referrer_by_user.items()},
                'referral_counts': {str(k): v for k, v in self._referral_counts.items()},
                'payment_requests': [x.isoformat() for x in self._payment_requests],
                'subscriptions_granted_events': [
                    x.isoformat() for x in self._subscriptions_granted_events
                ],
                'payment_requests_total': self._payment_requests_total,
                'subscriptions_granted_total': self._subscriptions_granted_total,
            }
            self._state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    @staticmethod
    def _parse_dt(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            return None

    @staticmethod
    def _normalize_username(username: str | None) -> str:
        if not username:
            return ''
        return username.strip().removeprefix('@').casefold()

    @staticmethod
    def _today_key() -> str:
        return datetime.now(UTC).date().isoformat()

    def _drop_old_dialog_days(self, keep_days: int = 14) -> None:
        cutoff = datetime.now(UTC).date() - timedelta(days=keep_days)
        fresh: Dict[str, Dict[int, int]] = {}
        for key, value in self._dialog_starts_by_day.items():
            try:
                day = date.fromisoformat(key)
            except ValueError:
                continue
            if day >= cutoff:
                fresh[key] = value
        self._dialog_starts_by_day = fresh
