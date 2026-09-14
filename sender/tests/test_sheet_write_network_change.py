"""Смена сети посреди прогона не должна останавливать рассылку.

Живьём 2026-09-14 (лид #1195): ноутбук перешёл с раздачи телефона
(172.20.10.x) на Wi-Fi (192.168.8.x). Отклик ушёл, а `mark_sent` упал на
`ConnectionError: ('Connection aborted.', OSError(49, "Can't assign requested
address"))` — запись такие ошибки не повторяла вовсе. Прогон остановился на
пятом лиде из 72, строку пришлось проставлять руками.

Запись в этом репозитории — всегда перезапись конкретных ячеек (update и
batch_update по адресам), поэтому повтор после дошедшего запроса кладёт те же
значения в те же ячейки и дубля не создаёт. Повторять её при обрыве соединения
безопасно, а ждать сеть стоит дольше пары секунд.
"""
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.infrastructure import sheets_repo as sr


def _network_gone():
    return RequestsConnectionError(
        ("Connection aborted.", OSError(49, "Can't assign requested address")))


def test_a_write_survives_half_a_minute_without_network():
    slept = []

    def op():
        if sum(slept) < 30:          # сеть возвращается через полминуты
            raise _network_gone()
        return "ok"

    assert sr._with_retry(op, sleep=slept.append) == "ok"


def test_a_write_still_gives_up_when_the_network_never_comes_back():
    def op():
        raise _network_gone()

    with pytest.raises(RequestsConnectionError):
        sr._with_retry(op, sleep=lambda s: None)
