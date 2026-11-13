"""Provider-independent LLM access for live and hash-checked replay runs."""
import hashlib
import json
import math
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", os.environ.get("ACADZA_PROVIDER", "groq")).strip().lower()
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "groq": "openai/gpt-oss-120b"}
MODEL = os.environ.get(
    "GROQ_MODEL" if PROVIDER == "groq" else "ANTHROPIC_MODEL",
    os.environ.get("ACADZA_MODEL", DEFAULT_MODELS.get(PROVIDER, "")),
)
REPLAY_DIR = Path(__file__).resolve().parent / "replay"
GROQ_REPLAY_DIR = Path(__file__).resolve().parent / "replay_groq"
ANTHROPIC_REPLAY_DIR = Path(__file__).resolve().parent / "replay_anthropic"
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2


def request_hash(stage, system, user, schema):
    h = hashlib.sha256()
    for part in (stage, system, user, json.dumps(schema, sort_keys=True)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class Unavailable(RuntimeError):
    """A provider call or model response could not safely satisfy its request."""


def groq_schema(schema):
    """Normalize nullable enums for Groq's strict JSON-schema response format."""
    if isinstance(schema, list):
        return [groq_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {key: groq_schema(value) for key, value in schema.items() if key != "anyOf"}
    choices = schema.get("anyOf")
    if choices and all(isinstance(choice, dict) for choice in choices):
        types = [choice.get("type") for choice in choices]
        if all(kind in ("string", "null") for kind in types):
            result["type"] = list(dict.fromkeys(types))
            enums = [choice["enum"] for choice in choices if "enum" in choice]
            if enums:
                result["enum"] = [*enums[0], None]
    return result


def validate_json_schema(value, schema, path="$"):
    """Validate the JSON Schema subset used by the engine without extra dependencies."""
    if "anyOf" in schema:
        if not any(_schema_matches(value, option, path) for option in schema["anyOf"]):
            raise ValueError(f"{path} does not match any allowed schema")
        return
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]
    if expected:
        matches = any(_matches_type(value, kind) for kind in expected_types)
        if not matches:
            raise ValueError(f"{path} must be {', '.join(expected_types)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ValueError(f"{path} missing required field(s): {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(props)
            if unexpected:
                raise ValueError(f"{path} has unexpected field(s): {', '.join(sorted(unexpected))}")
        for key, child in value.items():
            if key in props:
                validate_json_schema(child, props[key], f"{path}.{key}")
    elif isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            validate_json_schema(child, schema["items"], f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")


def _matches_type(value, kind):
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "null":
        return value is None
    return True


def _schema_matches(value, schema, path):
    try:
        validate_json_schema(value, schema, path)
        return True
    except ValueError:
        return False


class LLM:
    def __init__(self, mode="replay", record=False, replay_dir=None, timeout=None, retries=None):
        if mode not in ("live", "replay"):
            raise ValueError("mode must be 'live' or 'replay'")
        if PROVIDER not in DEFAULT_MODELS:
            raise ValueError(f"unsupported LLM_PROVIDER: {PROVIDER}")
        if not MODEL:
            raise ValueError(f"a model must be configured for provider {PROVIDER}")
        self.mode, self.record = mode, record
        self.provider, self.model = PROVIDER, MODEL
        self.timeout = float(timeout if timeout is not None else os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT))
        self.retries = int(retries if retries is not None else os.environ.get("LLM_MAX_RETRIES", DEFAULT_RETRIES))
        if self.timeout <= 0 or self.retries < 0:
            raise ValueError("LLM timeout must be positive and retry count cannot be negative")
        self.calls, self.log, self.errors = 0, [], []
        self._replay = {}
        self.replay_dir = Path(replay_dir) if replay_dir else REPLAY_DIR
        self.client = None
        if mode == "live":
            self.client = self._make_client()

    def _make_client(self):
        if self.provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY", "").strip()
            if not api_key:
                raise ValueError("GROQ_API_KEY is required for live Groq mode")
            from groq import Groq
            return Groq(api_key=api_key, timeout=self.timeout, max_retries=0)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for live Anthropic mode")
        import anthropic
        return anthropic.Anthropic(api_key=api_key, timeout=self.timeout, max_retries=0)

    def _store(self, stage):
        if stage not in self._replay:
            path = self.replay_dir / f"{stage}.json"
            self._replay[stage] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return self._replay[stage]

    def _save(self, stage):
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        (self.replay_dir / f"{stage}.json").write_text(
            json.dumps(self._store(stage), ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )

    def _create(self, stage, system, user, schema, effort, max_tokens, json_retry=False):
        if self.provider == "groq":
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            if json_retry:
                messages.append({"role": "user", "content": "Return one valid JSON object matching the required schema."})
            params = {
                "model": self.model,
                "max_completion_tokens": max_tokens,
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": stage, "strict": True, "schema": groq_schema(schema)},
                },
            }
            if self.model.startswith("openai/gpt-oss-"):
                params["reasoning_effort"] = effort if effort in ("low", "medium", "high") else "medium"
            return self.client.chat.completions.create(**params)
        messages = [{"role": "user", "content": user}]
        if json_retry:
            messages.append({"role": "user", "content": "Return one valid JSON object matching the required schema."})
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )

    def _request(self, stage, key, system, user, schema, effort, max_tokens, json_retry):
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                response = self._create(stage, system, user, schema, effort, max_tokens, json_retry)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                name = type(exc).__name__.lower()
                message = self._error_message(status, name)
                retryable = status == 429 or (isinstance(status, int) and status >= 500) or any(
                    term in name for term in ("timeout", "connection")
                )
                if retryable and attempt < self.retries:
                    self.errors.append({"stage": stage, "key": key, "error": message, "retry": attempt + 1})
                    time.sleep(min(2 ** attempt, 4))
                    continue
                self.errors.append({"stage": stage, "key": key, "error": message})
                self.log.append({
                    "stage": stage, "key": key, "mode": "live", "provider": self.provider,
                    "model": self.model, "status": "error", "error": message,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                })
                raise Unavailable(f"{stage}:{key} {message}") from None
            self.calls += 1
            latency = round((time.monotonic() - started) * 1000)
            content, finish_reason, refusal = self._response_content(response)
            usage = self._usage(response)
            estimated_cost = self._estimated_cost(usage)
            self.log.append({
                "stage": stage, "key": key, "mode": "live", "provider": self.provider,
                "model": getattr(response, "model", self.model), "status": "response",
                "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                "latency_ms": latency, "estimated_cost_usd": estimated_cost,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            if finish_reason in ("length", "max_tokens"):
                self.log[-1]["status"] = "token_limit"
                self.errors.append({"stage": stage, "key": key, "error": "response reached its token limit"})
                raise Unavailable(f"{stage}:{key} response reached its token limit")
            if refusal:
                self.log[-1]["status"] = "refused"
                self.errors.append({"stage": stage, "key": key, "error": "provider refused the request"})
                raise Unavailable(f"{stage}:{key} was refused by the provider")
            if not content:
                self.log[-1]["status"] = "empty"
                self.errors.append({"stage": stage, "key": key, "error": "provider returned an empty response"})
                raise Unavailable(f"{stage}:{key} returned an empty response")
            try:
                output = json.loads(content)
                validate_json_schema(output, schema)
                return output, response, usage
            except (json.JSONDecodeError, ValueError) as exc:
                self.log[-1]["status"] = "invalid_json"
                if json_retry:
                    message = "returned malformed JSON or did not match its schema"
                    self.errors.append({"stage": stage, "key": key, "error": message})
                    raise Unavailable(f"{stage}:{key} {message}") from exc
                self.errors.append({"stage": stage, "key": key, "error": "malformed JSON/schema; retrying"})
                time.sleep(0.1)
                return self._request(stage, key, system, user, schema, effort, max_tokens, True)
        raise Unavailable(f"{stage}:{key} provider request failed")

    @staticmethod
    def _response_content(response):
        if hasattr(response, "choices"):
            choice = response.choices[0]
            message = choice.message
            return message.content or "", choice.finish_reason, getattr(message, "refusal", None)
        if response.stop_reason == "refusal":
            return "", response.stop_reason, True
        text = next((block.text for block in response.content if block.type == "text"), "")
        return text, response.stop_reason, False

    def _usage(self, response):
        usage = getattr(response, "usage", None)
        if usage is None:
            return {"input_tokens": None, "output_tokens": None}
        if self.provider == "groq":
            return {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
            }
        return {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }

    def _estimated_cost(self, usage):
        prefix = self.provider.upper()
        input_price = os.environ.get(f"{prefix}_INPUT_PRICE_PER_MILLION")
        output_price = os.environ.get(f"{prefix}_OUTPUT_PRICE_PER_MILLION")
        if input_price is None or output_price is None:
            return None
        try:
            input_price, output_price = float(input_price), float(output_price)
            if input_price < 0 or output_price < 0:
                return None
        except ValueError:
            return None
        if usage["input_tokens"] is None or usage["output_tokens"] is None:
            return None
        return round((usage["input_tokens"] * input_price + usage["output_tokens"] * output_price) / 1_000_000, 8)

    def _error_message(self, status, name):
        if status in (401, 403):
            return f"{self.provider} authentication failed; check the configured API key and permissions"
        if status == 429:
            return f"{self.provider} rate limit exceeded"
        if isinstance(status, int) and status >= 500:
            return f"{self.provider} service unavailable (HTTP {status})"
        if "timeout" in name:
            return f"{self.provider} request timed out"
        if "connection" in name:
            return f"{self.provider} connection failed"
        if isinstance(status, int):
            return f"{self.provider} request rejected (HTTP {status})"
        return f"{self.provider} request failed ({name})"

    def json(self, stage, key, system, user, schema, effort="high", max_tokens=16000):
        request_digest = request_hash(stage, system, user, schema)
        if self.mode == "replay":
            entry = self._store(stage).get(key)
            if not entry:
                raise Unavailable(f"no recording for {stage}:{key}")
            if entry.get("request_sha256") != request_digest:
                raise Unavailable(f"recording for {stage}:{key} is stale (prompt or input changed)")
            try:
                output = entry["output"]
                validate_json_schema(output, schema)
            except (KeyError, ValueError) as exc:
                raise Unavailable(f"recording for {stage}:{key} failed schema validation: {exc}") from exc
            self.log.append({
                "stage": stage, "key": key, "mode": "replay", "provider": "replay",
                "model": entry.get("source", "recorded response"), "status": "response",
            })
            return output
        output, response, usage = self._request(stage, key, system, user, schema, effort, max_tokens, False)
        if self.record:
            self._store(stage)[key] = {
                "request_sha256": request_digest, "output": output,
                "source": f"live {getattr(response, 'model', self.model)} {time.strftime('%Y-%m-%d')}",
            }
            self._save(stage)
        return output
