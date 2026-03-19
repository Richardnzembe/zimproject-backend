import re


ORDERED_LIST_REGEX = re.compile(r"^(\s*)(\d+)([.)])(\s+)(.*)$")
BULLET_LIST_REGEX = re.compile(r"^(\s*)[-*+]\s+")
HEADING_REGEX = re.compile(r"^(#{1,6})\s+")
CODE_FENCE_REGEX = re.compile(r"^```")
HORIZONTAL_RULE_REGEX = re.compile(r"^([-*_]\s*){3,}$")
BLOCKQUOTE_REGEX = re.compile(r"^>\s?")


def _indent_width(value):
    return len(value.replace("\t", "    "))


def normalize_ordered_list_numbering(text):
    if not isinstance(text, str) or not text:
        return text or ""

    lines = text.split("\n")
    counters = []
    in_code_fence = False
    normalized_lines = []

    for line in lines:
        trimmed = line.strip()

        if CODE_FENCE_REGEX.match(line):
            counters.clear()
            in_code_fence = not in_code_fence
            normalized_lines.append(line)
            continue

        if in_code_fence or not trimmed:
            normalized_lines.append(line)
            continue

        if (
            HEADING_REGEX.match(trimmed)
            or HORIZONTAL_RULE_REGEX.match(trimmed)
            or BLOCKQUOTE_REGEX.match(trimmed)
        ):
            counters.clear()
            normalized_lines.append(line)
            continue

        ordered_match = ORDERED_LIST_REGEX.match(line)
        if ordered_match:
            indent = _indent_width(ordered_match.group(1))

            while counters and counters[-1]["indent"] > indent:
                counters.pop()

            counter = next(
                (item for item in counters if item["indent"] == indent),
                None,
            )
            if counter is None:
                counter = {
                    "indent": indent,
                    "value": int(ordered_match.group(2) or "1"),
                }
                counters.append(counter)
            else:
                counter["value"] += 1

            normalized_lines.append(
                f"{ordered_match.group(1)}{counter['value']}"
                f"{ordered_match.group(3)}{ordered_match.group(4)}{ordered_match.group(5)}"
            )
            continue

        if BULLET_LIST_REGEX.match(line):
            normalized_lines.append(line)
            continue

        leading_whitespace = re.match(r"^\s*", line)
        line_indent = _indent_width(leading_whitespace.group(0) if leading_whitespace else "")
        if counters and line_indent > counters[-1]["indent"]:
            normalized_lines.append(line)
            continue

        counters.clear()
        normalized_lines.append(line)

    return "\n".join(normalized_lines)
