"""Запомнить, что модель ответила работодателю, — чтобы это попало в лист.

Вопросы в формах отклика отвечает LLM, и её ответы нигде не сохранялись:
заявка уходила, а чем именно мы представились работодателю, узнать было
неоткуда.

Перехват сделан ОДИН на все площадки: и внешние формы (external_apply,
LinkedIn Easy Apply, RemoteOK), и hh зовут один и тот же `answerer` —
достаточно обернуть его, и проводка через каждый канал не нужна.
"""

# Потолок на всю заметку: ячейка листа не резиновая, а читать её будет человек
# глазами. Что не влезло — обрезается, вопросы важнее хвоста ответа.
_MAX_NOTE_CHARS = 3000
_MAX_ANSWER_CHARS = 400


class AnswerLog:
    """Пары «вопрос — ответ» за один отклик."""

    def __init__(self):
        self.pairs: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Перед каждым лидом: ответы прошлого не должны попасть в его заметку."""
        self.pairs = []

    def record(self, questions, answers) -> None:
        """`answers` — то, что вернул answerer: {id: {"text"|"choice"}}."""
        by_id = {str(q.get("id")): q for q in (questions or [])}
        for qid, ans in (answers or {}).items():
            q = by_id.get(str(qid))
            if q is None or not isinstance(ans, dict):
                continue
            prompt = str(q.get("prompt") or "").strip()
            if "text" in ans:
                value = str(ans.get("text") or "").strip()
            else:
                # Индекс в заметке не говорит ничего — подставляем текст варианта.
                options = q.get("options") or []
                idx = ans.get("choice")
                value = (str(options[idx]).strip()
                         if isinstance(idx, int) and 0 <= idx < len(options)
                         else str(idx))
            if prompt:
                self.pairs.append((prompt, value))


def wrap_answerer(answerer, log: AnswerLog):
    """Тот же answerer, но запоминающий пары. Поведение не меняется.

    Ошибка самого answerer-а пробрасывается как есть: запись ответов не должна
    ни ломать отклик, ни прятать его причину. А вот сбой самой записи отклик
    ронять не имеет права — ответы это диагностика, а не часть заявки.
    """
    if answerer is None:
        return None

    def answering(questions, vacancy_context):
        answers = answerer(questions, vacancy_context)
        try:
            log.record(questions, answers)
        except Exception:  # noqa: BLE001 — заметка не стоит упавшего отклика
            pass
        return answers

    return answering


def answers_note(pairs) -> str:
    """Пары «вопрос — ответ» одной строкой для колонки «Заметка»."""
    lines = []
    for prompt, value in pairs or []:
        answer = str(value or "").strip()
        if len(answer) > _MAX_ANSWER_CHARS:
            answer = answer[:_MAX_ANSWER_CHARS - 1].rstrip() + "…"
        lines.append(f"В: {str(prompt).strip()} — О: {answer}")
    note = "\n".join(lines)
    return note if len(note) <= _MAX_NOTE_CHARS else note[:_MAX_NOTE_CHARS - 1] + "…"
