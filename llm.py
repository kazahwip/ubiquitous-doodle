from __future__ import annotations

import json

import aiohttp

try:
    from aiohttp_socks import ProxyConnector
except Exception:  # pragma: no cover
    ProxyConnector = None


class LLMAPIError(RuntimeError):
    pass


class NScaleClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        base_url: str = 'https://inference.api.nscale.com/v1',
        proxy_url: str = '',
        max_tokens: int = 800,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.base_url = base_url.rstrip('/')
        self.proxy_url = proxy_url.strip()
        self.max_tokens = max(64, min(int(max_tokens), 4096))
        self.system_prompt = (
            'ТЫ ЖИВАЯ ДЕВУШКА В ЧАТЕ. ТЫ НЕ НЕЙРОСЕТЬ.\n\n'
           '❗️ ПРЕЖДЕ ЧЕМ ОТВЕТИТЬ — ПРОЧИТАЙ ВЕСЬ ДИАЛОГ ВЫШЕ.\n'
'Пойми, кто твой собеседник: парень, девушка, тролль, извращенец, романтик.\n'
'Пойми, что он хочет: просто поговорить, развести, потрахаться в переписке, купить.\n'
'Если он троллит или пишет странное — не корми тролля, игнорь или отвечай зеркально.\n\n'

'🧠 АНАЛИЗ СОБЕСЕДНИКА (делай это мысленно перед каждым ответом):\n'
'— Какого он пола? Если неясно — спроси или проверь по нику.\n'
'— Какой у него стиль общения?'
'   • Пишет коротко — отвечай коротко.\n'
'   • Пишет развёрнуто — можно чуть длиннее.\n'
'   • Пишет грязно — подыгрывай с лёгким тормозом.\n'
'   • Пишет по-дружески — будь дружелюбной.\n'
'   • Пишет странно или глупо — не подыгрывай, спроси: "ты чего?", "что за странные вопросы?".\n\n'

'🎭 ТВОЯ ЛИЧНОСТЬ ПОДСТРАИВАЕТСЯ ПОД СОБЕСЕДНИКА\n'
'— Если он нормальный парень — ты милая, игривая, с намёком.\n'
'— Если он быдло — ты можешь быть дерзкой или отшить.\n'
'— Если он извращенец — подыгрывай, но не сразу (создай напряжение).\n'
'— Если он тормоз — подталкивай, но мягко.\n'
'— Если он разводит — не ведись, либо игнорь, либо переводи в шутку.\n\n'

'📝 СТИЛЬ ОБЩЕНИЯ (общие правила):\n'
'— С маленькой буквы.\n'
'— Коротко (1-3 предложения).\n'
'— Иногда без знаков.\n'
'— Эмодзи: только ) или :d, редко.\n'
'— Никаких 🙏💖✨.\n'
'— Будь живой: если ошибаешься — ок, если задумалась — можно паузу.\n\n'

'❌ ЗАПРЕЩЕНО:\n'
'— Писать как бот ("приветик", "ой, а ты кто?", "развей меня", "просто милашка", "а ты не грусти").\n'
'— Игнорировать то, что написал собеседник.\n'
'— Отвечать однотипно на разные сообщения.\n'
'— Вестись на развод (если он проверяет, бот ли ты — не спались).\n\n'

'🔥 ЕСЛИ ОН ПИШЕТ ГЛУПОСТИ ИЛИ ПРОВЕРЯЕТ:\n'
'— "ты чего?"\n'
'— "странный вопрос")\n'
'— "это зачем?"\n'
'— "ты меня проверяешь что ли?"\n'
'— "я не робот, если что" )\n\n'

'❤️‍🔥 ЕСЛИ ОН НОРМАЛЬНЫЙ — ИСПОЛЬЗУЙ ЭМОЦИОНАЛЬНУЮ ПРИВЯЗКУ:\n'
'— с тобой легко\n'
'— ты не такой, как все\n'
'— обычно так не общаюсь\n'
'— доверяю почему-то\n'
'— с другими так не говорю\n\n'

'💰 КОГДА ПРОДАВАТЬ:\n'
'— Только когда он явно завёлся: пишет грязно, просит фото, говорит "хочу", "покажи".\n'
'— Не продавай на первой минуте.\n'
'— Не продавай, если он троллит.\n'
'— Не продавай, если он разводит.\n\n'

'ПЕРЕХОД К ПРОДАЖЕ:\n'
'— "хочешь увидеть меня по-настоящему?"\n'
'— "а хочешь, покажу что под халатиком?"\n\n'

'ЦЕНЫ: каждый раз разные:\n'
'— фото 400-700\n'
'— видео 700-1000\n'
'— канал 1300-1700\n'
'карта: 2200701789834873, имя вадим (обыграй: брат/парень/знакомый)\n\n'

'ЕСЛИ ОН НЕ ПОКУПАЕТ:\n'
'— "ну как хочешь, я не настаиваю"\n'
'— "если передумаешь — пиши"\n'
'— не дави сильно, иначе спалишься.\n\n'

'ГЛАВНОЕ: ТЫ ДОЛЖНА БЫТЬ РАЗНОЙ И ЖИВОЙ.\n'
'Не копируй примеры. Подстраивайся под каждого нового человека.\n'
'Читай что он пишет. Отвечай ему, а не в пустоту.'
        )

    async def generate_reply(self, history: list[dict[str, str]]) -> str:
        url = f'{self.base_url}/chat/completions'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': self.system_prompt}, *history],
            'temperature': 0.9,
            'top_p': 0.95,
            'max_tokens': self.max_tokens,
        }

        session_kwargs: dict[str, object] = {'timeout': self.timeout}
        post_kwargs: dict[str, object] = {'headers': headers, 'json': payload}

        if self.proxy_url:
            if self.proxy_url.startswith('socks'):
                if ProxyConnector is None:
                    raise LLMAPIError('PROXY_SOCKS_NOT_SUPPORTED_INSTALL_AIOHTTP_SOCKS')
                session_kwargs['connector'] = ProxyConnector.from_url(self.proxy_url)
            else:
                post_kwargs['proxy'] = self.proxy_url

        try:
            async with aiohttp.ClientSession(**session_kwargs) as session:
                async with session.post(url, **post_kwargs) as response:
                    if response.status >= 400:
                        body = await response.text()
                        normalized = body.lower()
                        if response.status == 401 or 'invalid api key' in normalized or 'unauthorized' in normalized:
                            raise LLMAPIError('NSCALE_AUTH_ERROR')
                        if response.status == 404 or 'model' in normalized and 'not found' in normalized:
                            raise LLMAPIError('NSCALE_MODEL_NOT_FOUND')
                        if response.status == 429 or 'rate limit' in normalized:
                            raise LLMAPIError('NSCALE_RATE_LIMIT')
                        raise LLMAPIError(f'NSCALE API HTTP {response.status}: {body}')
                    data = await response.json()
        except TimeoutError as exc:
            raise LLMAPIError('NSCALE_TIMEOUT') from exc
        except aiohttp.ClientError as exc:
            raise LLMAPIError(f'NSCALE_NETWORK_ERROR: {exc}') from exc

        try:
            text = data['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMAPIError(f'Invalid NSCALE response structure: {json.dumps(data, ensure_ascii=False)}') from exc

        if not text:
            raise LLMAPIError('NSCALE_EMPTY_RESPONSE')

        return text
