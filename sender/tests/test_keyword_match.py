from app.domain.keyword_match import title_matches


def test_matches_role_word_in_title():
    assert title_matches("Junior Backend Developer", ["junior backend developer"]) is True
    assert title_matches("Frontend Engineer", ["junior frontend developer"]) is True


def test_no_match_when_no_role_word():
    assert title_matches("Senior Sales Manager", ["junior backend developer"]) is False
    assert title_matches("Office Assistant", ["junior ai engineer"]) is False


def test_seniority_word_alone_does_not_match():
    assert title_matches("Junior Marketing Lead", ["junior"]) is False


def test_empty_title():
    assert title_matches("", ["developer"]) is False
