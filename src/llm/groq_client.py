"""
Groq LLM client wrapper.
Handles API calls with retry logic and token counting.
"""
import json
import time
from typing import Any, List, Dict, Optional, Tuple

from groq import Groq
from loguru import logger

from src.config.settings import settings
from src.llm.prompt_templates import CHUNK_NORMALIZE_PROMPT


class GroqClient:
    """
    Wrapper around Groq API for LLM calls.
    
    Handles:
    - System + user message formatting
    - Retry on rate limits
    - Token usage tracking
    """

    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        Send a chat completion request to Groq.

        Args:
            messages: List of {role, content} dicts.
            temperature: Sampling temperature (lower = more deterministic).
            max_tokens: Maximum tokens in response.
            system_prompt: Optional system message prepended to messages.
            model: Override the default model for this call (e.g. the cheaper
                extraction model for per-chunk structuring).

        Returns:
            Tuple of (response_text, token_usage_dict)
        """
        temperature = temperature if temperature is not None else settings.groq_temperature
        max_tokens = max_tokens or settings.groq_max_tokens
        model = model or self.model

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content
                usage = {
                    "prompt": response.usage.prompt_tokens,
                    "completion": response.usage.completion_tokens,
                    "total": response.usage.total_tokens,
                }
                return text, usage

            except Exception as e:
                if "rate_limit" in str(e).lower() and attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limit hit, waiting {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                else:
                    logger.error(f"Groq API error: {e}")
                    raise

        raise RuntimeError("Groq API failed after 3 attempts")

    def normalize_chunk(self, text: str) -> Dict[str, Any]:
        """Extract structured clinical data (study fields + patients[]) from one
        chunk of narrative text, returning parsed JSON. Uses the cheaper
        extraction model since structuring fires once per chunk.

        Returns {} if the model produced no usable JSON (caller decides whether a
        failed chunk is fatal)."""
        prompt = CHUNK_NORMALIZE_PROMPT.format(text=text)
        response, _ = self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1800,
            model=settings.groq_extraction_model,
        )
        return self._parse_json_object(response)

    @staticmethod
    def _parse_json_object(raw: str) -> Dict[str, Any]:
        """Best-effort parse of a JSON object from an LLM response (tolerates
        ```json fences and leading/trailing prose)."""
        if not raw:
            return {}
        clean = raw.strip()
        if "```" in clean:
            # take the content of the first fenced block
            parts = clean.split("```")
            if len(parts) >= 2:
                clean = parts[1]
                if clean.lstrip().lower().startswith("json"):
                    clean = clean.lstrip()[4:]
        clean = clean.strip()
        try:
            obj = json.loads(clean)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            # fall back to the outermost {...} span
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end > start:
                try:
                    obj = json.loads(clean[start : end + 1])
                    return obj if isinstance(obj, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}