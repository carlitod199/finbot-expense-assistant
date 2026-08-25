# -*- coding: utf-8 -*-
"""Integration with the LLM (Google Gemini) for parsing and answering.

Uses the official `google-genai` SDK. The API key ALWAYS comes from an
environment variable (GEMINI_API_KEY) - never hardcoded.
"""

from __future__ import annotations

import json
import os
import re

from google import genai
from google.genai import types

from finbot import dates, persona

# Default model: gemini-2.0-flash (fast, available on the free tier).
# Overridable through the GEMINI_MODEL environment variable.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

_client: genai.Client | None = None


def client() -> genai.Client:
    """Return the lazily created Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


def _response_text(resp) -> str:
    """Extract the text from a Gemini response, tolerating odd shapes."""
    try:
        if resp.text:
            return resp.text.strip()
    except Exception:  # noqa: BLE001 - resp.text can raise when there are no parts
        pass
    try:
        parts = resp.candidates[0].content.parts
        return "".join(getattr(p, "text", "") or "" for p in parts).strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_json(text: str) -> dict:
    """Extract the first JSON object found in the text, tolerating noise."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"Response contained no JSON: {text!r}")


def interpret_message(text: str) -> dict:
    """Ask Gemini to extract intent/amount/category/date from the message."""
    system = persona.extraction_prompt(dates.today().isoformat())
    resp = client().models.generate_content(
        model=MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=500,
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    data = _extract_json(_response_text(resp))

    # Defensive normalisation: guarantee every key exists.
    data.setdefault("intent", "other")
    data.setdefault("amount", None)
    data.setdefault("category", None)
    data.setdefault("date", None)
    data.setdefault("item_description", None)
    data.setdefault("confidence", 0.0)
    return data


def answer_purchase_query(user_text: str, budget_context: str) -> str:
    """Generate the purchase-decision reply following the persona and format."""
    system = persona.PERSONA + "\n\n" + persona.PURCHASE_REPLY_FORMAT
    content = (
        f"Budget context for the current month:\n{budget_context}\n\n"
        f"User message: {user_text}"
    )
    resp = client().models.generate_content(
        model=MODEL,
        contents=content,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=800,
            temperature=0.3,
        ),
    )
    return _response_text(resp)
