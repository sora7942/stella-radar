"""제목 → who 태그. 사전은 members.json에서 만들고, 오탐 방어용 목록만 이 파일에 둔다.

규칙 (SPEC 5장):
- 풀네임·이름·성(예: '아카네 리제', '리제', '아카네')과 영문 표기, 유닛명(에버리스/유니버스/클리셰, 영문 포함)을 사전으로 관리
- 여러 명이 걸리면 모두 태그(등장 순서), 하나도 없으면 'all'
- 그룹명을 먼저 찾아 그 구간을 지운다 → '유니버스'가 멤버 '유니'로 걸리지 않는다
- 긴 이름부터 찾고 지운다 → '하나코 나나'는 한 명으로만 센다
- 한 글자 이름(린)은 앞뒤가 글자가 아닐 때(조사는 허용)만, 영문 이름은 단어 경계에서만 매칭한다
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ALL = "all"

# 한글 이름을 품은 흔한 단어 — 이름 매칭 전에 지운다 (예: 바나나 ⊃ 나나, 유니폼 ⊃ 유니)
BLOCKLIST = ("바나나", "유니폼", "유니콘", "유니크", "유니온", "유니티", "유니버설", "리코더", "리제로")

# 별명. 확인된 표기만 넣는다 (근거: kangji의 유튜브 핸들 @GANGZI1 · X @GANGZIIII — members.json links).
# 공식 채널 제목의 '부키야…' 같은 별명은 확인 전이라 넣지 않았고, 그런 제목은 'all'이 된다.
ALIASES: dict[str, tuple[str, ...]] = {"kangji": ("gangzi",)}

_HANGUL = "가-힣"
_PARTICLES = "이랑|한테|에게|이|가|은|는|을|를|의|도|와|과|에|랑|만"


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _strip_accents(text: str) -> str:
    # NFD로 분해해 결합 부호만 제거 후 NFC 복원 (한글 자모는 Mn이 아니라서 영향 없음)
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if unicodedata.category(c) != "Mn"))


def _pattern(name: str) -> re.Pattern:
    parts = name.split()
    if name.isascii():  # 영문: 단어 경계 (Rin ≠ Rinse, Marine)
        body = r"\s+".join(re.escape(p) for p in parts)
        return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")
    body = r"\s*".join(re.escape(p) for p in parts)
    if len(parts) == 1 and len(name) == 1 and "가" <= name <= "힣":  # 한 글자 한글 이름 (린)
        return re.compile(rf"(?<![{_HANGUL}a-z0-9]){body}(?:(?![{_HANGUL}])|(?=(?:{_PARTICLES})))")
    return re.compile(body)


@dataclass(frozen=True)
class _Term:
    text: str
    key: str
    regex: re.Pattern


@dataclass(frozen=True)
class TagIndex:
    terms: tuple[_Term, ...]  # 그룹 먼저, 각각 긴 것부터
    blocklist: tuple[str, ...]


def _terms(names: set[str], key: str) -> list[_Term]:
    return [_Term(n, key, _pattern(n)) for n in sorted(names, key=len, reverse=True) if n]


def build_index(members: dict) -> TagIndex:
    """members.json 내용 → 태깅 사전."""
    groups: list[_Term] = []
    for g in members.get("groups", []):
        if g["key"] == "boss":  # 강지는 그룹이 아니라 멤버(kangji)로 태깅한다
            continue
        names = {_norm(g["label"])}
        if g.get("en"):
            en = _norm(g["en"])
            names |= {en, _strip_accents(en)}  # cliché / cliche
        groups += _terms(names, g["key"])

    people: list[_Term] = []
    for key, m in members["members"].items():
        names = {_norm(m["n"]), _norm(m["en"])}
        for full in (m["n"], m["en"]):
            tokens = full.split()
            if len(tokens) > 1:  # 성·이름 따로 ('아카네', '리제' / 'Akane', 'Lize')
                names |= {_norm(tokens[0]), _norm(tokens[-1])}
        names |= {_norm(a) for a in ALIASES.get(key, ())}
        people += _terms(names, key)

    ordered = sorted(groups, key=lambda t: -len(t.text)) + sorted(people, key=lambda t: -len(t.text))
    return TagIndex(terms=tuple(ordered), blocklist=tuple(_norm(w) for w in BLOCKLIST))


def tag_text(text: str, index: TagIndex) -> list[str]:
    """제목 → who 목록(등장 순서). 아무것도 없으면 ['all']."""
    t = _norm(text or "")
    for word in index.blocklist:
        t = t.replace(word, " " * len(word))

    hits: list[tuple[int, str]] = []
    for term in index.terms:
        pos = 0
        while (m := term.regex.search(t, pos)) is not None:
            hits.append((m.start(), term.key))
            t = t[: m.start()] + " " * (m.end() - m.start()) + t[m.end():]  # 찾은 구간은 지워서 짧은 이름이 또 걸리지 않게
            pos = m.end()

    keys: list[str] = []
    for _, key in sorted(hits):
        if key not in keys:
            keys.append(key)
    return keys or [ALL]
