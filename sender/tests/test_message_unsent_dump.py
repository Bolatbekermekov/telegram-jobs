"""Неотправленное сообщение LinkedIn оставляет после себя снимок экрана.

Живьём 2026-09-26, лид #1698 (профиль): «текст остался в поле ввода —
отправка не подтверждена». Прошлый такой случай (2026-08-22) оказался
переименованной кнопкой отправки, и установили это только по живой разметке.
Этот путь ничего не сохранял, и причину было не разобрать, а повторять вслепую
нельзя: если сообщение всё же ушло, человек получит второе. Разметка должна
приходить сама, из настоящего прогона.
"""
import pytest

from app.domain.channel import ChannelError
from tests.test_message_send_bubble import _Bubble, _FakePage, _send


class _DumpablePage(_FakePage):
    url = "https://www.linkedin.com/in/rachel-n-736b20211/"

    def content(self):
        return "<html>composer</html>"

    def screenshot(self, path=None, full_page=False):
        open(path, "wb").write(b"png")


def test_an_unsent_message_dumps_the_screen(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.APPLY_DEBUG_DIR", str(tmp_path))
    page = _DumpablePage([_Bubble("Rachel", send_class=None)])

    with pytest.raises(ChannelError, match="текст остался в поле ввода"):
        _send(page)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.startswith("message-unsent-") and n.endswith(".html") for n in names)
    assert any(n.startswith("message-unsent-") and n.endswith(".png") for n in names)


def test_a_dump_that_fails_does_not_hide_the_real_error(monkeypatch, tmp_path):
    """Страница без content()/screenshot() — снимок не удался, а ошибка отправки
    всё равно та же: она важнее снимка."""
    monkeypatch.setattr("app.config.APPLY_DEBUG_DIR", str(tmp_path))
    page = _FakePage([_Bubble("Rachel", send_class=None)])
    with pytest.raises(ChannelError, match="текст остался в поле ввода"):
        _send(page)
