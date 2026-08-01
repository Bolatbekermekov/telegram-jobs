"""Словарь ролей: он один на весь проект, разъехаться ему нельзя."""
from app.domain.cv_role import (
    DEFAULT_ROLE,
    ROLE_DESCRIPTIONS,
    ROLES,
    normalize_role,
)


def test_roles_are_exactly_the_eight_agreed():
    assert ROLES == ("ai", "backend-node", "backend-go", "backend-python",
                     "frontend", "mobile", "qa", "fullstack")


def test_default_role_is_in_the_list():
    assert DEFAULT_ROLE == "fullstack"
    assert DEFAULT_ROLE in ROLES


def test_every_role_has_a_description_for_the_prompt():
    """Классификатор выбирает по описанию, поэтому роль без описания слепа."""
    assert set(ROLE_DESCRIPTIONS) == set(ROLES)
    assert all(desc.strip() for desc in ROLE_DESCRIPTIONS.values())


def test_normalize_accepts_a_valid_role():
    assert normalize_role("qa") == "qa"


def test_normalize_is_forgiving_about_shape():
    """Модель вернёт то, что вернёт: регистр, пробелы, подчёркивание вместо дефиса."""
    assert normalize_role("  QA  ") == "qa"
    assert normalize_role("Backend_Node") == "backend-node"
    assert normalize_role("BACKEND-GO") == "backend-go"


def test_normalize_falls_back_on_anything_unknown():
    assert normalize_role("devops") == DEFAULT_ROLE
    assert normalize_role("") == DEFAULT_ROLE
    assert normalize_role(None) == DEFAULT_ROLE
