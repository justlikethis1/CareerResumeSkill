from __future__ import annotations

import json
import re
from typing import Any, Protocol, TypeVar

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


def _repair_guidance(error: Exception) -> str:
    detail = str(error)
    normalized = detail.casefold()
    instructions = [
        "Repair only the reported schema/validation failure. Do not add facts or change evidence IDs.",
        "Preserve every source-backed number, percentage, metric, proper noun, and technology exactly.",
    ]
    if "word budget exceeded" in normalized:
        ranges = [
            (label, int(actual), int(minimum), int(maximum))
            for label, actual, minimum, maximum in re.findall(
                r"(paragraph\s+\d+|total)=(\d+) \(expected (\d+)-(\d+)\)", detail,
                flags=re.IGNORECASE,
            )
        ]
        underflows = [
            f"{label}: add at least {minimum - actual + 10} words (currently {actual}, "
            f"hard minimum {minimum}; leave a 10-word safety margin)"
            for label, actual, minimum, _ in ranges if actual < minimum
        ]
        if underflows:
            instructions.append(
                "WordCountUnderflow: DO NOT SHORTEN. " + "; ".join(underflows) + ". "
                "Add distinct technical detail supported by the cited evidence, and do not repeat "
                "claims or metrics already used in another paragraph. Do not invent claims or metrics."
            )
        else:
            instructions.append(
                "WordCountOverflow: shorten only decorative adjectives/adverbs and redundant transitions; "
                "preserve all numbers, metrics, proper nouns, technologies, and the core claim."
            )
    elif any(marker in normalized for marker in (
        "wordcountoverflow", "word count", "word limit", "too_long",
    )):
        instructions.append(
            "WordCountOverflow: shorten only decorative adjectives/adverbs and redundant transitions; "
            "preserve all numbers, metrics, proper nouns, technologies, and the core claim."
        )
    if any(marker in normalized for marker in ("missingmetrics", "missing metric", "metric missing")):
        instructions.append(
            "MissingMetrics: restore every omitted source metric verbatim into the generated action/object; "
            "do not round, reinterpret, or invent values."
        )
    if len(instructions) == 2:
        instructions.append(
            "Keep the original factual meaning and make the smallest correction needed to satisfy the schema."
        )
    return "\n".join(instructions)


