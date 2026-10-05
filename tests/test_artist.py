"""공식 음악 사이트의 아티스트 문자열 → who (tagging.parse_artist). 사례는 stellive.me/music 실제 값."""
import pytest

from updater import tagging


@pytest.fixture(scope="module")
def index(members):
    return tagging.build_index(members)


def parse(index, s):
    return tagging.parse_artist(s, index)


@pytest.mark.parametrize(
    "artist, who",
    [
        ("Yuzuha Riko", ["riko"]),
        ("Akane Lize", ["lize"]),
        ("AoKumo Rin", ["rin"]),  # 대소문자 변형
        ("Yuzuha Riko\xa0", ["riko"]),  # 상세 페이지 값 끝의 &nbsp;
        ("Neneko Mashiro x Tenko Shibuki", ["mashiro", "shibuki"]),
        ("Shirayuki Hina & Hanako Nana", ["hina", "nana"]),
        ("Yuzuha Riko & Ayatsuno Yuni & Akane Lize", ["riko", "yuni", "lize"]),
        ("Hanako Nana x Yuzuha Riko x Aokumo Rin", ["nana", "riko", "rin"]),
        ("Akane Lize,Aokumo Rin", ["lize", "rin"]),
    ],
)
def test_members(index, artist, who):
    assert parse(index, artist).who == who


@pytest.mark.parametrize(
    "artist, who",
    [
        ("Everys", ["everys"]),
        ("Universe", ["universe"]),
        ("Cliche", ["cliche"]),
        ("Cliché", ["cliche"]),
        ("Mystic & Universe", ["universe"]),  # 외부 아티스트(Mystic)는 who에서 제외
    ],
)
def test_groups(index, artist, who):
    info = parse(index, artist)
    assert info.who == who and info.groups == who


@pytest.mark.parametrize("artist", ["STELLIVE", "StelLive", "stellive"])
def test_stellive_is_all(index, artist):
    info = parse(index, artist)
    assert info.who == ["all"] and info.all


@pytest.mark.parametrize(
    "artist, who",
    [
        ("Airi Kanna", []),  # 졸업 멤버
        ("Airi Kanna & VESPERBELL 요미", []),
        ("Hanako Nana x Todoroki Hajime", ["nana"]),  # 외부 아티스트와 협업
        ("Nerissa Ravencroft x Aokumo Rin", ["rin"]),
        ("Airi Kanna & Akane Lize", ["lize"]),
        ("Someone Else", []),
        ("", []),
    ],
)
def test_graduated_and_external_are_excluded_from_who(index, artist, who):
    assert parse(index, artist).who == who


def test_token_counts_and_members(index):
    info = parse(index, "Hanako Nana x Todoroki Hajime")
    assert info.tokens == 2 and info.members == ["nana"]
    assert parse(index, "Airi Kanna").tokens == 1
    assert parse(index, "").tokens == 0


def test_x_inside_a_word_is_not_a_separator(index):
    # 'Rex'·'Alex' 같은 단어 속 x는 구분자가 아니다 (공백으로 둘러싸인 x만)
    assert parse(index, "Alex Rex").tokens == 1


def test_duplicate_members_counted_once(index):
    assert parse(index, "Akane Lize x Akane Lize").who == ["lize"]
