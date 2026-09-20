"""단어 목록 로딩과 셔플백 순환.

순수 Python 모듈이다 - Qt를 import하지 않는다. 그래서 GUI 없이 테스트된다.
"""
from __future__ import annotations

import locale
import random
from pathlib import Path

GUIDE_TEXT = "words.txt에 단어를 넣어주세요"

MAX_WORD_LEN = 64
MAX_MEANING_LEN = 120
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_LINES = 50_000

# "vocabulary, 어휘" / "vocabulary<탭>어휘" / "vocabulary = 어휘" 를 모두 받는다.
# 뜻 없이 단어만 적은 줄도 그대로 동작한다 (하위 호환).
SEPARATORS = (",", "\t", "=")


def read_text_best_effort(path: Path) -> tuple[str, str]:
    """어떤 인코딩으로 저장됐든 최선을 다해 읽는다. 예외를 던지지 않는다.

    UTF-8을 CP949보다 **먼저** 시도해야 한다. CP949는 UTF-8 바이트를 예외 없이
    깨진 글자로 디코딩해버리지만, UTF-8은 CP949 바이트에서 예외를 낸다.
    순서가 뒤집히면 한글이 조용히 깨진다.
    """
    # 병적으로 큰 파일에 메모리를 통째로 내주지 않는다. 잘린 멀티바이트 문자는
    # 아래 사다리 끝의 errors="replace" 가 받아낸다.
    with path.open("rb") as fh:
        raw = fh.read(MAX_FILE_BYTES)
    preferred = locale.getpreferredencoding(False) or "cp949"
    for enc in ("utf-8-sig", "utf-8", preferred, "cp949"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def split_entry(line: str) -> tuple[str, str | None]:
    """'단어' 또는 '단어, 뜻' 한 줄을 (단어, 뜻) 으로 쪼갠다."""
    for sep in SEPARATORS:
        if sep in line:
            head, _, tail = line.partition(sep)
            meaning = tail.strip()
            return head.strip(), (meaning[:MAX_MEANING_LEN] if meaning else None)
    return line.strip(), None


def parse_entries(text: str) -> tuple[list[str], dict[str, str]]:
    """한 줄에 한 항목. 빈 줄과 '#' 주석은 버리고, 순서를 지키며 중복을 없앤다.

    반환: (단어 목록, {단어: 뜻}). 뜻이 없는 단어는 dict 에 들어가지 않는다.
    """
    seen: set[str] = set()
    words: list[str] = []
    meanings: dict[str, str] = {}
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")[:MAX_LINES]:
        stripped = line.replace("﻿", "").strip()
        if not stripped or stripped.startswith("#"):
            continue
        word, meaning = split_entry(stripped)
        if not word or len(word) > MAX_WORD_LEN:
            continue
        if word not in seen:
            seen.add(word)
            words.append(word)
            if meaning:
                meanings[word] = meaning
        elif meaning and word not in meanings:
            # 같은 단어가 뒤에서 뜻과 함께 다시 나오면 그 뜻은 받아들인다.
            meanings[word] = meaning
    return words, meanings


def parse_words(text: str) -> list[str]:
    return parse_entries(text)[0]


def load_words(path) -> tuple[list[str], dict[str, str], str | None]:
    """(단어 목록, 뜻 사전, 오류 사유). 오류가 있어도 예외 대신 사유를 돌려준다."""
    path = Path(path)
    if not path.exists():
        return [], {}, f"{path.name} 파일이 없습니다"
    try:
        text, _ = read_text_best_effort(path)
    except OSError as exc:
        return [], {}, f"{path.name} 을 읽을 수 없습니다: {exc}"

    words, meanings = parse_entries(text)
    if not words:
        return [], {}, f"{path.name} 에 단어가 없습니다"
    return words, meanings, None


class WordSource:
    """셔플백 방식으로 단어를 돌려준다.

    전체를 섞어 한 바퀴 다 쓰고 다시 섞는다. 순수 랜덤과 달리 모든 단어가 고르게
    나오고, 백 경계에서 같은 단어가 연달아 나오지 않는다.
    """

    def __init__(self, words=(), rng: random.Random | None = None,
                 error: str | None = None, meanings: dict[str, str] | None = None):
        self._rng = rng or random.Random()
        self._words: list[str] = list(words)
        self._meanings: dict[str, str] = dict(meanings or {})
        self._error = error
        self._bag: list[str] = []
        self._i = 0
        self._prev: str | None = None
        self._refill()

    @classmethod
    def from_file(cls, path, rng: random.Random | None = None) -> "WordSource":
        words, meanings, error = load_words(path)
        return cls(words, rng=rng, error=error, meanings=meanings)

    # --- 상태 ---------------------------------------------------------

    @property
    def words(self) -> list[str]:
        return list(self._words)

    @property
    def count(self) -> int:
        return len(self._words)

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def meaning_count(self) -> int:
        return len(self._meanings)

    def meaning(self, word: str) -> str | None:
        """그 단어의 뜻. 없으면 None."""
        return self._meanings.get(word)

    # --- 순환 ---------------------------------------------------------

    def _refill(self) -> None:
        bag = list(self._words)
        self._rng.shuffle(bag)
        # 새 백의 첫 단어가 직전 단어와 같으면 뒤쪽 아무 위치와 맞바꾼다.
        # "다를 때까지 다시 섞기"로 구현하면 단어가 1개일 때 무한 루프에 빠지고,
        # "한 번만 더 섞기"는 단어가 2개일 때 절반의 확률로 실패한다.
        # 이 교환은 O(1)이고 항상 성공한다.
        if len(bag) > 1 and self._prev is not None and bag[0] == self._prev:
            j = self._rng.randrange(1, len(bag))
            bag[0], bag[j] = bag[j], bag[0]
        self._bag = bag
        self._i = 0

    def next(self) -> str:
        """다음 단어. 단어가 하나도 없으면 안내 문구를 돌려준다."""
        if not self._words:
            return GUIDE_TEXT
        if self._i >= len(self._bag):
            self._refill()
        # 끝에서 pop 하지 않고 앞에서부터 커서로 소비한다.
        # pop 방식이면 '첫 단어'가 bag[-1] 이 되어 위 중복 검사가 뒤집힌다.
        word = self._bag[self._i]
        self._i += 1
        self._prev = word
        return word

    # --- 다시 불러오기 -------------------------------------------------

    def reload_from_file(self, path) -> bool:
        """성공하면 True. **실패하면 기존 목록을 그대로 두고** False.

        편집기는 저장 도중 파일을 잠깐 비우거나 잠근다. 그 순간 다시 불러오기가
        멀쩡한 목록을 날려버리면 안 된다.
        """
        words, meanings, error = load_words(path)
        if not words:
            if not self._words:
                self._error = error  # 원래도 비어 있었으면 사유를 갱신해 준다
            return False
        self._words = words
        self._meanings = meanings
        self._error = None
        self._prev = None
        self._refill()
        return True
