"""«Apply», за которым вход или регистрация, — это не «форма не распознана».

Живьём 2026-09-14, Alignerr (лид #1194, из LinkedIn): на странице вакансии
`www.alignerr.com/jobs/<id>` нет ни одного поля, а обе кнопки «Apply now» —
ссылки на `app.alignerr.com/signin?job=<id>` и `app.alignerr.com/signup`.
Адрес самой страницы при этом остаётся адресом вакансии, пароля на ней нет —
прежняя проверка входа молчала, и в таблицу уходило «форма не распознана».
Аккаунтов мы не заводим, отклик тут всё равно ручной, но причина в заметке
должна быть настоящей.
"""
import pytest

from app.infrastructure.channels.external_apply import _requires_signup_or_login


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    p.stop()


# Разметка по живой странице Alignerr: вход в шапке и две кнопки-ссылки отклика.
_ALIGNERR_JOB = """
<header><a href="https://app.alignerr.com/signin">Sign in</a></header>
<main>
  <h1>Software Engineer (AI Training)</h1>
  <a href="https://app.alignerr.com/signup">Apply Now</a>
  <p>About the role</p>
  <a href="https://app.alignerr.com/signin?job=d7a134c0">Apply now</a>
</main>
"""

# Обычная вакансия: вход в шапке есть почти у всех сайтов, а «Apply» ведёт к форме.
_ORDINARY_JOB = """
<header><a href="https://jobs.acme.com/login">Sign in</a></header>
<main>
  <h1>AI Engineer</h1>
  <a href="https://jobs.acme.com/jobs/42/apply">Apply for this job</a>
</main>
"""


def test_apply_links_leading_to_sign_in_mean_an_account_is_required(page):
    page.set_content(f"<body>{_ALIGNERR_JOB}</body>")
    assert _requires_signup_or_login(page) is True


def test_a_sign_in_link_in_the_header_is_not_a_gated_apply(page):
    """Смотрим только на ссылки отклика: вход в шапке ничего не говорит о том,
    нужен ли аккаунт, чтобы подать заявку."""
    page.set_content(f"<body>{_ORDINARY_JOB}</body>")
    assert _requires_signup_or_login(page) is False
