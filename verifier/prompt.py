"""The scan prompt, frozen: the Glass Pantry app's contents prompt, exported verbatim and never edited here.

Source: `ClaudeSpaceClient.contentsPrompt(const [], (W, H))` in the app at commit 6913119 (no compartment roster,
no part: one shelf photo). The photo size is filled into the {W}/{H} placeholders. Any change to the text is a
new prompt version and needs a new hash, so results from different prompts are never mixed.
"""

from pathlib import Path

TEMPLATE = (Path(__file__).parent / "prompts" / "contents.txt").read_text(encoding="utf-8")
SHA256 = "780861360745df9cd6e4ca25645a89ca8e29a9ed7331479131d7664becd285fb"
VERSION = "app-6913119"


def contents(w: int, h: int) -> str:
    return TEMPLATE.replace("{W}", str(w)).replace("{H}", str(h))
