"""Model calls through any OpenAI-compatible API. Reasoning is switched off via extra_body from
models.toml; network and rate-limit errors are retried with backoff."""
import random
import sys
import time

import openai

from . import usage

TRANSIENT = (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
             openai.InternalServerError)
MAX_ATTEMPTS = 6


class LLMError(Exception):
    pass


def _retry_after(e):
    resp = getattr(e, "response", None)
    value = resp.headers.get("retry-after") if resp is not None else None
    return int(value) if value and str(value).isdigit() else 0


class Client:
    def __init__(self, model_cfg, log, temperature=0.3, max_tokens=8000):
        if not model_cfg.get("api_key"):
            raise LLMError(f"{model_cfg['key_env']} is not set: add {model_cfg['key_env']}=... to "
                           "~/.config/glossbook/.env or ./.env (`glossbook init` writes a template)")
        self.cfg = model_cfg
        self.api = openai.OpenAI(api_key=model_cfg["api_key"], base_url=model_cfg["base_url"], max_retries=0,
                                 timeout=model_cfg.get("timeout", 180))
        self.log = log
        self.temperature = temperature
        self.max_tokens = max_tokens

    def params(self):
        """Sampling parameters. models.toml can rename or drop them per model: reasoning models such as
        gpt-5 accept only the default temperature and want max_completion_tokens
        (`temperature = false`, `max_tokens_param = "max_completion_tokens"`)."""
        p = {}
        temperature = self.cfg.get("temperature", self.temperature)
        if temperature is not False:
            p["temperature"] = temperature
        p[self.cfg.get("max_tokens_param", "max_tokens")] = self.max_tokens
        return p

    def chat(self, messages, kind="seg", chapter=None, retry=False):
        for attempt in range(MAX_ATTEMPTS):
            try:
                r = self.api.chat.completions.create(
                    model=self.cfg["model"], messages=messages, **self.params(),
                    extra_body=self.cfg.get("extra_body") or None)
                break
            except TRANSIENT as e:
                if attempt == MAX_ATTEMPTS - 1:
                    raise LLMError(f"still failing after {MAX_ATTEMPTS} attempts: {e}") from e
                wait = max(min(60, 2 ** attempt * 2) + random.random(), _retry_after(e))
                print(f"  {type(e).__name__}, retrying in {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
            except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
                raise LLMError(f"API key rejected ({self.cfg['key_env']}): {e}") from e
            except openai.BadRequestError as e:
                raise LLMError(f"request rejected; check model / extra_body of {self.cfg['name']!r} "
                               f"in models.toml: {e}") from e
            except openai.APIStatusError as e:
                if e.status_code == 402:
                    raise LLMError(f"insufficient balance on the {self.cfg['name']!r} account ({e.status_code}); "
                                   "top up and run again (finished chunks are cached)") from e
                raise LLMError(f"API error {e.status_code} from {self.cfg['base_url']}: {e}") from e
            except openai.APIError as e:
                raise LLMError(f"API error from {self.cfg['base_url']}: {e}") from e
        self.log.add(self.cfg["name"], kind, chapter, usage.from_response(r), retry)
        choice = r.choices[0]
        if choice.finish_reason == "length":
            print("  warning: output hit max_tokens; missing segments will be retried", file=sys.stderr)
        return choice.message.content or ""
