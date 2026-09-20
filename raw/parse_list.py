# -*- coding: utf-8 -*-
"""사용자가 준 원본 목록을 'word, definition' 형식으로 바꾸고 중복을 찾는다."""
import re
import sys
from collections import OrderedDict
from pathlib import Path

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# 표제어 자체가 여러 단어인 것들. 첫 공백에서 자르면 안 된다.
PHRASES = {"in response to", "in unison"}


def split_paren_def(line):
    """'Word (= 뜻)' 형태. 뜻 안에 괄호가 또 있을 수 있어 짝을 맞춰 센다."""
    i = line.find("(=")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(line)):
        if line[j] == "(":
            depth += 1
        elif line[j] == ")":
            depth -= 1
            if depth == 0:
                inside = line[i + 2:j].strip()
                tail = line[j + 1:].strip()
                word = line[:i].strip()
                definition = (inside + " " + tail).strip() if tail else inside
                return word, definition
    return line[:i].strip(), line[i + 2:].strip()


def parse(line):
    line = line.strip()
    if not line:
        return None

    paren = split_paren_def(line)
    if paren:
        return paren

    # 한글이 시작되는 지점, 여는 괄호, ' = ' 중 가장 먼저 오는 곳에서 자른다.
    cuts = []
    m = HANGUL.search(line)
    if m:
        cuts.append(m.start())
    k = line.find("(")
    if k > 0:
        cuts.append(k)
    e = line.find(" = ")
    if e > 0:
        cuts.append(e)
    if cuts:
        c = min(cuts)
        word = line[:c].strip()
        definition = line[c:].strip()
        if definition.startswith("= "):
            definition = definition[2:].strip()
        return word, definition

    # 여기까지 왔으면 한글도 괄호도 '=' 도 없는 순수 영어 줄이다.
    # "Construe interpret" 처럼 뒤에 영어 설명이 붙은 경우와
    # "In response to" 처럼 표제어 자체가 여러 단어인 경우를 갈라야 한다.
    if line.lower() in PHRASES:
        return line, None
    if " / " in line:
        # "Desiccation / desiccate" 처럼 같은 어근의 다른 품사를 나란히 적은 경우
        head, _, rest = line.partition(" / ")
        return head.strip(), "cf. " + rest.strip()
    parts = line.split(None, 1)
    if len(parts) == 2 and parts[1][:1].islower():
        return parts[0], parts[1]
    return line, None


def main():
    src = Path(sys.argv[1])
    lines = src.read_text(encoding="utf-8").splitlines()

    entries = []
    for line in lines:
        parsed = parse(line)
        if parsed and parsed[0]:
            entries.append(parsed)

    # 중복 찾기 (대소문자 무시)
    seen = OrderedDict()
    dups = OrderedDict()
    for word, definition in entries:
        key = word.lower()
        if key in seen:
            dups.setdefault(key, [seen[key]]).append((word, definition))
        else:
            seen[key] = (word, definition)

    print(f"원본 {len(lines)}줄 -> 항목 {len(entries)}개")
    print(f"고유 단어 {len(seen)}개 / 중복 {len(dups)}건")
    print()
    print("=== 중복 ===")
    for key, items in dups.items():
        print(f"  {items[0][0]}")
        for w, d in items:
            print(f"      - {d if d else '(설명 없음)'}")
    print()
    no_def = [w for w, d in seen.values() if not d]
    print(f"=== 설명이 없는 단어 {len(no_def)}개 ===")
    print("  " + ", ".join(no_def))


if __name__ == "__main__":
    main()
