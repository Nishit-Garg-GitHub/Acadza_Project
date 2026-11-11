"""LLM access: live (Anthropic API) or replay (recorded responses).

Live mode uses the official `anthropic` SDK with structured JSON output, adaptive thinking
(always on for Opus 5.5; depth set via `effort`), server-side refusal fallback, and prompt
caching on the frozen system prompt.

Replay mode serves recorded outputs from engine/replay/<stage>.json so the pipeline (and the
deployed console) runs with no key and no spend. Every recorded entry stores the sha256 of the
exact request it answers; if a prompt or input changes, the hash no longer matches and replay
refuses to serve the stale answer (the stage then falls back as if the model were unavailable).
`python -m engine.run --live --record` refreshes the recordings from real API calls.
"""
import hashlib
import json
import os
import time
from pathlib import Path

MODEL = os.environ.get("ACADZA_MODEL", "claude-opus-5-5")
REPLAY_DIR = Path(__file__).resolve().parent / "replay"
PRICE = {"claude-opus-5-5": (4.00, 20.00, 0.20)}  # $/MTok input, output, cache-read


def request_hash(stage, system, user, schema):
    h = hashlib.sha256()
    for part in (stage, system, user, json.dumps(schema, sort_keys=True)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class Unavailable(Exception):
    pass


class LLM:
    def __init__(self, mode="replay", record=False):
        self.mode, self.record = mode, record
        self.calls, self.log = 0, []
        self._replay = {}
        if mode == "live":
            import anthropic  # official SDK; only needed for live runs
            self.client = anthropic.Anthropic()

    # -- replay store -------------------------------------------------------
    def _store(self, stage):
        if stage not in self._replay:
            p = REPLAY_DIR / f"{stage}.json"
            self._replay[stage] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return self._replay[stage]

    def _save(self, stage):
        REPLAY_DIR.mkdir(exist_ok=True)
        (REPLAY_DIR / f"{stage}.json").write_text(
            json.dumps(self._store(stage), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    # -- main entry ---------------------------------------------------------
    def json(self, stage, key, system, user, schema, effort="high", max_tokens=16000):
        rh = request_hash(stage, system, user, schema)
        if self.mode == "replay":
            entry = self._store(stage).get(key)
            if not entry:
                raise Unavailable(f"no recording for {stage}:{key}")
            if entry.get("request_sha256") != rh:
                raise Unavailable(f"recording for {stage}:{key} is stale (prompt or input changed)")
            self.log.append({"stage": stage, "key": key, "mode": "replay", "source": entry.get("source")})
            return entry["output"]

        t0 = time.time()
        resp = self.client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        self.calls += 1
        if resp.stop_reason == "refusal":
            raise Unavailable(f"{stage}:{key} refused")
        if resp.stop_reason == "max_tokens":
            raise Unavailable(f"{stage}:{key} hit max_tokens")
        text = next(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
        u = resp.usage
        pin, pout, pcache = PRICE.get(MODEL, (0, 0, 0))
        cost = ((u.input_tokens or 0) * pin + (u.output_tokens or 0) * pout
                + (getattr(u, "cache_read_input_tokens", 0) or 0) * pcache) / 1e6
        self.log.append({"stage": stage, "key": key, "mode": "live", "model": resp.model,
                         "in": u.input_tokens, "out": u.output_tokens,
                         "cache_read": getattr(u, "cache_read_input_tokens", 0), "usd": round(cost, 4),
                         "secs": round(time.time() - t0, 1)})
        if self.record:
            self._store(stage)[key] = {"request_sha256": rh, "output": out,
                                       "source": f"live {resp.model} {time.strftime('%Y-%m-%d')}"}
            self._save(stage)
        return out
