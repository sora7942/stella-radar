import pytest

from updater import tagging


@pytest.fixture(scope="module")
def index(members):
    return tagging.build_index(members)


def tags(index, text):
    return tagging.tag_text(text, index)


# --- SPEC 10장 케이스 ----------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("아카네 리제 생일 굿즈", ["lize"]),
        ("에버리스 1주년", ["everys"]),
        ("STELLA MODE:ON", ["all"]),
        ("Cliché", ["cliche"]),
    ],
)
def test_spec_cases(index, text, expected):
    assert tags(index, text) == expected


# --- 이름 변형 -------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("리제 방송 하이라이트", ["lize"]),
        ("Akane Lize birthday", ["lize"]),
        ("lize 3D", ["lize"]),
        ("아카네 리제와 하나코 나나", ["lize", "nana"]),
        ("하나코 나나", ["nana"]),  # 풀네임은 한 명으로만 센다
        ("Cliche 1st EP", ["cliche"]),
        ("cliché", ["cliche"]),
        ("UNIVERSE 2nd Single", ["universe"]),
        ("강지 신곡", ["kangji"]),
        ("GANGZI 쇼츠", ["kangji"]),  # members.json 링크의 @GANGZI1 에서 확인된 표기
    ],
)
def test_name_variants(index, text, expected):
    assert tags(index, text) == expected


def test_multiple_members_in_order_of_appearance(index):
    assert tags(index, "[마시로, 나나, 히나] 신의상") == ["mashiro", "nana", "hina"]


def test_member_and_group_together(index):
    assert tags(index, "유니 / 에버리스") == ["yuni", "everys"]


# --- 오탐 방어 -------------------------------------------------------------------
def test_universe_is_not_yuni(index):
    # '유니버스'의 앞 두 글자가 멤버 '유니'로 걸리면 안 된다
    assert tags(index, "유니버스 1주년") == ["universe"]


@pytest.mark.parametrize(
    "text",
    [
        "바나나 먹방",  # 바(나나)
        "유니폼 공개",
        "유니콘 오버로드",
        "리코더 연주",
        "리제로 2기",  # Re:Zero
        "아린 쇼츠",  # 한 글자 이름 '린'이 단어 중간에 끼면 안 된다
        "마린 보이",
        "Rinse 광고",
        "Marine",
    ],
)
def test_false_positives_fall_back_to_all(index, text):
    assert tags(index, text) == ["all"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("린, 리제", ["rin", "lize"]),
        ("[린] 신의상", ["rin"]),
        ("린이 노래해요", ["rin"]),  # 조사가 붙은 경우
        ("Rin sings", ["rin"]),
        ("아오쿠모 린", ["rin"]),
    ],
)
def test_single_syllable_name(index, text, expected):
    assert tags(index, text) == expected


def test_empty_and_none_like(index):
    assert tags(index, "") == ["all"]
    assert tags(index, "   ") == ["all"]


# --- 실제 공식 채널 제목 (fixtures/youtube_rss_official.xml) -----------------------
REAL_OFFICIAL_TITLES = [
    ("비바해피 [ビバハピ / Mitchie M] l 에버리스 (EVERYS) Cover", ["everys"]),
    ("아오쿠모...나나?! - [스텔라 핫클립]", ["rin", "nana"]),
    ("🏖️스텔라와 함께하는 여름 휴가🏝️ DAY 4 - [린, 리제 신의상 공개 티저]", ["rin", "lize"]),
    ("🏖️스텔라와 함께하는 여름 휴가🏝️ DAY 3 - [리코, 시부키, 유니 신의상 공개 티저]", ["riko", "shibuki", "yuni"]),
    ("🏖️스텔라와 함께하는 여름 휴가🏝️ DAY 2 - [마시로, 나나, 히나 신의상 공개 티저]", ["mashiro", "nana", "hina"]),
    ("🏖️스텔라와 함께하는 여름 휴가🏝️ DAY 1 - [후야, 타비 신의상 공개 티저]", ["huya", "tabi"]),
    ("츄~♥️♥️- [스텔라 핫클립]", ["all"]),
    ("🏖️스텔라와 함께하는 여름 휴가🏝️  - [단체 수영복 신의상 공개]", ["all"]),
    ("주거랏!!!!!!!!  - [스텔라 핫클립]", ["all"]),
    ("부키야너는정말최고야(박수짝짝)  - [스텔라 핫클립]", ["shibuki"]),  # 별명 '부키'
]


@pytest.mark.parametrize("title, expected", REAL_OFFICIAL_TITLES)
def test_real_official_titles(index, title, expected):
    assert tags(index, title) == expected


# --- 별명 (ALIASES) ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("부키야너는정말최고야", ["shibuki"]),  # 단어 시작 + 조사·어미가 바로 붙는 형태
        ("부키는 최고", ["shibuki"]),
        ("부키", ["shibuki"]),
        ("03:20 부키 - 부키 벌레", ["shibuki"]),  # 공식 핫클립 설명란 표기 (두 번 나와도 한 명)
        ("[린, 부키, 리코] 귀하다", ["rin", "shibuki", "riko"]),  # 등장 순서
        ("시부키 - 압축 부키", ["shibuki"]),  # 풀 이름과 별명이 함께 있어도 한 명
        ("텐코 시부키", ["shibuki"]),
        ("(부키) 신의상", ["shibuki"]),  # 괄호 뒤
    ],
)
def test_alias_matches(index, text, expected):
    assert tags(index, text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "가부키 공연 후기",  # 歌舞伎 — '부키'를 품은 실제 단어. 앞 글자가 한글이라 제외
        "가부키초 여행",
        "아부키 도시락",
        "내 동생 정부키",  # 단어 중간은 매칭하지 않는다 (알려진 한계: 이런 말장난은 all)
    ],
)
def test_alias_does_not_match_inside_words(index, text):
    assert tags(index, text) == ["all"]


def test_alias_keys_all_exist_in_members(members):
    # 오타로 존재하지 않는 멤버 key에 별명을 달면 build_index가 조용히 무시하므로 여기서 막는다
    assert set(tagging.ALIASES) <= set(members["members"])


def test_alias_does_not_break_full_name_or_group(index):
    assert tags(index, "클리셰 부키") == ["cliche", "shibuki"]
    assert tags(index, "시부키") == ["shibuki"]


# --- 공식 공지 제목 ------------------------------------------------------------------
@pytest.mark.parametrize(
    "title, expected",
    [
        ("2026 아카네 리제 생일 한정 굿즈 예약 판매 오픈!", ["lize"]),
        ("<스텔라이브 에버리스 1주년> 아크릴 스탠드 예약 판매 오픈!", ["everys"]),
        ("<2026 STELLIVE POP-UP STELLA MODE:ON> 예약 링크 안내 공지", ["all"]),
        ("2026 하나코 나나 생일 한정 굿즈 판매 마감 임박 안내", ["nana"]),
    ],
)
def test_notice_titles(index, title, expected):
    assert tags(index, title) == expected
