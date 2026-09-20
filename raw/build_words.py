# -*- coding: utf-8 -*-
"""원본 목록 + 영어 정의 -> words.txt 생성. 누락/불일치를 전부 보고한다."""
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_list import parse  # noqa: E402

# 원본의 철자 오류. 학습용 목록이라 조용히 두지 않고 고치고 알린다.
SPELLING_FIXES = {
    "perserverance": "Perseverance",
    "far-fetch": "Far-fetched",
}


def main():
    root = Path(__file__).resolve().parent
    raw_lines = (root / "list.txt").read_text(encoding="utf-8").splitlines()

    # 정의 사전
    defs = {}
    for line in (root / "en_defs.txt").read_text(encoding="utf-8").splitlines():
        if "::" not in line:
            continue
        w, _, d = line.partition("::")
        defs[w.strip().lower()] = (w.strip(), d.strip())

    # 원본에서 고유 단어를 순서대로 뽑는다 (중복은 첫 등장 위치 유지)
    order = OrderedDict()
    korean_notes = {}
    for line in raw_lines:
        parsed = parse(line)
        if not parsed or not parsed[0]:
            continue
        word, note = parsed
        fixed = SPELLING_FIXES.get(word.lower(), word)
        key = fixed.lower()
        if key not in order:
            order[key] = fixed
        if note:
            korean_notes.setdefault(key, []).append(note)

    missing, extra = [], []
    out = ["# 영단어 학습 목록. \"word, definition\" 형식이며 마우스를 올리면 설명이 보입니다.",
           "# 원본(직접 적으신 한글 노트)은 raw/list.txt 에 그대로 보관되어 있습니다.",
           "# 수정한 뒤 트레이 > 다시 불러오기 를 누르면 바로 반영됩니다.",
           "",
           f"# ---- 직접 정리하신 목록 ({len(order)}개) ----"]
    for key, word in order.items():
        if key in defs:
            out.append(f"{defs[key][0]}, {defs[key][1]}")
        else:
            missing.append(word)
            out.append(word)

    # 기본 제공 목록을 뒤에 이어붙인다. 겹치는 단어는 직접 정리하신 쪽을 남긴다.
    base_path = root / "base_list.txt"
    base_added, base_skipped = [], []
    if base_path.exists():
        for line in base_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            w, _, d = line.partition(",")
            w, d = w.strip(), d.strip()
            if w.lower() in order:
                base_skipped.append(w)
                continue
            # 표기를 앞 목록과 맞춘다 (abate -> Abate)
            base_added.append(f"{w[:1].upper() + w[1:]}, {d}" if d else w.capitalize())
        if base_added:
            out.append("")
            out.append(f"# ---- 기본 제공 목록 ({len(base_added)}개, 겹치는 "
                       f"{len(base_skipped)}개 제외) ----")
            out.extend(base_added)

    used = set(order.keys())
    for key, (w, _) in defs.items():
        if key not in used:
            extra.append(w)

    Path(root.parent / "words.txt").write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"직접 정리하신 목록 {len(order)}개 + 기본 목록 {len(base_added)}개"
          f" (겹쳐서 건너뛴 것 {len(base_skipped)}개) = 총 {len(order) + len(base_added)}개")
    if base_skipped:
        print("  겹쳐서 건너뛴 단어:", ", ".join(base_skipped))
    print(f"정의가 없는 단어: {missing if missing else '없음'}")
    print(f"쓰이지 않은 정의: {extra if extra else '없음'}")
    print()
    print("철자 교정:")
    for wrong, right in SPELLING_FIXES.items():
        print(f"  {wrong} -> {right}")
    print()
    print("중복이라 합친 단어 (원본에 두 번 이상 나온 것):")
    for key, notes in korean_notes.items():
        if len(notes) > 1:
            print(f"  {order[key]}: " + " | ".join(notes))


if __name__ == "__main__":
    main()
