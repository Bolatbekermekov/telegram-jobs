"""Страница за проверкой на бота или с отказом в доступе — это не «форма не распознана».

Живьём 2026-09-13, прогон 65 лидов:
    Betterteam (лиды #1154, #1157) — заголовок «Just a moment...», iframe
      challenges.cloudflare.com/…/turnstile: проверка Cloudflare. Проходить её
      автоматически — обходить защиту от ботов, и делать этого бот не будет.
    TalentRecruit (лид #1161) — страница «403 Forbidden».
Обе в таблицу легли «форма не распознана», и человек шёл искать поломку в
распознавании форм, которой нет. Причина должна называться прямо.
"""
from app.domain.page_gone import page_block_reason


def test_a_cloudflare_challenge_is_named():
    frames = ["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/ov2/av0"]
    assert page_block_reason("Just a moment...", "Verifying you are human.", frames) == "cloudflare"


def test_the_challenge_title_alone_is_enough():
    assert page_block_reason("Just a moment...", "", []) == "cloudflare"


def test_a_forbidden_page_is_named():
    assert page_block_reason("403 Forbidden", "403 Forbidden\nnginx", []) == "forbidden"


def test_an_ordinary_page_is_not_blocked():
    assert page_block_reason("Senior Engineer - Acme", "Apply for this job. 403 open roles.", []) == ""
