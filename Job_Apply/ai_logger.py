import time
import uuid
from datetime import datetime
from db import get_db

# Model-aware pricing per token (verified May 2026)
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.000001,  "output": 0.000005},
    "claude-sonnet-4-20250514":  {"input": 0.000003,  "output": 0.000015},
    "claude-opus-4-20250514":    {"input": 0.000005,  "output": 0.000025},
    # claude-sonnet-4-20250514 was retired from the API (this app hit a 404
    # calling it) and every call site now uses claude-sonnet-5 instead.
    # Reusing the Sonnet 4 rate here as a placeholder — it's unverified for
    # Sonnet 5, so treat governance.html's cost figures as approximate until
    # this is checked against actual current pricing.
    "claude-sonnet-5":           {"input": 0.000003,  "output": 0.000015},
}
DEFAULT_INPUT_PRICE  = 0.000003
DEFAULT_OUTPUT_PRICE = 0.000015


def extract_text(content_blocks):
    """response.content is a list of content blocks (TextBlock, ThinkingBlock,
    ToolUseBlock, ...), not always text-first. Current models run thinking by
    default — e.g. Sonnet 5 runs adaptive thinking even with `thinking`
    omitted from the request — so content[0] is frequently a ThinkingBlock,
    and `response.content[0].text` raises AttributeError on it. Pull the
    first actual text block instead of assuming position 0.

    Every call site in this app expects exactly one text block per response
    (none currently request tool use or multiple text blocks), so returning
    just the first one preserves existing behavior."""
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def log_ai_call(call_type, job_id, model, prompt_tokens, completion_tokens,
                latency_ms, success, error_text=None, output_preview=None):

    pricing = MODEL_PRICING.get(model, {
        "input": DEFAULT_INPUT_PRICE, "output": DEFAULT_OUTPUT_PRICE
    })
    cost = (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])

    conn = get_db()
    conn.execute("""
        INSERT INTO ai_calls (
            id, timestamp, call_type, job_id, model,
            prompt_tokens, completion_tokens, latency_ms,
            cost_usd, success, error_text, output_preview
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        str(uuid.uuid4()),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        call_type, job_id, model,
        prompt_tokens, completion_tokens, latency_ms,
        round(cost, 6), 1 if success else 0,
        error_text,
        output_preview[:200] if output_preview else None
    ))
    conn.commit()
    conn.close()


def call_claude_with_logging(client, call_type, job_id, model, messages, max_tokens=1000):
    """
    Wrapper for every Claude API call.
    Logs latency, token usage, model-aware cost, and success/failure.
    Retries up to 3 times with exponential backoff on failure.
    """
    max_retries = 3

    for attempt in range(max_retries):
        start = time.time()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages
            )
            latency_ms = int((time.time() - start) * 1000)
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            output_text = extract_text(response.content)

            log_ai_call(
                call_type=call_type, job_id=job_id, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                latency_ms=latency_ms, success=True, output_preview=output_text
            )
            return response

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            error_text = str(e)

            log_ai_call(
                call_type=call_type, job_id=job_id, model=model,
                prompt_tokens=0, completion_tokens=0,
                latency_ms=latency_ms, success=False, error_text=error_text
            )

            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"[ai_logger] Attempt {attempt+1} failed: {error_text}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[ai_logger] All {max_retries} attempts failed for {call_type} on {job_id}")
                raise
