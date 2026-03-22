"""Async box runner — the core reasoning loop for a single box.

Each box subscribes to the shared EventStore, filters incoming events
by its visibility rules, builds a prompt (stable system first, growing
context second, variable instruction last — for OpenAI prompt caching),
calls the OpenAI API, parses labeled findings from the response, and
publishes them back to the store.

Box 1 (o4-mini):   sees NOTHING from other boxes — only initial question/docs.
Box 2 (gpt-4.1):   sees ONLY Box 1 events.
Specialists (gpt-4.1-mini): see ALL events from ALL boxes, gated by a
                    gpt-4.1-nano relevance filter.
"""

import asyncio
import logging
import re
from typing import Callable, Optional

from openai import APIError, AsyncOpenAI, RateLimitError

from app.engine.cost_tracker import CostTracker
from app.engine.event_store import EventStore
from app.models import BoxState, Event

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Approximate safe context limits (tokens) per model.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "o4-mini": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4.1-nano": 1_000_000,
}

# Characters-per-token rough estimate used for overflow checks.
_CHARS_PER_TOKEN = 4

# Regex that extracts labeled findings from a model response.
FINDING_PATTERN = re.compile(
    r"\[(HYPOTHESIS|EVIDENCE|CONCLUSION|DEAD_END|QUESTION|CONNECTION|DONE)\]"
    r"\s*(.*?)"
    r"(?=\[(?:HYPOTHESIS|EVIDENCE|CONCLUSION|DEAD_END|QUESTION|CONNECTION|DONE)\]|\Z)",
    re.DOTALL,
)

# Maximum retry attempts on transient API errors.
_MAX_RETRIES = 3

# Fraction of remaining budget that a single call should not exceed.
_SINGLE_CALL_BUDGET_WARN = 0.50


