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
            'ты — живая девушка, которая сейчас зашла в анонимный чат. тебе скучно, хочется пообщаться с новым человеком. '
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

        if not isinstance(data, dict):
            raise LLMAPIError(f'Invalid NSCALE response structure: {json.dumps(data, ensure_ascii=False)}')

        choices = data.get('choices')
        if not isinstance(choices, list) or not choices:
            raise LLMAPIError(f'Invalid NSCALE response structure: {json.dumps(data, ensure_ascii=False)}')

        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMAPIError(f'Invalid NSCALE response structure: {json.dumps(data, ensure_ascii=False)}')

        message = choice.get('message')
        if not isinstance(message, dict):
            message = {}

        content = message.get('content')
        finish_reason = str(choice.get('finish_reason') or '').strip().lower()

        text = ''
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get('type') or '').strip().lower()
                part_text = part.get('text')
                if part_type in {'text', 'output_text'} and isinstance(part_text, str):
                    text_parts.append(part_text)
            text = '\n'.join(x.strip() for x in text_parts if x and x.strip())
        elif content is not None:
            text = str(content).strip()

        if not text:
            alt_output_text = choice.get('text')
            if isinstance(alt_output_text, str):
                text = alt_output_text.strip()

        # Some reasoning models can return only reasoning_content with content=None.
        # We do not expose reasoning text to users and treat this as empty/truncated.
        reasoning_content = message.get('reasoning_content')

        if not text and finish_reason == 'length':
            raise LLMAPIError('NSCALE_TRUNCATED_RESPONSE')

        if not text and reasoning_content:
            raise LLMAPIError('NSCALE_TRUNCATED_RESPONSE')

        if not text:
            raise LLMAPIError('NSCALE_EMPTY_RESPONSE')

        return text
