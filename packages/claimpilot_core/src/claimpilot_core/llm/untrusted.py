"""Document text inside a prompt: our markup made inert, then wrapped as one data block.

Prompts put a document between `<<<` and `>>>` and mark its pages with `=== Page N ===`. A
document that prints those strings could close its own block and continue as if it were the
prompt; one that prints chat-template tokens (`<|im_start|>`, `[INST]`) could open a new turn on a
local model. Those strings are rewritten so they read the same to a person and mean nothing to
the model. Text without them passes unchanged, so cassettes of ordinary documents stay valid.
"""

import re

PAGE_MARK = re.compile(r"(={3,})(\s*page\s+\d+\s*)(={3,})", re.IGNORECASE)
CHAT_TOKENS = re.compile(r"\[(/?INST)\]|<<\s*(/?SYS)\s*>>", re.IGNORECASE)


def neutralize(text: str) -> str:
    text = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
    text = PAGE_MARK.sub(lambda m: "-" * len(m.group(1)) + m.group(2) + "-" * len(m.group(3)), text)
    text = text.replace("<|", "‹|").replace("|>", "|›")
    return CHAT_TOKENS.sub(lambda m: f"({m.group(1) or m.group(2)})", text)


def wrap(text: str, label: str = "") -> str:
    """Neutralized text between the document delimiters, with an optional label after `<<<`."""
    head = f"<<< {label}" if label else "<<<"
    return f"{head}\n{neutralize(text)}\n>>>"
