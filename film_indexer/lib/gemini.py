"""
Wrapper Gemini pour le pipeline film-indexer.

Stack :
- google-genai==1.66.0 (le nouveau SDK unifié, pas l'ancien google-generativeai)
- async client pour rate limiting via asyncio.Semaphore
- tenacity pour retry exponentiel
- pydantic pour validation des outputs JSON

Modèles utilisés :
- gemini-2.5-flash : Pass A vidéo (fallback safe, batch+vidéo fonctionne)
- gemini-3.1-flash-lite-preview : Pass A vidéo (cheapest si dispo)
- gemini-3.1-pro-preview : Pass B reasoning text-only (qualité max sur petit volume)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Type, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


T = TypeVar("T", bound=BaseModel)


# Modèles disponibles avril 2026
MODEL_PASS_A_PRIMARY = "gemini-3-flash-preview"  # async sync, contourne bug #1890
MODEL_PASS_A_FALLBACK = "gemini-2.5-flash"  # safe fallback
MODEL_PASS_B_REASONING = "gemini-3-flash-preview"  # text-only, reasoning medium
MODEL_PASS_B_DEEP = "gemini-3-flash-preview"  # quality max pour council deep

# Coûts ($/M tokens) — pour cost tracker
PRICING = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
}


class GeminiClient:
    """Async wrapper around google-genai."""

    def __init__(self, api_key: Optional[str] = None):
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.client = genai.Client(api_key=api_key)
        self.uploaded_files: dict[str, types.File] = {}

    # ============================================================
    # FILE UPLOAD
    # ============================================================

    def upload_video(self, video_path: Path, mime_type: str = "video/mp4") -> types.File:
        """Upload a video to Gemini Files API. Returns the File object.

        File is cached by path: subsequent calls with same path skip upload.
        """
        key = str(video_path.resolve())
        if key in self.uploaded_files:
            return self.uploaded_files[key]

        print(f"[gemini] Uploading {video_path.name} ({video_path.stat().st_size / 1e6:.1f} MB)...")
        file = self.client.files.upload(
            file=str(video_path),
            config={"mime_type": mime_type},
        )

        # Wait for ACTIVE state
        while file.state.name == "PROCESSING":
            time.sleep(2)
            file = self.client.files.get(name=file.name)

        if file.state.name != "ACTIVE":
            raise RuntimeError(f"Upload failed: {file.state.name}")

        print(f"[gemini] Upload OK: {file.name} ({file.state.name})")
        self.uploaded_files[key] = file
        return file

    # ============================================================
    # GENERATE WITH STRUCTURED OUTPUT
    # ============================================================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((RuntimeError, ValidationError)),
        reraise=True,
    )
    def generate_structured(
        self,
        model: str,
        contents: list,
        schema: Type[T],
        system_instruction: Optional[str] = None,
        thinking_level: str = "low",
    ) -> tuple[T, dict]:
        """Generate structured JSON output validated against a pydantic schema.

        Returns (parsed_object, metadata_dict).
        Metadata includes: tokens_in, tokens_out, cost_usd, model, latency_s.

        Uses google-genai response_schema natif pour forcer la structure exacte.
        """
        start = time.time()

        config: dict = {
            "response_mime_type": "application/json",
        }
        # NOTE: response_schema=pydantic_class fails because google-genai serializes
        # 'additionalProperties' which Gemini API doesn't recognize. We rely on
        # tolerant pydantic validation (extra="allow") + retry on parse error.

        if system_instruction:
            # Append explicit JSON shape hint at end of system instruction
            schema_json = schema.model_json_schema()
            schema_hint = json.dumps(schema_json, indent=2, ensure_ascii=False)
            system_instruction = (
                f"{system_instruction}\n\n"
                f"---\n\n"
                f"OUTPUT JSON SCHEMA (must match exactly, no extra fields):\n"
                f"```json\n{schema_hint}\n```"
            )
            config["system_instruction"] = system_instruction

        # Try with thinking_config if model supports it
        if "gemini-3" in model:
            config["thinking_config"] = types.ThinkingConfig(thinking_budget=0 if thinking_level == "minimal" else -1)

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise RuntimeError(f"Gemini API call failed on {model}: {e}") from e

        latency = time.time() - start

        # Extract usage metadata
        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", 0) or 0
        tokens_out = getattr(usage, "candidates_token_count", 0) or 0

        pricing = PRICING.get(model, {"input": 0, "output": 0})
        cost = (tokens_in / 1e6) * pricing["input"] + (tokens_out / 1e6) * pricing["output"]

        # Parse JSON
        text = response.text
        if not text:
            raise RuntimeError(f"Empty response from {model}")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON from {model}: {e}\nText: {text[:500]}") from e

        # Validate against schema
        try:
            obj = schema.model_validate(data)
        except ValidationError as e:
            raise RuntimeError(f"Schema validation failed for {schema.__name__}: {e}") from e

        meta = {
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 6),
            "latency_s": round(latency, 2),
        }
        return obj, meta

    # ============================================================
    # CLEANUP
    # ============================================================

    def delete_uploaded(self, file_name: str):
        """Delete an uploaded file from Gemini Files API."""
        try:
            self.client.files.delete(name=file_name)
        except Exception as e:
            print(f"[gemini] delete warning: {e}")
