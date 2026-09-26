"""Чтение кода из почты подключено в одном месте — в зависимостях внешних форм.

Пять каналов (ATS, LinkedIn, Indeed, RemoteOK, внешние) зовут `deps["fn"]` с
одинаковыми аргументами, поэтому код из письма едет внутри самой функции
(`partial`), и ни один канал править не нужно.
"""
from types import SimpleNamespace

from app.infrastructure.channels import registry


def _cfg(**over):
    base = dict(EXTERNAL_APPLY_ENABLED=True, SMTP_HOST="smtp.gmail.com", SMTP_PORT=465,
                SMTP_USER="me@gmail.com", SMTP_PASSWORD="app-pass", EMAIL_FROM_NAME="Me",
                APPLY_PROFILE_PATH="no-such-profile.yml", CONTACTS=None, CV_PATH="cv.pdf", LLM_API_KEY="",
                APPLY_DRY_RUN=False, EMAILED_CODE_ENABLED=True)
    base.update(over)
    return SimpleNamespace(**base)


def _code_source(deps):
    return getattr(deps["fn"], "keywords", {}).get("code_source")


def test_with_a_gmail_box_the_forms_read_the_code():
    assert _code_source(registry._external_apply_deps(_cfg())) is not None


def test_the_owner_can_switch_it_off():
    assert _code_source(registry._external_apply_deps(_cfg(EMAILED_CODE_ENABLED=False))) is None


def test_without_a_mailbox_nothing_is_read():
    assert _code_source(registry._external_apply_deps(_cfg(SMTP_USER=""))) is None
