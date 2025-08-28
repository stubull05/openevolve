"""
OpenAI API interface for LLMs
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

import openai

from openevolve.config import LLMConfig
from openevolve.llm.base import LLMInterface

logger = logging.getLogger(__name__)


class OpenAILLM(LLMInterface):
    """LLM interface using OpenAI-compatible APIs"""

    def __init__(
        self,
        model_cfg: Optional[dict] = None,
    ):
        self.model = model_cfg.name
        self.system_message = model_cfg.system_message
        self.temperature = model_cfg.temperature
        self.top_p = model_cfg.top_p
        self.max_tokens = model_cfg.max_tokens
        self.timeout = model_cfg.timeout
        self.retries = model_cfg.retries
        self.retry_delay = model_cfg.retry_delay
        self.api_base = model_cfg.api_base
        self.api_key = model_cfg.api_key
        self.random_seed = getattr(model_cfg, "random_seed", None)

        # Set up API client with extended timeout for thinking models
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            timeout=max(self.timeout, 600),  # Ensure minimum 10 minutes for thinking models
        )

        # Only log unique models to reduce duplication
        if not hasattr(logger, "_initialized_models"):
            logger._initialized_models = set()

        if self.model not in logger._initialized_models:
            logger.info(f"Initialized OpenAI LLM with model: {self.model}")
            logger._initialized_models.add(self.model)

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from a prompt"""
        return await self.generate_with_context(
            system_message=self.system_message,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )

    async def generate_with_context(
        self, system_message: str, messages: List[Dict[str, str]], **kwargs
    ) -> str:
        """Generate text using a system message and conversational context"""
        # Prepare messages with system message
        formatted_messages = [{"role": "system", "content": system_message}]
        formatted_messages.extend(messages)

        # Set up generation parameters
        if self.api_base == "https://api.openai.com/v1" and str(self.model).lower().startswith("o"):
            # For o-series models
            params = {
                "model": self.model,
                "messages": formatted_messages,
                "max_completion_tokens": kwargs.get("max_tokens", self.max_tokens),
            }
        else:
            params = {
                "model": self.model,
                "messages": formatted_messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "top_p": kwargs.get("top_p", self.top_p),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }

        # Add seed parameter for reproducibility if configured
        # Skip seed parameter for Google AI Studio endpoint as it doesn't support it
        seed = kwargs.get("seed", self.random_seed)
        if seed is not None:
            if self.api_base == "https://generativelanguage.googleapis.com/v1beta/openai/":
                logger.warning(
                    "Skipping seed parameter as Google AI Studio endpoint doesn't support it. "
                    "Reproducibility may be limited."
                )
            else:
                params["seed"] = seed

        # Attempt the API call with retries
        retries = kwargs.get("retries", self.retries)
        retry_delay = kwargs.get("retry_delay", self.retry_delay)
        timeout = kwargs.get("timeout", self.timeout)

        # Use a longer timeout for the asyncio.wait_for to account for slow models
        extended_timeout = max(timeout, 600)  # At least 10 minutes
        
        for attempt in range(retries + 1):
            try:
                response = await asyncio.wait_for(self._call_api(params), timeout=extended_timeout)
                return response
            except asyncio.TimeoutError:
                if attempt < retries:
                    logger.warning(f"Timeout ({extended_timeout}s) on attempt {attempt + 1}/{retries + 1}. Retrying...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"All {retries + 1} attempts failed with timeout ({extended_timeout}s)")
                    raise
            except Exception as e:
                if attempt < retries:
                    logger.warning(
                        f"Error on attempt {attempt + 1}/{retries + 1}: {str(e)}. Retrying..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"All {retries + 1} attempts failed with error: {str(e)}")
                    raise

    async def _call_api(self, params: Dict[str, Any]) -> str:
        """Make the actual API call"""
        # Use asyncio to run the blocking API call in a thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self.client.chat.completions.create(**params)
        )
        # VERBOSE LOGGING
        logger.info(f"=== LLM REQUEST ===")
        logger.info(f"Model: {params['model']}")
        logger.info(f"System: {params['messages'][0]['content'][:200]}...")
        logger.info(f"User: {params['messages'][1]['content'][:200]}...")
        
        response_content = response.choices[0].message.content
        
        # VERBOSE LOGGING OF RESPONSE
        logger.info(f"=== LLM RESPONSE ===")
        logger.info(f"Response length: {len(response_content)}")
        logger.info(f"Response preview: {response_content[:500]}...")
        logger.info(f"Response end: ...{response_content[-200:]}")
        
        return response_content
