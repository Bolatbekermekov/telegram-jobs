"""Use-case: generate a personalized outreach message for a lead."""
from app.domain.lead import Lead


class GenerateMessage:
    def __init__(self, ai, cv_text: str, profile_text: str, signature_text: str = ""):
        # ai: object with .generate(cv_text, profile_text, vacancy_context) -> str
        self._ai = ai
        self._cv_text = cv_text
        self._profile_text = profile_text
        self._signature_text = signature_text.strip()

    def execute(self, lead: Lead) -> str:
        body = self._ai.generate(
            cv_text=self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
        )
        if self._signature_text:
            return f"{body}\n\n{self._signature_text}"
        return body

    def execute_with_note(self, lead: Lead, note_limit: int) -> tuple[str, str]:
        """(письмо, записка) для канала, у которого есть отдельная короткая форма.

        Подпись приклеивается ТОЛЬКО к письму: в записку на ~200 символов она не
        влезает, а LinkedIn рядом с приглашением и так показывает, кто пишет.
        """
        letter, note = self._ai.generate_with_note(
            cv_text=self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
            note_limit=note_limit,
        )
        if self._signature_text:
            letter = f"{letter}\n\n{self._signature_text}"
        return letter, note


def generate_body(generator, lead):
    """(body, None) on success; (None, exc) if generation failed.

    Message generation calls out to OpenAI, so a network blip or an API outage
    raises mid-run. Letting that propagate aborts the ENTIRE send loop and strands
    every remaining lead (row 82 killed a 27-lead run on one DNS hiccup). A failed
    generation is transient and per-lead, so return the error for the caller to log
    and skip — the lead stays `new` and retries next run. Only real errors are
    absorbed; KeyboardInterrupt/SystemExit (BaseException) still stop the run."""
    try:
        return generator.execute(lead), None
    except Exception as exc:  # noqa: BLE001 — a generation failure must not abort the run
        return None, exc


def generate_for(generator, lead, channel):
    """(body, note, err) для конкретного канала.

    Канал, объявивший `note_limit`, получает два текста за один запрос; любой
    другой идёт прежним однотекстовым путём и о существовании записки не знает.
    Проверка по атрибуту, а не по имени канала: список каналов растёт, и правка
    ради LinkedIn не должна требовать помнить про этот if в каждом новом.

    Ошибки возвращаются, а не бросаются, ровно по той же причине, что и в
    `generate_body`: обвал OpenAI не должен уносить весь прогон.
    """
    note_limit = getattr(channel, "note_limit", None)
    if not note_limit:
        body, err = generate_body(generator, lead)
        return body, "", err
    try:
        body, note = generator.execute_with_note(lead, note_limit)
        return body, note, None
    except Exception as exc:  # noqa: BLE001 — как generate_body: пропуск лида, не крах
        return None, "", exc


def subject_for(vacancy_context: str) -> str:
    """A short email subject derived from the vacancy text (first non-empty line)."""
    for line in vacancy_context.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return "Заявка на вакансию"
