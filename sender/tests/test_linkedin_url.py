from app.infrastructure.search.linkedin_search import build_jobs_url


def test_url_has_keywords_location_and_defaults():
    url = build_jobs_url("AI Engineer", "Worldwide")
    assert "keywords=AI+Engineer" in url
    assert "location=Worldwide" in url
    # f_WT (формат работы) больше НЕ вшит: человек готов к релокации, а
    # фильтр «только удалёнка» отсекал 60–75% вакансий.
    assert "f_WT" not in url
    assert "f_E=1%2C2%2C3" in url     # Intern + Junior + Junior+
    assert "f_TPR=r604800" in url     # 7 days


def test_empty_experience_omits_level_filter():
    url = build_jobs_url("Dev", "Worldwide", experience="")
    assert "f_E=" not in url


def test_custom_recency_passes_through():
    url = build_jobs_url("Dev", "Worldwide", posted_within="r86400")
    assert "f_TPR=r86400" in url