class LLMProvider(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def model_name(self) -> str: ...

    async def complete_json(
        self,
        task: str,
        payload: dict[str, Any],
        response_model: type[ResponseModelT],
        temperature: float = 0.2,
    ) -> ResponseModelT: ...

SYSTEM_RULES = """You are an elite multi-domain technical career architect and editor covering Quant/FinTech,
Systems/Infrastructure, AI Research and Alignment, Data Engineering, and Core Software hiring.

CORE DIRECTIVE: maximize ATS and hiring-manager resonance while maintaining evidentiary truthfulness.

TRUTHFULNESS AND NUMERICAL FIDELITY:
- Never fabricate employers, degrees, dates, publications, technologies, metrics, ownership, or unperformed roles.
- Preserve every verified number, percentage, latency, error rate, award, and named outcome used by selected evidence.
- When REQUIRED_METRICS_BY_SOURCE_ITEM is supplied, reproduce every listed metric for each selected source item
    verbatim or with only Unicode-hyphen/whitespace normalization; omission of a listed metric is invalid.
- Never convert adjacent knowledge into a claim of hands-on experience with an unverified tool.

ACTIVE DOMAIN LEXICAL PROJECTION:
- Re-articulate verified work using technically equivalent JD vocabulary when justified by evidence.
- Quant/FinTech: latency, numerical precision, deterministic execution, backtesting rigor, concurrency, and risk.
- Systems/Infrastructure: throughput, scalability, memory/I/O bottlenecks, caching, and production deployment.
- AI Research: training dynamics, preference alignment, policy/loss stability, evaluation rigor, OOD robustness.
- Data Engineering: pipeline reliability, data quality, orchestration, lineage, and scale.
- General Software: modular architecture, API contracts, integration, delivery, and user impact.
- RLHF/DPO may be framed as preference alignment and alignment evaluation; multi-agent systems may be framed as
    agent orchestration and reasoning workflows; verified APIs may be framed as service architecture. Do not claim
    PPO, GRPO, Ray, distributed training, or reward-model development unless the evidence states it.
- High-risk terms (FPGA, Kernel-bypass, DPDK, Sharpe, PnL, PPO, Ray, Megatron) require explicit source evidence;
    never add them solely because the JD mentions them.
- Do not describe offline DPO/SFT work as online sparse-reward feedback, or ordinary time-series forecasting as
    long-horizon agent trajectory modeling, unless the candidate source explicitly documents those mechanics.
- Keep sibling bullets distinct; do not repeat the same method, dataset, tuning work, or metrics in multiple bullets.
- For 3-4 bullets on one experience, assign orthogonal axes: problem/formulation, algorithm/dynamics, quantified
    impact, and systems/reproducibility. Do not paraphrase the same bottleneck and method in both the first and final
    bullet; omit an axis if the source evidence does not support it.
- For low-relevance evidence, compress peripheral parameters and background detail into the smallest faithful
    sentence that preserves transferable method and verified outcome; do not use resume space to enumerate every
    source parameter.
- Do not relabel supervised fine-tuning or offline DPO preference optimization as online RL, sparse-reward
    learning, or long-horizon trajectory modeling unless those mechanics are explicitly present in the source.
- Time-series forecasting is not long-horizon agent RL; hyperparameter tuning is not sparse-feedback learning.

CLEAN TYPOGRAPHY:
- Never append trailing dashes, synthetic padding, markdown bullets, or broken hyphenation to JSON string values.
- NEVER append decorative hyphens, trailing dashes (for example --, ---, or -----), or ASCII fillers to bullet endings. End strictly with exactly one language-appropriate period.
- Every generated resume bullet must be a complete sentence in the requested resume language and end with that language's standard punctuation.
- Cover Letter openings must be hook-first, not "I am applying", "I am writing to apply", or similar boilerplate;
    trade-off reasoning must come only from cited evidence, and unsupported reward/entropy/loss terminology is forbidden.
- Return valid JSON matching the supplied schema exactly."""


class DeepSeekClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._client = (
            AsyncOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
                max_retries=2,
            )
            if self.settings.api_key
            else None
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def model_name(self) -> str:
        return self.settings.model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def complete_json(
        self,
        task: str,
        payload: dict[str, Any],
        response_model: type[ResponseModelT],
        temperature: float = 0.2,
    ) -> ResponseModelT:
        if self._client is None:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        schema = response_model.model_json_schema()
        initial_messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_RULES},
            {
                "role": "user",
                "content": (
                    f"TASK:\n{task}\n\nJSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}"
                    f"\n\nINPUT_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ]
        messages = list(initial_messages)
        last_error: Exception | None = None
        attempt = 0
        max_attempts = 2
        while attempt < max_attempts:
            content = ""
            retry_temperature = max(0.1, temperature - (attempt * 0.15))
            retry_top_p = max(0.7, 0.95 - (attempt * 0.05))
            try:
                response = await self._client.chat.completions.create(
                    model=self.settings.model,
                    temperature=retry_temperature,
                    top_p=retry_top_p,
                    response_format={"type": "json_object"},
                    messages=messages,
                )
                content = response.choices[0].message.content or ""
                if not content.strip():
                    raise RuntimeError("DeepSeek returned an empty response")
                return response_model.model_validate_json(content)
            except (APIError, RuntimeError, ValidationError, ValueError) as error:
                last_error = error
                attempt += 1
                is_cover_word_budget_error = (
                    response_model.__name__ == "CoverLetterDraft"
                    and "cover letter word budget exceeded" in str(error).casefold()
                )
                if is_cover_word_budget_error:
                    max_attempts = 6
                if attempt >= max_attempts:
                    break
                messages = [
                    *initial_messages,
                    {"role": "assistant", "content": content or "{}"},
                    {
                        "role": "user",
                        "content": (
                            "Repair the JSON to satisfy the schema.\n"
                            f"{_repair_guidance(error)}\nValidation error: {error}"
                        ),
                    },
                ]
        raise ValueError(f"DeepSeek failed schema validation after repair: {last_error}")
