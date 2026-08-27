"""GAIA's quasi-exact-match answer scoring.

Reimplemented from the publicly documented shape of GAIA's own scorer (number/string/list
normalization + exact match after normalization) — not verified byte-identical against
GAIA's original source, since that wasn't pulled in for this pilot. Treat a resolved/
unresolved call from this module as directionally trustworthy, not as an official GAIA
leaderboard score. If exact fidelity to the official scorer matters later, diff this
against the real implementation before trusting close calls.
"""

import re


def is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def normalize_number_str(s: str) -> float | None:
    s = s.replace("$", "").replace("%", "").replace(",", "").strip()
    return float(s) if is_float(s) else None


def split_string(s: str, chars: tuple[str, ...] = (",", ";")) -> list[str]:
    pattern = "|".join(re.escape(c) for c in chars)
    return [p.strip() for p in re.split(pattern, s)]


def normalize_str(s: str, remove_punct: bool = True) -> str:
    s = s.strip().lower()
    if remove_punct:
        s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def question_scorer(model_answer: str, ground_truth: str) -> bool:
    """True if model_answer matches ground_truth under GAIA's normalize-then-compare
    rule. Three shapes, tried in order: number, comma/semicolon-separated list, plain
    string."""
    if model_answer is None:
        return False
    model_answer = str(model_answer).strip()
    ground_truth = str(ground_truth).strip()

    gt_num = normalize_number_str(ground_truth)
    if gt_num is not None:
        ans_num = normalize_number_str(model_answer)
        return ans_num is not None and ans_num == gt_num

    if any(c in ground_truth for c in (",", ";")):
        gt_parts = split_string(ground_truth)
        ans_parts = split_string(model_answer)
        if len(gt_parts) != len(ans_parts):
            return False
        for gp, ap in zip(gt_parts, ans_parts):
            gp_num = normalize_number_str(gp)
            if gp_num is not None:
                ap_num = normalize_number_str(ap)
                if ap_num is None or ap_num != gp_num:
                    return False
            elif normalize_str(gp) != normalize_str(ap):
                return False
        return True

    return normalize_str(model_answer) == normalize_str(ground_truth)


if __name__ == "__main__":
    cases = [
        ("egalitarian", "egalitarian", True),
        ("Egalitarian.", "egalitarian", True),
        ("34,689", "34689", True),
        ("41", "41", True),
        ("backtick", "backtick", True),
        ("142", "142", True),
        ("04/15/18", "04/15/18", True),
        ("86", "86", True),
        ("3.1.3.1; 1.11.1.7", "3.1.3.1; 1.11.1.7", True),
        ("1.11.1.7; 3.1.3.1", "3.1.3.1; 1.11.1.7", False),  # order matters
        ("wrong", "right", False),
    ]
    for ans, gt, expected in cases:
        got = question_scorer(ans, gt)
        status = "ok" if got == expected else "MISMATCH"
        print(f"{status}: question_scorer({ans!r}, {gt!r}) = {got} (expected {expected})")
