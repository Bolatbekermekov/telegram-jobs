from app.domain.candidate import (
    Candidate, CANDIDATE_COLUMNS, normalize_url, linkedin_action_for_url,
    is_company_actor, post_actor_profile_url, post_author_profile_url,
    posting_identity,
)


def test_candidate_columns_order():
    assert CANDIDATE_COLUMNS == [
        "id", "Платформа", "Тип", "URL", "Title", "Company",
        "Salary", "Location", "Summary", "Статус", "Дата",
    ]


def test_normalize_url_lowercases_host_strips_query_fragment_slash():
    a = normalize_url("HTTPS://www.LinkedIn.com/jobs/view/123/?ref=abc#top")
    b = normalize_url("https://www.linkedin.com/jobs/view/123")
    assert a == b == "https://www.linkedin.com/jobs/view/123"


def test_normalize_url_handles_trailing_slash_only():
    assert normalize_url("https://wellfound.com/jobs/9/") == "https://wellfound.com/jobs/9"


def test_linkedin_action_for_url():
    assert linkedin_action_for_url("https://www.linkedin.com/jobs/view/1") == "easy_apply"
    assert linkedin_action_for_url("https://www.linkedin.com/in/jane-doe") == "dm"


def test_linkedin_action_for_url_detects_posts():
    assert linkedin_action_for_url(
        "https://www.linkedin.com/posts/ilyas-mustafin-44b575144_abc-activity-747-CmC7/") == "post"
    assert linkedin_action_for_url(
        "https://www.linkedin.com/feed/update/urn:li:activity:747/") == "post"


def test_post_author_profile_url_extracts_author():
    url = ("https://www.linkedin.com/posts/ilyas-mustafin-44b575144_"
           "%D0%B2%D1%81%D0%B5%D0%BC-activity-7477653261932650496-CmC7/"
           "?utm_source=share&utm_medium=member_ios")
    assert post_author_profile_url(url) == \
        "https://www.linkedin.com/in/ilyas-mustafin-44b575144/"


def test_post_author_profile_url_none_when_unparseable():
    assert post_author_profile_url(
        "https://www.linkedin.com/feed/update/urn:li:activity:747/") is None
    assert post_author_profile_url("https://www.linkedin.com/in/jane") is None


def test_post_author_profile_url_none_for_a_hashtag_share_link():
    """Прогон 2026-08-27: оба поста-лида в очереди пришли ссылкой вида
    `/posts/<хештеги>-share-<id>-<хеш>/` — вместо ника автора там теги, и оба
    упали «не удалось определить автора». Из адреса его взять НЕЛЬЗЯ, и правило
    честно отвечает пусто; автора снимают со страницы (post_actor_profile_url)."""
    assert post_author_profile_url(
        "https://www.linkedin.com/posts/hiring-frontendengineer-"
        "frontenddeveloper-share-7495708880526544896-xQBG/") is None
    assert post_author_profile_url(
        "https://www.linkedin.com/posts/hiring-react-remotejobs-"
        "share-7494732972525260800--qGz/") is None


def test_post_actor_profile_url_drops_the_mini_profile_query():
    """Снято живьём 2026-08-27 со страницы поста: у ссылки на автора-человека
    к нику приклеен `?miniProfileUrn=…`. Открывать профиль надо чистым."""
    assert post_actor_profile_url(
        "https://www.linkedin.com/in/chrisguindon?miniProfileUrn=urn%3Ali%3A"
        "fsd_profile%3AACoAAANmiAEBHnimmxw__4Q-byyqxFgLRfHJWI8"
    ) == "https://www.linkedin.com/in/chrisguindon/"


def test_post_actor_profile_url_takes_a_relative_href():
    # На странице соседние ссылки на профили — относительные; актор сегодня
    # абсолютный, но полагаться на это незачем.
    assert post_actor_profile_url("/in/jane-doe/") == \
        "https://www.linkedin.com/in/jane-doe/"


def test_a_company_page_is_not_a_person_to_write_to():
    """Оба упавших поста 2026-08-27 подписаны СТРАНИЦАМИ компаний
    (`/company/eliza-black/posts`, `/company/hr-diya-l2/posts`). У страницы нет
    ни «Сообщение», ни «Установить контакт» — писать там некому."""
    href = "https://www.linkedin.com/company/eliza-black/posts"
    assert post_actor_profile_url(href) is None
    assert is_company_actor(href)


def test_a_showcase_page_counts_as_a_company_too():
    # Витрина: снята живьём в репостах — `/showcase/alpha-omega-oss/posts`.
    href = "https://www.linkedin.com/showcase/alpha-omega-oss/posts"
    assert post_actor_profile_url(href) is None
    assert is_company_actor(href)


def test_an_unreadable_actor_href_is_neither_person_nor_company():
    # Пусто и «что-то третье» — это не «компания», а «не смог прочитать»:
    # канал на них отвечает разными исходами, и путать их нельзя.
    assert post_actor_profile_url("") is None
    assert not is_company_actor("")
    assert not is_company_actor("https://www.linkedin.com/feed/hashtag/hiring/")


def test_candidate_is_a_dataclass_with_fields():
    c = Candidate(platform="linkedin", kind="job", url="u", title="t",
                  company="c", salary="", location="Remote", summary="s")
    assert c.platform == "linkedin" and c.kind == "job" and c.salary == ""


# --- опознание объявления помимо адреса ---------------------------------------

def test_posting_identity_ignores_case_and_extra_spaces():
    assert (posting_identity("AI-разработчик  (Python)", "LLC СП Солюшен")
            == posting_identity("ai-разработчик (python)", "llc сп солюшен"))


def test_posting_identity_separates_employers():
    assert posting_identity("Frontend-разработчик", "Foxible") != \
           posting_identity("Frontend-разработчик", "Другая компания")


def test_posting_identity_separates_roles():
    assert posting_identity("Frontend-разработчик", "Foxible") != \
           posting_identity("Fullstack-разработчик", "Foxible")


def test_posting_identity_needs_both_halves():
    """Пустая половина ключа не образует: иначе безымянные карточки схлопнутся."""
    assert posting_identity("", "Foxible") is None
    assert posting_identity("Разработчик", "") is None
    assert posting_identity("  ", "  ") is None
