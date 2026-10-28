import json
import logging
import os
import re
from pathlib import Path

# Get the directory where this file is located
module_dir = os.path.dirname(os.path.abspath(__file__))

# ── Load chat prompt ──
prompt_path = os.path.join(module_dir, "sales_assistant.md")
with open(prompt_path, "r", encoding="utf-8") as f:
    system_prompt = f.read()

# ── Load voice prompt ──
voice_prompt_path = os.path.join(module_dir, "voice_assistant.md")
with open(voice_prompt_path, "r", encoding="utf-8") as f:
    voice_system_prompt = f.read()

# Scan for dynamic documents in pageindex_data
data_dir = Path(module_dir).parent.parent / "data" / "knowledge"
dynamic_docs_list = []
if data_dir.exists():
    for json_file in sorted(data_dir.glob("*.json")):
        name = json_file.stem
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                meta = data.get("metadata", {})
                desc = meta.get("description", "No description available")
                # Keep it concise
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                dynamic_docs_list.append(f"- **{name}** - {desc}")
        except (OSError, json.JSONDecodeError, TypeError):
            logging.getLogger(__name__).warning(
                "Could not load document metadata: %s", name
            )

# Reconstruct DOCUMENTS section in both prompts
if dynamic_docs_list:
    doc_section_content = "\n".join(dynamic_docs_list)
    pattern = r"(## DOCUMENTS\s*\n)([\s\S]*?)(### Document Selection Guide)"
    replacement = rf"\1{doc_section_content}\n\n\3"
    system_prompt = re.sub(pattern, replacement, system_prompt)
    voice_system_prompt = re.sub(pattern, replacement, voice_system_prompt)

sales_assistant_system_prompt = system_prompt
voice_assistant_system_prompt = voice_system_prompt

# Keep the existing tool prompts for an explicit LLM-retrieval comparison.
# Jev mode uses an evidence-only writer with no contradictory tool instructions.
answer_rules = Path(module_dir, "answer_only.md").read_text(encoding="utf-8")
sales_answer_system_prompt = (
    answer_rules
    + """

For chat, use 2-4 sentences for most answers.
Cite the actual document title and page or section naturally for factual answers.
When clarifying, offer 3-5 short choices using [OPTIONS] and [/OPTIONS] on separate lines.
Use tables only for requested comparisons and bullet points only when they improve clarity.
On a first greeting, briefly introduce yourself as Chanakya, an independent AI assistant for Paytm business products.
"""
)
voice_answer_system_prompt = (
    answer_rules
    + """

This is a voice conversation and the answer will be spoken aloud.
Use 1-3 short, natural sentences for most answers.
Do not use Markdown, tables, emojis, option blocks, links, or URLs.
Ask clarifying questions conversationally with a few choices inline.
Read numbers naturally, preserving exact amounts when they matter.
Cite sources briefly in spoken form, such as "According to the Paytm product page".
On a first greeting, briefly introduce yourself as Chanakya, an independent AI assistant for Paytm business products.
"""
)

# Apply the same sales policy to every retrieval and answer path.
sales_rules = Path(module_dir, "sales_rules.md").read_text(encoding="utf-8")
sales_assistant_system_prompt += "\n\n" + sales_rules
voice_assistant_system_prompt += "\n\n" + sales_rules
sales_answer_system_prompt += "\n\n" + sales_rules
voice_answer_system_prompt += "\n\n" + sales_rules
