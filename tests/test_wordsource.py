"""wordsource 모듈 단위 테스트. Qt 없이 돈다."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wordsource as ws  # noqa: E402


def make(tmp_path, text, encoding="utf-8", name="words.txt"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return p


def src(path, seed=0):
    return ws.WordSource.from_file(path, rng=random.Random(seed))


# --- 파일 로딩 ----------------------------------------------------------

def test_one_word_per_line(tmp_path):
    s = src(make(tmp_path, "apple\nbanana\ncherry\n"))
    assert s.words == ["apple", "banana", "cherry"]
    assert s.error is None


def test_strips_whitespace_and_blank_lines(tmp_path):
    s = src(make(tmp_path, "  apple  \n\n\t\nbanana\n   \n"))
    assert s.words == ["apple", "banana"]


def test_handles_crlf(tmp_path):
    s = src(make(tmp_path, "apple\r\nbanana\r\n"))
    assert s.words == ["apple", "banana"]


def test_drops_comment_lines(tmp_path):
    s = src(make(tmp_path, "# 토익 단어\napple\n#banana\ncherry\n"))
    assert s.words == ["apple", "cherry"]


def test_dedupes_preserving_first_seen_order(tmp_path):
    s = src(make(tmp_path, "banana\napple\nbanana\ncherry\napple\n"))
    assert s.words == ["banana", "apple", "cherry"]


def test_drops_absurdly_long_lines(tmp_path):
    s = src(make(tmp_path, "apple\n" + "x" * 200 + "\nbanana\n"))
    assert s.words == ["apple", "banana"]


# --- 인코딩 -------------------------------------------------------------

def test_strips_utf8_bom(tmp_path):
    p = tmp_path / "words.txt"
    p.write_bytes(b"\xef\xbb\xbfapple\nbanana\n")
    s = src(p)
    assert s.words == ["apple", "banana"], "BOM 이 첫 단어에 붙으면 안 된다"


def test_reads_cp949_file(tmp_path):
    """한글 Windows 메모장이 ANSI 로 저장한 경우."""
    s = src(make(tmp_path, "사과\napple\n", encoding="cp949"))
    assert s.words == ["사과", "apple"]


def test_utf8_is_preferred_over_cp949(tmp_path):
    """순서가 뒤집히면 CP949 가 UTF-8 바이트를 예외 없이 깨뜨린다 — 조용한 버그."""
    s = src(make(tmp_path, "사과\n포도\n", encoding="utf-8"))
    assert s.words == ["사과", "포도"], "UTF-8 을 먼저 시도해야 한다"


def test_undecodable_bytes_do_not_raise(tmp_path):
    p = tmp_path / "words.txt"
    p.write_bytes(b"\xff\xfe\x00apple\nbanana\n")
    s = src(p)
    assert isinstance(s.next(), str)
    assert s.error is None or s.count > 0


# --- 비어 있거나 없는 파일 ----------------------------------------------

@pytest.mark.parametrize("content", ["", "   \n\t\n", "# 주석만\n# 또 주석\n"])
def test_empty_like_files_report_guidance(tmp_path, content):
    s = src(make(tmp_path, content))
    assert s.count == 0
    assert s.error is not None
    assert s.next() == ws.GUIDE_TEXT, "단어가 없어도 죽지 않고 안내를 띄운다"


def test_missing_file_reports_guidance(tmp_path):
    s = src(tmp_path / "nope.txt")
    assert s.count == 0
    assert s.error is not None
    assert s.next() == ws.GUIDE_TEXT


def test_missing_file_next_is_stable(tmp_path):
    s = src(tmp_path / "nope.txt")
    assert [s.next() for _ in range(5)] == [ws.GUIDE_TEXT] * 5


# --- 셔플백 -------------------------------------------------------------

def test_first_cycle_is_a_permutation(tmp_path):
    words = ["a", "b", "c", "d", "e"]
    s = src(make(tmp_path, "\n".join(words)))
    drawn = [s.next() for _ in range(len(words))]
    assert sorted(drawn) == sorted(words)
    assert len(set(drawn)) == len(words), "한 바퀴 안에서 중복이 나오면 안 된다"


def test_second_cycle_is_also_a_permutation(tmp_path):
    words = ["a", "b", "c", "d", "e"]
    s = src(make(tmp_path, "\n".join(words)))
    [s.next() for _ in range(len(words))]
    second = [s.next() for _ in range(len(words))]
    assert sorted(second) == sorted(words)


@pytest.mark.parametrize("seed", range(20))
def test_no_consecutive_repeats_three_words(tmp_path, seed):
    """백 경계에서 같은 단어가 두 번 연달아 나오면 안 된다."""
    s = src(make(tmp_path, "a\nb\nc\n"), seed=seed)
    drawn = [s.next() for _ in range(200)]
    assert all(x != y for x, y in zip(drawn, drawn[1:]))


@pytest.mark.parametrize("seed", range(20))
def test_two_words_strictly_alternate(tmp_path, seed):
    """초안의 '한 번 더 섞기' 알고리즘이 50% 확률로 실패하던 바로 그 케이스."""
    s = src(make(tmp_path, "a\nb\n"), seed=seed)
    drawn = [s.next() for _ in range(200)]
    assert all(x != y for x, y in zip(drawn, drawn[1:]))
    assert set(drawn) == {"a", "b"}


def test_single_word_terminates(tmp_path):
    """'다를 때까지 다시 섞기'로 구현하면 여기서 무한 루프에 빠진다."""
    s = src(make(tmp_path, "solo\n"))
    assert [s.next() for _ in range(10)] == ["solo"] * 10


def test_seeded_rng_is_reproducible(tmp_path):
    p = make(tmp_path, "a\nb\nc\nd\ne\nf\n")
    a = [ws.WordSource.from_file(p, rng=random.Random(1234)).next() for _ in range(1)]
    s1 = ws.WordSource.from_file(p, rng=random.Random(1234))
    s2 = ws.WordSource.from_file(p, rng=random.Random(1234))
    assert [s1.next() for _ in range(20)] == [s2.next() for _ in range(20)]
    assert a  # 사용하지 않는 변수 경고 방지


def test_all_words_appear_over_two_cycles(tmp_path):
    words = [f"w{i}" for i in range(30)]
    s = src(make(tmp_path, "\n".join(words)))
    drawn = [s.next() for _ in range(60)]
    assert set(drawn) == set(words), "셔플백은 모든 단어를 고르게 돌려야 한다"


# --- 다시 불러오기 ------------------------------------------------------

def test_reload_swaps_list(tmp_path):
    p = make(tmp_path, "a\nb\n")
    s = src(p)
    s.next()
    p.write_text("x\ny\nz\n", encoding="utf-8")
    assert s.reload_from_file(p) is True
    assert s.words == ["x", "y", "z"]
    assert set(s.next() for _ in range(3)) == {"x", "y", "z"}


def test_reload_failure_keeps_existing_words(tmp_path):
    """편집기는 저장 중 파일을 잠깐 비운다. 그 순간 목록을 날리면 안 된다."""
    p = make(tmp_path, "a\nb\nc\n")
    s = src(p)
    p.write_text("", encoding="utf-8")
    assert s.reload_from_file(p) is False
    assert s.words == ["a", "b", "c"]
    assert s.next() in {"a", "b", "c"}


def test_reload_missing_file_keeps_existing_words(tmp_path):
    p = make(tmp_path, "a\nb\nc\n")
    s = src(p)
    p.unlink()
    assert s.reload_from_file(p) is False
    assert s.words == ["a", "b", "c"]


def test_reload_onto_empty_source_succeeds(tmp_path):
    p = tmp_path / "words.txt"
    s = src(p)
    assert s.count == 0
    p.write_text("a\nb\n", encoding="utf-8")
    assert s.reload_from_file(p) is True
    assert s.words == ["a", "b"]
    assert s.error is None


def test_stray_bom_inside_content_is_stripped(tmp_path):
    """BOM 이 중복으로 들어간 병적인 파일도 첫 단어를 망가뜨리면 안 된다."""
    p = tmp_path / "words.txt"
    p.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfapple\nbanana\n")
    s = src(p)
    assert s.words == ["apple", "banana"]


# --- 한글 뜻 -------------------------------------------------------------

def test_comma_separated_meaning(tmp_path):
    s = src(make(tmp_path, "vocabulary, 어휘\nephemeral, 덧없는\n"))
    assert s.words == ["vocabulary", "ephemeral"]
    assert s.meaning("vocabulary") == "어휘"
    assert s.meaning("ephemeral") == "덧없는"


def test_tab_and_equals_separators(tmp_path):
    s = src(make(tmp_path, "alpha\t첫째\nbravo = 둘째\n"))
    assert s.meaning("alpha") == "첫째"
    assert s.meaning("bravo") == "둘째"


def test_word_without_meaning_still_works(tmp_path):
    """뜻 없이 단어만 적은 기존 파일이 그대로 동작해야 한다."""
    s = src(make(tmp_path, "alpha\nbravo, 둘째\ncharlie\n"))
    assert s.words == ["alpha", "bravo", "charlie"]
    assert s.meaning("alpha") is None
    assert s.meaning("bravo") == "둘째"
    assert s.meaning_count == 1


def test_meaning_whitespace_is_trimmed(tmp_path):
    s = src(make(tmp_path, "alpha ,   첫째   \n"))
    assert s.words == ["alpha"]
    assert s.meaning("alpha") == "첫째"


def test_meaning_may_contain_commas_after_the_first(tmp_path):
    """첫 구분자에서만 쪼갠다. 뜻 안의 쉼표는 살아 있어야 한다."""
    s = src(make(tmp_path, "run, 달리다, 운영하다\n"))
    assert s.words == ["run"]
    assert s.meaning("run") == "달리다, 운영하다"


def test_empty_meaning_is_treated_as_none(tmp_path):
    s = src(make(tmp_path, "alpha,\nbravo,   \n"))
    assert s.words == ["alpha", "bravo"]
    assert s.meaning("alpha") is None
    assert s.meaning_count == 0


def test_duplicate_word_picks_up_later_meaning(tmp_path):
    s = src(make(tmp_path, "alpha\nalpha, 첫째\n"))
    assert s.words == ["alpha"]
    assert s.meaning("alpha") == "첫째"


def test_overlong_meaning_is_truncated(tmp_path):
    s = src(make(tmp_path, "alpha, " + "가" * 300 + "\n"))
    assert len(s.meaning("alpha")) == ws.MAX_MEANING_LEN


def test_meanings_survive_cp949(tmp_path):
    s = src(make(tmp_path, "vocabulary, 어휘\n", encoding="cp949"))
    assert s.meaning("vocabulary") == "어휘"


def test_reload_updates_meanings(tmp_path):
    p = make(tmp_path, "alpha\n")
    s = src(p)
    assert s.meaning("alpha") is None
    p.write_text("alpha, 첫째\n", encoding="utf-8")
    assert s.reload_from_file(p) is True
    assert s.meaning("alpha") == "첫째"


def test_unknown_word_has_no_meaning(tmp_path):
    s = src(make(tmp_path, "alpha, 첫째\n"))
    assert s.meaning("없는단어") is None


# --- 히스토리 (이전/다음) -------------------------------------------------

def from_words(words, seed=0):
    return ws.WordSource(words, rng=random.Random(seed))


def test_no_history_at_the_start():
    s = from_words(["a", "b", "c"])
    assert s.can_prev is False
    assert s.prev() is None
    assert s.history == []


def test_prev_walks_back_through_what_was_shown():
    s = from_words(["a", "b", "c", "d"])
    seen = [s.next() for _ in range(4)]
    assert s.can_prev is True
    back = [s.prev() for _ in range(3)]
    assert back == seen[-2::-1]
    assert s.can_prev is False
    assert s.prev() is None


def test_next_after_prev_replays_instead_of_drawing():
    """되돌아간 뒤의 '다음'은 새 단어가 아니라 왔던 길이어야 한다."""
    s = from_words(["a", "b", "c", "d", "e"])
    seen = [s.next() for _ in range(4)]
    s.prev(); s.prev()
    assert s.next() == seen[2]
    assert s.next() == seen[3]
    # 끝에 닿으면 그때부터 새로 뽑는다
    fresh = s.next()
    assert s.history == seen + [fresh]


def test_current_follows_the_cursor():
    s = from_words(["a", "b", "c"])
    assert s.current() is None
    first = s.next()
    assert s.current() == first
    second = s.next()
    assert s.current() == second
    assert s.prev() == first
    assert s.current() == first


def test_history_is_capped():
    s = from_words(["a", "b", "c"])
    for _ in range(ws.HISTORY_LIMIT + 50):
        s.next()
    assert len(s.history) == ws.HISTORY_LIMIT
    # 잘라낸 뒤에도 커서가 끝을 가리켜야 한다
    assert s.current() == s.history[-1]
    assert s.can_prev is True


def test_reload_clears_history(tmp_path):
    p = tmp_path / "words.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    s = ws.WordSource.from_file(p, rng=random.Random(0))
    s.next(); s.next()
    p.write_text("x\ny\nz\n", encoding="utf-8")
    assert s.reload_from_file(p) is True
    # 지워진 단어로 되돌아갈 수 있으면 안 된다
    assert s.history == []
    assert s.can_prev is False


def test_empty_source_has_no_history():
    s = from_words([])
    assert s.next() == ws.GUIDE_TEXT
    assert s.history == []
    assert s.can_prev is False
    assert s.can_next is False
