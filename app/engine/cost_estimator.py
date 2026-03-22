"""Pre-run cost estimation.

Uses **tiktoken** for accurate token counting and a cheap
``gpt-4.1-nano`` call to score the question's complexity, then
projects how much a full run will cost so the UI can show the user
a range *before* they commit.
"""

import tiktoken
from openai import AsyncOpenAI

from app.models import RunConfig, CostEstimate
from app.engine.cost_tracker import MODEL_PRICING


# ------------------------------------------------------------------
# Token counting
# ------------------------------------------------------------------

def count_tokens(text: str, model: str = "gpt-4.1") -> int:
    """Return the number of tokens in *text* for *model*.

    Falls back to ``cl100k_base`` if tiktoken does not recognise the
    model name.
    """
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


# ------------------------------------------------------------------
# Single-box cost helper
# ------------------------------------------------------------------

def estimate_box_cost(model: str, input_tokens: int, est_output: int) -> float:
    """Estimate the dollar cost for one cycle of a single box.

    Parameters
    ----------
    model:
        Key into ``MODEL_PRICING``.
    input_tokens:
        Estimated prompt tokens for the cycle.
    est_output:
        Estimated completion tokens for the cycle.
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4.1-mini"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (est_output / 1_000_000) * pricing["output"]
    return input_cost + output_cost


# ------------------------------------------------------------------
# Complexity scoring (nano call)
# ------------------------------------------------------------------

async def score_complexity(client: AsyncOpenAI, question: str) -> int:
    """Use ``gpt-4.1-nano`` to rate analytical complexity on a 1-10 scale.

    Returns ``5`` (mid-range) on any failure so that the estimator can
    still produce a reasonable projection.
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-nano",
            max_tokens=10,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rate the analytical complexity of this question "
                        "from 1-10 (just the number):\n\n"
                        f"{question[:2000]}"
                    ),
                }
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        digits = "".join(c for c in raw if c.isdigit())[:2]
        score = int(digits) if digits else 5
        return max(1, min(10, score))
    except Exception:
        return 5


# ------------------------------------------------------------------
# Full run estimator
# ------------------------------------------------------------------

async def estimate_run_cost(
    client: AsyncOpenAI,
    config: RunConfig,
) -> CostEstimate:
    """Generate a pre-run cost estimate for *config*.

    The estimate combines:
    * exact token counts (via tiktoken) for the user's question + docs,
    * a nano-model complexity score (1-10), and
    * per-box cost projections scaled by estimated cycle count.

    Returns a ``CostEstimate`` with low/high range and any warnings.
    """
    # --- Token count for all input material ---
    all_text = config.question + " ".join(config.documents)
    input_tokens = count_tokens(all_text)

    # --- Complexity scoring via nano ---
    complexity = await score_complexity(client, config.question)

    # --- Estimated cycle count (3-20 depending on complexity) ---
    est_cycles = max(3, min(20, int(complexity * 1.5)))

    # --- Per-cycle cost for each logical component ---
    box1_per_cycle = estimate_box_cost(
        "o4-mini", input_tokens, est_output=4000
    )
    box2_per_cycle = estimate_box_cost(
        "gpt-4.1", input_tokens * 2, est_output=3000
    )
    specialist_per_cycle = estimate_box_cost(
        "gpt-4.1-mini", input_tokens * 3, est_output=2000
    )
    gate_per_cycle = estimate_box_cost(
        "gpt-4.1-nano", 500, est_output=100
    )

    num_specialists = len(config.specialists)
    total_per_cycle = (
        box1_per_cycle
        + box2_per_cycle
        + (specialist_per_cycle * num_specialists)
        + (gate_per_cycle * num_specialists)
    )

    # --- Warnings ---
    warnings: list[str] = []
    if input_tokens > 100_000:
        warnings.append(
            f"Documents contain ~{input_tokens:,} tokens. "
            "Consider summarizing to reduce costs."
        )
    if num_specialists > 5:
        warnings.append(
            f"{num_specialists} specialists will multiply costs. "
            "Consider consolidating related domains."
        )

    return CostEstimate(
        input_tokens=input_tokens,
        complexity_score=complexity,
        estimated_cycles=est_cycles,
        cost_low=round(total_per_cycle * est_cycles * 0.6, 2),
        cost_high=round(total_per_cycle * est_cycles * 1.2, 2),
        cost_per_cycle=round(total_per_cycle, 4),
        warnings=warnings,
    )
