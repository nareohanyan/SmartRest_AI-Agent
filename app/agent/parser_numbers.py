from __future__ import annotations

import re

_NUMBER_WORDS: dict[str, str] = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "մեկ": "1",
    "մի": "1",
    "երկու": "2",
    "երեք": "3",
    "չորս": "4",
    "հինգ": "5",
    "վեց": "6",
    "յոթ": "7",
    "ութ": "8",
    "ինը": "9",
    "տասը": "10",
    "տասնմեկ": "11",
    "տասներկու": "12",
    "տասներեք": "13",
    "տասնչորս": "14",
    "տասնհինգ": "15",
    "տասնվեց": "16",
    "տասնյոթ": "17",
    "տասնութ": "18",
    "տասնինը": "19",
    "քսան": "20",
    "один": "1",
    "одна": "1",
    "одно": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
    "десять": "10",
    "одиннадцать": "11",
    "двенадцать": "12",
    "тринадцать": "13",
    "четырнадцать": "14",
    "пятнадцать": "15",
    "шестнадцать": "16",
    "семнадцать": "17",
    "восемнадцать": "18",
    "девятнадцать": "19",
    "двадцать": "20",
}

_NUMBER_WORD_PATTERN = "|".join(
    sorted((re.escape(word) for word in _NUMBER_WORDS), key=len, reverse=True)
)
_NUMBER_WORD_RE = re.compile(r"\b(" + _NUMBER_WORD_PATTERN + r")\b")


def normalize_number_words(normalized_text: str) -> str:
    if not normalized_text:
        return normalized_text

    return _NUMBER_WORD_RE.sub(lambda match: _NUMBER_WORDS[match.group(1)], normalized_text)