class BoxRunner:
    """Drives a single reasoning box through subscribe-think-publish cycles."""

    def __init__(
        self,
        box_id: str,
        model: str,
        system_prompt: str,
        event_store: EventStore,
        cost_tracker: CostTracker,
        client: AsyncOpenAI,
        visibility_filter: Callable[[list[Event]], list[Event]],
        max_completion_tokens: int = 4096,
        status_callback: Optional[Callable] = None,
        specialist_domain: Optional[str] = None,
        gate_model: str = "gpt-4.1-nano",
    ) -> None:
        self.box_id = box_id
        self.model = model
        self.system_prompt = system_prompt
        self.event_store = event_store
        self.cost_tracker = cost_tracker
        self.client = client
        self.visibility_filter = visibility_filter
        self.max_completion_tokens = max_completion_tokens
        self.status_callback = status_callback
        self.specialist_domain = specialist_domain
        self.gate_model = gate_model

        self.state = BoxState(box_id=box_id)
        self.is_done = False
        self._cancelled = False
        self._last_processed_idx: int = 0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Signal this box to exit its run loop at the next opportunity."""
        self._cancelled = True

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    async def _update_status(self, status: str) -> None:
        self.state.status = status
        if self.status_callback:
            await self.status_callback(self.box_id, status, self.state.current_cycle)

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self, initial_context: str = "") -> None:
        """Main run loop — blocks until the box signals [DONE] or is cancelled."""
        queue = await self.event_store.subscribe(self.box_id)

        try:
            # Box 1 kicks off immediately with the question / documents.
            if self.box_id == "box1":
                await self._update_status("thinking")
                await self._run_cycle(initial_context)

            while not self.is_done and not self._cancelled:
                # ---- Wait for new events --------------------------------
                new_events = await self._collect_events(queue, timeout=5.0)

                if self._cancelled:
                    break

                # ---- Visibility ------------------------------------------
                visible_events = self.visibility_filter(
                    self.event_store.get_all_events()
                )

                if not new_events and self.state.current_cycle > 0:
                    # No new work arrived.  If other boxes are done, wrap up.
                    done_events = [
                        e
                        for e in self.event_store.get_all_events()
                        if e.event_type == "done" and e.source_box != self.box_id
                    ]
                    if done_events and self.box_id != "box1":
                        if not self.is_done:
                            await self._update_status("concluding")
                            await self._run_cycle(
                                self._build_context(visible_events), conclude=True
                            )
                            await self._signal_done()
                        break
                    continue

                # ---- Specialist relevance gate ---------------------------
                if self.specialist_domain and visible_events:
                    # Only gate-check events we haven't produced ourselves.
                    foreign_events = [
                        e
                        for e in visible_events
                        if e.source_box != self.box_id
                    ]
                    if foreign_events:
                        visible_events = await self._check_relevance(foreign_events)
                        if not visible_events:
                            continue

                # ---- Budget checks ---------------------------------------
                if self.cost_tracker.should_stop():
                    await self._update_status("concluding")
                    await self._run_cycle(
                        self._build_context(visible_events), conclude=True
                    )
                    await self._signal_done()
                    break

                # ---- Run a thinking cycle --------------------------------
                await self._update_status("thinking")
                context = (
                    initial_context
                    if self.box_id == "box1"
                    else self._build_context(visible_events)
                )
                await self._run_cycle(
                    context, conclude=self.cost_tracker.should_conclude()
                )

                if self.is_done:
                    break

                await self._update_status("waiting")

        except asyncio.CancelledError:
            logger.info("Box %s cancelled", self.box_id)
        except Exception:
            logger.exception("Box %s encountered an error", self.box_id)
            self.state.status = "error"
            await self._update_status("error")
        finally:
            self.event_store.unsubscribe(self.box_id)

    # ------------------------------------------------------------------
    # Event collection
    # ------------------------------------------------------------------

    async def _collect_events(
        self, queue: asyncio.Queue, timeout: float
    ) -> list[Event]:
        """Collect events from *queue*, blocking up to *timeout* seconds."""
        events: list[Event] = []
        try:
            event = await asyncio.wait_for(queue.get(), timeout=timeout)
            events.append(event)
            # Drain anything that arrived while we were waiting.
            while not queue.empty():
                events.append(queue.get_nowait())
        except asyncio.TimeoutError:
            pass
        return events

    # ------------------------------------------------------------------
    # Thinking cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self, context: str, conclude: bool = False) -> None:
        """Execute one think-parse-publish cycle."""
        self.state.current_cycle += 1

        # -- Build conclude instruction if needed ----------------------
        conclude_instruction = ""
        if conclude:
            conclude_instruction = (
                "\n\nIMPORTANT: The system is approaching its budget limit. "
                "Wrap up your analysis. Synthesize your most important "
                "findings into clear conclusions. Output [DONE] when complete."
            )

        system = self.system_prompt.replace(
            "{conclude_instruction}", conclude_instruction
        )

        # -- Handle context window overflow ----------------------------
        context = self._maybe_summarize(context)

        # -- Assemble messages (system first, context last) ------------
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": context if context else "Begin your analysis."},
        ]

        # -- Check for single-call budget overrun ----------------------
        remaining = self.cost_tracker.remaining_budget
        if remaining > 0:
            est_prompt_tokens = len(system + context) // _CHARS_PER_TOKEN
            # Very rough per-call cost estimate
            from app.engine.cost_tracker import MODEL_PRICING

            pricing = MODEL_PRICING.get(self.model, MODEL_PRICING["gpt-4.1-mini"])
            est_cost = (est_prompt_tokens / 1_000_000) * pricing["input"] + (
                self.max_completion_tokens / 1_000_000
            ) * pricing["output"]
            if est_cost > remaining * _SINGLE_CALL_BUDGET_WARN:
                logger.warning(
                    "Box %s cycle %d: estimated call cost $%.4f exceeds 50%% "
                    "of remaining budget $%.4f",
                    self.box_id,
                    self.state.current_cycle,
                    est_cost,
                    remaining,
                )

        # -- Call API --------------------------------------------------
        response = await self._call_api(messages)
        if response is None:
            return

        # -- Parse findings from response ------------------------------
        content = response.choices[0].message.content or ""
        events = self._parse_findings(content)

        # -- Record token usage & cost ---------------------------------
        usage = response.usage
        usage_dict: dict = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }
        if (
            hasattr(usage, "prompt_tokens_details")
            and usage.prompt_tokens_details is not None
        ):
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0)
            usage_dict["prompt_tokens_details"] = {"cached_tokens": cached}
        if (
            hasattr(usage, "completion_tokens_details")
            and usage.completion_tokens_details is not None
        ):
            reasoning = getattr(
                usage.completion_tokens_details, "reasoning_tokens", 0
            )
            usage_dict["completion_tokens_details"] = {
                "reasoning_tokens": reasoning
            }
            self.state.total_reasoning_tokens += reasoning

        await self.cost_tracker.record_usage(self.box_id, self.model, usage_dict)

        # -- Update local state ----------------------------------------
        self.state.total_input_tokens += usage.prompt_tokens
        self.state.total_output_tokens += usage.completion_tokens

        # -- Publish findings ------------------------------------------
        for event in events:
            if event.event_type == "done":
                self.is_done = True
                await self._signal_done()
            else:
                await self.event_store.publish(event)
                self.state.findings.append(event)

    # ------------------------------------------------------------------
    # OpenAI API call with retry
    # ------------------------------------------------------------------

    async def _call_api(
        self, messages: list[dict], max_retries: int = _MAX_RETRIES
    ):
        """Call the OpenAI Chat Completions API with exponential backoff.

        Returns the API response, or ``None`` after exhausting retries.
        """
        for attempt in range(max_retries):
            try:
                kwargs: dict = {
                    "model": self.model,
                    "messages": messages,
                }
                # o4-mini has built-in chain-of-thought and requires
                # ``max_completion_tokens`` instead of ``max_tokens``.
                if self.model == "o4-mini":
                    kwargs["max_completion_tokens"] = self.max_completion_tokens
                else:
                    kwargs["max_tokens"] = self.max_completion_tokens

                return await self.client.chat.completions.create(**kwargs)

            except RateLimitError:
                wait = (2 ** attempt) * 2
                logger.warning(
                    "Rate limited on %s, retrying in %ds (attempt %d/%d)",
                    self.box_id,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await self._update_status("rate_limited")
                await asyncio.sleep(wait)

            except APIError as exc:
                if attempt == max_retries - 1:
                    logger.error(
                        "API error on %s after %d retries: %s",
                        self.box_id,
                        max_retries,
                        exc,
                    )
                    return None
                wait = 2 ** attempt
                logger.warning(
                    "API error on %s, retrying in %ds: %s", self.box_id, wait, exc
                )
                await asyncio.sleep(wait)

        return None

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_findings(self, content: str) -> list[Event]:
        """Extract labeled findings from *content*.

        If no labels are found the entire text is emitted as a single
        ``[EVIDENCE]`` event so that nothing is silently lost.
        """
        findings: list[Event] = []
        matches = FINDING_PATTERN.findall(content)

        if matches:
            for event_type, text in matches:
                text = text.strip()
                if not text:
                    continue
                findings.append(
                    Event(
                        source_box=self.box_id,
                        event_type=event_type.lower(),
                        content=text,
                        metadata={
                            "cycle": self.state.current_cycle,
                            "model": self.model,
                        },
                    )
                )
        elif content.strip():
            # No labels found — treat the whole response as evidence.
            findings.append(
                Event(
                    source_box=self.box_id,
                    event_type="evidence",
                    content=content.strip(),
                    metadata={
                        "cycle": self.state.current_cycle,
                        "model": self.model,
                        "unparsed": True,
                    },
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Context building & overflow handling
    # ------------------------------------------------------------------

    def _build_context(self, events: list[Event]) -> str:
        """Format *events* into a textual context block."""
        if not events:
            return "No findings yet."

        lines: list[str] = []
        for e in events:
            lines.append(f"[{e.source_box}] [{e.event_type.upper()}] {e.content}")
        return "\n\n".join(lines)

    def _maybe_summarize(self, context: str) -> str:
        """If *context* would blow the model's context window, truncate the
        oldest events and prepend a 'story so far' summary header.

        This is a synchronous heuristic (no extra API call) to keep the
        box running when context grows large.
        """
        limit = MODEL_CONTEXT_LIMITS.get(self.model, 128_000)
        # Reserve room for system prompt + completion.
        safe_input_chars = (limit - self.max_completion_tokens) * _CHARS_PER_TOKEN
        # Subtract a buffer for the system prompt (~2 000 tokens).
        safe_input_chars -= 8_000

        if len(context) <= safe_input_chars:
            return context

        logger.warning(
            "Box %s context (%d chars) exceeds safe limit (%d chars), summarizing",
            self.box_id,
            len(context),
            safe_input_chars,
        )

        # Split into individual event blocks.
        blocks = context.split("\n\n")
        if len(blocks) <= 2:
            # Already minimal — hard-truncate the tail.
            return context[:safe_input_chars]

        # Keep the most recent half; summarize the older half.
        midpoint = len(blocks) // 2
        older = blocks[:midpoint]
        newer = blocks[midpoint:]

        # Build a compressed summary of the older events.
        summary_lines: list[str] = ["=== STORY SO FAR (summarized older events) ==="]
        for block in older:
            # Extract just the label and first 120 chars.
            summary_lines.append(block[:150].replace("\n", " "))
        summary_lines.append("=== END SUMMARY ===\n")

        summarized = "\n".join(summary_lines) + "\n\n".join(newer)

        # If still too long, hard-truncate.
        if len(summarized) > safe_input_chars:
            summarized = summarized[-safe_input_chars:]

        return summarized

    # ------------------------------------------------------------------
    # Specialist relevance gate
    # ------------------------------------------------------------------

    async def _check_relevance(self, events: list[Event]) -> list[Event]:
        """Use the nano gate model to filter *events* by relevance to this
        specialist's domain.

        On gate failure, returns all events (fail-open).
        """
        if not events:
            return []

        event_summaries = "\n".join(
            f"{i + 1}. [{e.source_box}] {e.event_type}: {e.content[:200]}"
            for i, e in enumerate(events)
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.gate_model,
                max_tokens=100,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Domain: {self.specialist_domain}\n\n"
                            "Which of these findings are relevant to this domain? "
                            "Return ONLY the numbers (comma-separated) of relevant "
                            "items, or 'none'.\n\n"
                            f"{event_summaries}"
                        ),
                    }
                ],
            )

            # Record the gate cost.
            usage = response.usage
            await self.cost_tracker.record_usage(
                f"gate:{self.box_id}",
                self.gate_model,
                {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
            )

            result = (response.choices[0].message.content or "").strip().lower()
            if result == "none":
                return []

            nums = [int(n.strip()) - 1 for n in re.findall(r"\d+", result)]
            return [events[i] for i in nums if 0 <= i < len(events)]

        except Exception:
            logger.warning(
                "Relevance gate failed for %s — falling through", self.box_id
            )
            return events  # Fail-open: don't block on gate failure.

    # ------------------------------------------------------------------
    # Done signaling
    # ------------------------------------------------------------------

    async def _signal_done(self) -> None:
        """Publish a ``done`` event and update state."""
        self.is_done = True
        self.state.status = "done"
        done_event = Event(
            source_box=self.box_id,
            event_type="done",
            content=f"Box {self.box_id} has completed analysis.",
            metadata={"cycle": self.state.current_cycle},
        )
        await self.event_store.publish(done_event)
        await self._update_status("done")
