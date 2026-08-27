"""`detect_language` здесь — дословная копия ноутбучной. Проверяем механически.

Копия, а не общий пакет, по той же причине, что `contact.py` и `vacancy_text.py`:
интейк деплоится в Vercel из `intake-bot/`, и пакет из корня репозитория в сборку
не поедет. Что делает копию безопасной — механическая проверка, что она всё ещё
копия, а не «выглядит похоже» (тот же приём, что в sender/tests/test_vacancy_mirror.py).

Здесь на кону не абстрактная чистота. Одна и та же функция отвечает на два
вопроса в разных половинах проекта: на каком языке ИНТЕЙК пишет колонку
«Вакансия» и на каком языке НОУТ пишет по ней письмо. Разъедутся пороги — и
английская вакансия получит английское описание и русское письмо, то есть ровно
ту рассинхронизацию, ради которой всё это и заводилось.

Файлы целиком не сравниваются: у ноутбучной копии есть `language_source`
(выбор между оригиналом и пересказом), а здесь — `summary_language` и правило
про пересказ. Расхождение это намеренное и описано в докстроке модуля.
"""
import inspect
from pathlib import Path

import pytest

from app.domain import message_language

_SENDER_COPY = (Path(__file__).resolve().parents[2]
                / "sender" / "app" / "domain" / "message_language.py")

# Всё, из чего складывается ответ `detect_language`: сами регулярки и порог доли
# кириллицы. Порог тут не круглое число, а измеренная граница (см. комментарий
# над ним), поэтому подправить его на одной стороне особенно легко.
_SHARED_CONSTANTS = ("_CYRILLIC = ", "_LETTER = ", "_SCORE_NOTE = ",
                     "_MIN_CYRILLIC_SHARE = ")


def _sender_source() -> str:
    if not _SENDER_COPY.exists():
        pytest.skip("sender/ рядом нет — сравнивать не с чем")
    return _SENDER_COPY.read_text(encoding="utf-8")


def test_detect_language_is_still_the_senders_function_word_for_word():
    assert inspect.getsource(message_language.detect_language) in _sender_source(), (
        "detect_language разъехалась с sender/app/domain/message_language.py. "
        "Правится одна копия — переносится в обе."
    )


def test_the_constants_it_reads_are_the_same_numbers():
    theirs = _sender_source()
    ours = Path(inspect.getfile(message_language)).read_text(encoding="utf-8")
    mirrored = [line for line in ours.splitlines()
                if line.startswith(_SHARED_CONSTANTS)]
    assert len(mirrored) == len(_SHARED_CONSTANTS)
    for line in mirrored:
        assert line in theirs, f"{line!r} — такой строки у ноутбучной копии нет"
