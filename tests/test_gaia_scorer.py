"""Tests for GAIA scorer implementation.

This file pins observed behaviour of orchestrator/benchmarks/gaia_scorer.py. The xfail
tests below mark real defects rather than aspirations - they assert correct behaviour
that the scorer should exhibit once the bugs are fixed.
"""

import pytest
from orchestrator.benchmarks.gaia_scorer import (
    normalize_str,
    question_scorer,
    normalize_number_str,
)


def test_normalize_str_strips_punctuation():
    """normalize_str strips ALL punctuation uniformly and lowercases and collapses internal whitespace."""
    assert normalize_str("Hello, world!") == "hello world"
    assert normalize_str("Egalitarian.") == "egalitarian"
    assert normalize_str("This is   a test") == "this is a test"
    assert normalize_str("Comma, dash—exclamation! Period.") == "comma dashexclamation period"
    assert normalize_str("  leading and trailing spaces  ") == "leading and trailing spaces"
    assert normalize_str("Dash—emdash") == "dashemdash"


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("a;b", ["a", "b"]),
        ("a,b", ["a", "b"]),
        ("a, b", ["a", "b"]),
        ("a;b;c", ["a", "b", "c"]),
        (" a , b ; c ", ["a", "b", "c"]),
    ],
)
def test_split_string_interchangeable_separators(input_str, expected):
    """Separators are interchangeable in list mode."""
    from orchestrator.benchmarks.gaia_scorer import split_string
    assert split_string(input_str) == expected


def test_question_scorer_treats_separators_as_interchangeable():
    """A ';'-separated answer matches a ','-separated gold, and spacing after the
    separator is irrelevant — split_string strips each part. Asserted through
    question_scorer rather than split_string alone: the interchangeability that matters
    is the one the scorer actually applies."""
    assert question_scorer("a;b", "a,b")
    assert question_scorer("a, b", "a,b")
    assert question_scorer("a;b;c", "a, b, c")


def test_question_scorer_list_order_matters():
    """List element ORDER is significant. Note the gold must be one the number branch
    cannot swallow (see test_question_scorer_bug1_list_vs_number_branching) or this
    never reaches the list branch at all — '8,5,3' as a gold parses as 853.0."""
    assert not question_scorer("8,5,3", "3, 5, 8")
    assert question_scorer("8, 5, 3", "8, 5, 3")
    assert question_scorer("a,b,c", "a,b,c")


def test_question_scorer_list_count_must_match():
    """List element COUNT must match."""
    assert not question_scorer("pears", "pears, bananas")
    assert not question_scorer("pears, bananas", "pears")
    assert question_scorer("pears, bananas", "pears, bananas")


def test_question_scorer_currency_percent_stripped():
    """Currency and percent signs are stripped by number normalization."""
    assert question_scorer("$1,234.56", "1234.56")
    assert question_scorer("50%", "50")
    assert question_scorer("$100,000", "100000")
    assert question_scorer("25.5%", "25.5")


def test_question_scorer_punctuation_insensitive():
    """question_scorer is punctuation-insensitive for plain strings."""
    assert question_scorer("Egalitarian.", "egalitarian")
    assert question_scorer("Hello, world!", "hello world")
    assert question_scorer("What?!", "what")


def test_question_scorer_inf_match():
    """question_scorer('inf','inf') is True."""
    assert question_scorer("inf", "inf")


@pytest.mark.xfail(reason="bug 1: comma-separated gold consumed by number branch", strict=True)
def test_question_scorer_bug1_list_vs_number_branching():
    """Bug 1: a comma-separated gold with no spaces is consumed by the number branch before the list branch."""
    # Currently returns True when it should be False
    assert not question_scorer("358", "3,5,8")
    # Currently returns False when it should be True
    assert question_scorer("3, 5, 8", "3,5,8")


@pytest.mark.xfail(reason="bug 2: nan should be treated as identical", strict=True)
def test_question_scorer_bug2_nan_match():
    """Bug 2: question_scorer('nan','nan') is currently False when a scorer should treat identical answers as matching."""
    assert question_scorer("nan", "nan")


@pytest.mark.xfail(reason="bug 3: malformed digit grouping should return None", strict=True)
def test_normalize_number_str_bug3_malformed_digit_grouping():
    """Bug 3: normalize_number_str('1,000,00') currently returns 100000.0 when malformed digit grouping should return None."""
    assert normalize_number_str("1,000,00") is None


# Additional tests for comprehensive coverage
def test_question_scorer_plain_string_match():
    """Plain string matching after normalization."""
    assert question_scorer("Hello world", "hello world")
    assert question_scorer("Test case", "test case")
    assert question_scorer("Different", "different")  # case is normalized away


def test_question_scorer_number_match():
    """Number matching after normalization."""
    assert question_scorer("123", "123")
    assert question_scorer("123.45", "123.45")
    assert question_scorer("$123.45", "123.45")
    assert not question_scorer("123", "456")


def test_question_scorer_list_mixed_types():
    """List with mixed number and string elements."""
    assert question_scorer("123,apple", "123, apple")
    assert question_scorer("123, apple", "123,apple")
    assert not question_scorer("123,apple", "456,apple")


def test_question_scorer_empty_strings():
    """Edge case with empty strings."""
    assert question_scorer("", "")
    assert not question_scorer("", "a")
    assert not question_scorer("a", "")


def test_question_scorer_none_handling():
    """None handling as specified in the function."""
    assert not question_scorer(None, "anything")
    assert not question_scorer("anything", None)


def test_normalize_str_various_punctuation():
    """Various punctuation removal tests."""
    test_cases = [
        ("Hello, world!", "hello world"),
        ("What's up?", "whats up"),
        ("Don't worry!", "dont worry"),
        ("Hi!!! How are you??", "hi how are you"),
        ("Dash—emdash", "dashemdash"),
    ]
    for input_str, expected in test_cases:
        assert normalize_str(input_str) == expected


def test_normalize_number_str_edge_cases():
    """Edge cases for number normalization."""
    assert normalize_number_str("123") == 123.0
    assert normalize_number_str("123.45") == 123.45
    assert normalize_number_str("$123.45") == 123.45
    assert normalize_number_str("50%") == 50.0
    assert normalize_number_str("abc") is None
    assert normalize_number_str("123abc") is None
    assert normalize_number_str("12.34.56") is None
