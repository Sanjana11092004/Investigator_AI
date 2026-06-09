"""
Groq LLM client wrapper.
Handles API calls with retry logic and token counting.
"""
import time
from typing import List, Dict, Optional, Tuple

from groq import Groq
from loguru import logger

from src.config.settings import settings


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
    ) -> Tuple[str, Dict[str, int]]:
        """
        Send a chat completion request to Groq.
        
        Args:
            messages: List of {role, content} dicts.
            temperature: Sampling temperature (lower = more deterministic).
            max_tokens: Maximum tokens in response.
            system_prompt: Optional system message prepended to messages.
        
        Returns:
            Tuple of (response_text, token_usage_dict)
        """
        temperature = temperature if temperature is not None else settings.groq_temperature
        max_tokens = max_tokens or settings.groq_max_tokens

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
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