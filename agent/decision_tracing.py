"""Shared tracing for typed retrieval decisions without client credentials."""

import json

from langsmith import get_current_run_tree


def _trace_inputs(inputs):
    return {
        key: value for key, value in inputs.items() if key not in {"self", "on_fetch"}
    }


def _trace_outputs(response):
    if response is None:
        return {}
    outputs = dict(response)
    outputs["choices"] = [
        {"message": {"role": "assistant", "content": json.dumps(response["answers"])}}
    ]
    usage = response.get("usage") or {}
    if all(
        type(usage.get(key)) is int and usage[key] >= 0
        for key in ("input_tokens", "output_tokens")
    ):
        outputs["usage_metadata"] = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
    return outputs


def _trace_model(model, provider, purpose="retrieval"):
    run = get_current_run_tree()
    if run is not None:
        if purpose != "retrieval":
            run.name = f"jev_{purpose}"
        run.tags = list(dict.fromkeys([*(run.tags or []), purpose]))
        run.metadata.update({"ls_provider": provider, "ls_model_name": model, "purpose": purpose})
