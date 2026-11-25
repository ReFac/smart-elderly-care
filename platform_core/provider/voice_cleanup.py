"""Tidy obvious speaking artefacts while preserving the original business message."""

import re


VERBATIM = re.compile(r"[「」『』“”‘’\"']|原话|原文|逐字|原样|备注|抄录|记录为|(?:复述|回答|写|填)[：:]")
LEADING_FILLER = re.compile(r"^(?:(?:[嗯呃额]+|um|uh|erm)[，,、 \t]+)+")
ATTACHED_FILLER = re.compile(r"^[嗯呃额]+(?=请|麻烦|帮我|打开|查看|查询|我想|我要)")
INLINE_FILLER = re.compile(
    r"(?P<previous>\S)(?P<pause>[ \t]*[，,、])(?:[ \t]*(?:呃+|um|uh|erm)[ \t]*[，,、])+[ \t]*"
)
ONLY_FILLERS = re.compile(r"(?:[嗯呃额，,、 \t。.!！…]|um|uh|erm)+")
REPEATED_START = re.compile(
    r"^(?P<start>请帮我|麻烦帮我|麻烦你|麻烦|请你|请|帮我|给我|我想|我要|打开|查看|查询|查一下|看一下|找一下)"
    r"(?:[，,、 \t]*(?P=start))+"
)
CORRECTION = re.compile(
    r"^(?P<before>[^，,、。！？；;\n]+)[，,、][ \t]*(?:不对|(?:我)?说错了)[，,、 \t]*"
    r"(?:应该是|我是说|我说的是|是)?[，,、 \t]*(?P<after>[^，,、。！？；;\n]+[。！!]?)$"
)
PAGE_COMMAND = re.compile(r"(?:请帮我|请你|帮我|请)?[ \t]*(?:打开|进入|前往|带我去|跳转到)[ \t]*(.+?)")


def _remove_pause(match):
    # Joining two numbers across a comma could turn them into one numeric value.
    if match["previous"].isdigit() and match.string[match.end():match.end() + 1].isdigit():
        return match[0]
    return match["previous"] + match["pause"]


def _names_page(utterance, labels):
    match = PAGE_COMMAND.fullmatch(utterance.strip(" 。！!"))
    return bool(match and match[1] in labels)


def polish(transcript):
    if VERBATIM.search(transcript):
        return transcript
    candidate = LEADING_FILLER.sub("", transcript)
    candidate = ATTACHED_FILLER.sub("", candidate)
    candidate = INLINE_FILLER.sub(_remove_pause, candidate)
    candidate = REPEATED_START.sub(r"\g<start>", candidate)
    if len(candidate) <= 150 and (correction := CORRECTION.fullmatch(candidate)):
        from ..agents.chat_navigation import PAGES

        labels = {label for page in PAGES for label in (page.title, *page.aliases)}
        if all(_names_page(correction[key], labels) for key in ("before", "after")):
            candidate = correction["after"]
    # A clip containing only hesitations still belongs to the speaker for review.
    return candidate if candidate and not ONLY_FILLERS.fullmatch(candidate) else transcript
