import time
import asyncio
import json
import structlog
from pydantic import BaseModel
from openai import AsyncOpenAI, AsyncAzureOpenAI
from app.config import get_settings

logger = structlog.get_logger(__name__)


class LLMUnavailableError(Exception):
    """Raised when the LLM is unreachable or circuit breaker is open."""
    pass


class LLMParseError(Exception):
    """Raised when the LLM response cannot be parsed into the expected schema."""
    pass


class LLMRateLimitError(Exception):
    """Raised when the LLM returns a rate limit error."""
    pass


class AzureOpenAIClient:
    """
    Production wrapper around Azure OpenAI with:
    - Structured output mode (response_format using native OpenAI beta parse)
    - Retry logic with exponential backoff (max 3 retries, base 1s)
    - Token usage tracking per call
    - Structured logging of every call (model, tokens, latency, incident_id)
    - Circuit breaker: if 5 consecutive failures, raise LLMUnavailableError and stop retrying
    """

    def __init__(self):
        settings = get_settings()
        if "/v1" in settings.AZURE_OPENAI_ENDPOINT:
            self._client = AsyncOpenAI(
                base_url=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
            )
        else:
            self._client = AsyncAzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
        self._consecutive_failures: int = 0
        self._circuit_breaker_threshold: int = 5
        self._max_retries: int = 3
        self._base_backoff_s: float = 1.0
        self._model_name = settings.AZURE_OPENAI_DEPLOYMENT

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        response_schema: type[BaseModel],
        incident_id: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> BaseModel:
        """
        Calls Azure OpenAI with structured output (response_format=response_schema).
        Parses and validates the response as the given Pydantic model.
        Raises: LLMUnavailableError, LLMParseError, LLMRateLimitError
        """
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            logger.error(
                "llm.circuit_breaker_open",
                incident_id=incident_id,
                consecutive_failures=self._consecutive_failures,
            )
            raise LLMUnavailableError(
                f"Circuit breaker open after {self._consecutive_failures} consecutive failures"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_exception = None
        for attempt in range(1, self._max_retries + 1):
            start = time.time()
            try:
                # Use standard beta.chat.completions.parse for structured output
                response = await self._client.beta.chat.completions.parse(
                    model=self._model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_schema,
                )
                elapsed = time.time() - start

                # Extract token usage
                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                logger.info(
                    "llm.complete",
                    incident_id=incident_id,
                    model=self._model_name,
                    schema=response_schema.__name__,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=round(elapsed * 1000),
                    attempt=attempt,
                )

                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raw_content = response.choices[0].message.content
                    try:
                        parsed = response_schema.model_validate_json(raw_content)
                    except Exception as parse_err:
                        raise LLMParseError(
                            f"Failed to parse LLM response as {response_schema.__name__}: {parse_err}"
                        ) from parse_err

                # Success — reset circuit breaker
                self._consecutive_failures = 0
                return parsed

            except LLMParseError:
                # Parse errors are not transient — don't retry
                self._consecutive_failures += 1
                raise

            except Exception as e:
                elapsed = time.time() - start
                last_exception = e
                err_str = str(e).lower()

                # Check for rate limiting
                if "429" in err_str or "rate" in err_str:
                    self._consecutive_failures += 1
                    logger.warning(
                        "llm.rate_limited",
                        incident_id=incident_id,
                        attempt=attempt,
                        latency_ms=round(elapsed * 1000),
                    )
                    if attempt == self._max_retries:
                        raise LLMRateLimitError(f"Rate limited after {attempt} attempts") from e
                else:
                    self._consecutive_failures += 1
                    logger.warning(
                        "llm.call_failed",
                        incident_id=incident_id,
                        attempt=attempt,
                        error=str(e),
                        latency_ms=round(elapsed * 1000),
                    )

                if attempt < self._max_retries:
                    backoff = self._base_backoff_s * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

        # All retries exhausted
        raise LLMUnavailableError(
            f"LLM unavailable after {self._max_retries} retries: {last_exception}"
        )

    async def health_check(self) -> bool:
        """Return True immediately to avoid consuming tokens on frequent healthchecks."""
        return True
