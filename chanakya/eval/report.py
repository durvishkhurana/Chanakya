"""Write evaluation results as JSON, Markdown and a self-contained HTML page with simple bar charts."""

import html
import json
from pathlib import Path

ROWS = [
    ("mission_success_rate", "Mission success (consent to onboarding)"),
    ("follow_up_rate", "Follow-up agreed"),
    ("walk_away_rate", "Merchant walked away"),
    ("turns_to_close", "Agent turns to close"),
    ("turns_on_failed_calls", "Agent turns on failed calls"),
    ("escalation_precision", "Escalation precision"),
    ("escalation_recall", "Escalation recall"),
    ("wrong_action_rate", "Wrong actions per call"),
    ("safety_violations", "Safety violations"),
    ("adversarial_violations", "Violations on adversarial calls"),
    ("latency_p50_ms", "Turn latency p50 (ms)"),
    ("latency_p90_ms", "Turn latency p90 (ms)"),
    ("llm_calls_per_completed_mission", "LLM calls per completed mission"),
    ("agent_errors", "Agent turns that failed (provider errors)"),
]
NOT_MEASURED = (
    "Speed to lead and cost per completed mission in currency are not measured by this text-mode harness: "
    "it has no scheduler clock or provider billing. LLM calls per completed mission is reported instead."
)


def _cell(value) -> str:
    return "n/a" if value is None else str(value)


def markdown(results: dict, command: str) -> str:
    """A Markdown report with the command and seed that produced it."""
    config, summary = results["config"], results["summary"]
    variants = list(summary)
    lines = [
        "# Chanakya evaluation", "",
        f"- Command: `{command}`",
        f"- Mode: {config['mode']} (offline means template voices and declared moves, no network)",
        (f"- Seed: {config['seed']}; held-out Twin-B calls per variant: {summary[variants[0]]['calls']}; "
         f"adversarial calls per variant: {summary[variants[0]]['adversarial_calls']}"),
        f"- Elapsed: {config['elapsed_s']} s", "",
        "| Metric | " + " | ".join(variants) + " |",
        "|---|" + "---|" * len(variants),
    ]
    for key, label in ROWS:
        lines.append(f"| {label} | " + " | ".join(_cell(summary[v][key]) for v in variants) + " |")
    lines += ["", "Violations by kind:", ""]
    lines += [f"- {v}: {summary[v]['violations_by_kind'] or 'none'}" for v in variants]
    lines += ["", NOT_MEASURED, ""]
    return "\n".join(lines)


def html_page(results: dict, command: str) -> str:
    """A self-contained HTML page: the same table plus bars for success and walk-away rates."""
    summary = results["summary"]
    bars = []
    for key, colour in (("mission_success_rate", "#2f7d4f"), ("walk_away_rate", "#b4483c")):
        bars.append(f"<h2>{html.escape(dict(ROWS)[key])}</h2><svg viewBox='0 0 420 {len(summary) * 30 + 10}' "
                    "width='100%' role='img'>")
        for i, (variant, metrics) in enumerate(summary.items()):
            value = metrics[key] or 0
            y = 10 + i * 30
            bars.append(f"<text x='0' y='{y + 14}' font-size='12'>{html.escape(variant)}</text>"
                        f"<rect x='150' y='{y}' width='{value * 230:.1f}' height='18' fill='{colour}'/>"
                        f"<text x='{155 + value * 230:.1f}' y='{y + 14}' font-size='12'>{value:.0%}</text>")
        bars.append("</svg>")
    table = markdown(results, command).split("\n")
    rows = [line for line in table if line.startswith("|") and not line.startswith("|---")]
    cells = "".join("<tr>" + "".join(f"<td>{html.escape(c.strip())}</td>" for c in row.strip("|").split("|")) + "</tr>"
                    for row in rows)
    return ("<!doctype html><meta charset='utf-8'><title>Chanakya evaluation</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2em auto;padding:0 16px}"
            "table{border-collapse:collapse;width:100%}td{border:1px solid #ccc;padding:4px 8px}</style>"
            f"<h1>Chanakya evaluation</h1><p><code>{html.escape(command)}</code></p><table>{cells}</table>"
            + "".join(bars) + f"<p>{html.escape(NOT_MEASURED)}</p>")


def write_report(results: dict, out: Path, command: str) -> list[Path]:
    """Write ``results.json``, ``report.md`` and ``report.html`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / "results.json", out / "report.md", out / "report.html"]
    paths[0].write_text(json.dumps({**results, "command": command}, ensure_ascii=False, indent=1), encoding="utf-8")
    paths[1].write_text(markdown(results, command), encoding="utf-8")
    paths[2].write_text(html_page(results, command), encoding="utf-8")
    return paths
