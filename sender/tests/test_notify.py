from app.application.notify import search_done_message


def test_message_with_new_candidates_points_to_show_vacancies():
    msg = search_done_message(["linkedin", "wellfound"], 15)
    assert "15" in msg
    assert "linkedin, wellfound" in msg
    assert "/show_vacancies" in msg


def test_message_with_zero_says_nothing_new():
    msg = search_done_message(["wellfound"], 0)
    assert "wellfound" in msg
    assert "0" not in msg          # phrased as "ничего нового", not "+0"
    assert "ничего нового" in msg.lower()
