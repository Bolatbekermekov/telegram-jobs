"""Use-case: generate a personalized outreach message for a lead."""
from app.domain.contacts import Contacts, canonicalize, parse_contacts
from app.domain.lead import Lead
from app.domain.message_language import detect_language
from app.domain.signature import localize_signature


class GenerateMessage:
    def __init__(self, ai, cv_text: str, profile_text: str, signature_text: str = "",
                 contacts: Contacts | None = None):
        # ai: object with .generate(cv_text, profile_text, vacancy_context) -> str
        self._ai = ai
        self._cv_text = cv_text
        self._profile_text = profile_text
        self._signature_text = signature_text.strip()
        # Контакты по умолчанию берутся из той же подписи: она и есть их
        # источник правды (app/domain/contacts.py). Модель видит CV, где записан
        # СТАРЫЙ телеграм-ник, и переносит его в текст — в письме оказывались два
        # разных ника сразу, наш в подписи и чужой в теле.
        self._contacts = contacts if contacts is not None else parse_contacts(
            self._signature_text)
        # cv_text здесь это запасной вариант: реальное CV выбирается под роль
        # лида и приходит в execute/execute_with_note отдельным аргументом.

    def _signature_for(self, lead: Lead) -> str:
        """Подпись на языке письма.

        Модель её не пишет — это фиксированный блок из signature.txt, который
        клеится уже после генерации, поэтому language_rule на него не
        действует. Английское письмо уезжало с русским «С уважением, Bolatbek»
        в конце: единственное русское слово в остальном английском тексте.

        Язык берётся из ТОГО ЖЕ текста, из которого его берёт правило для
        модели (openai_client), — иначе письмо и подпись разъедутся.
        """
        return localize_signature(
            self._signature_text,
            detect_language(lead.vacancy_context or lead.raw_text))

    def execute(self, lead: Lead, cv_text: str = "") -> str:
        body = self._ai.generate(
            cv_text=cv_text or self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
        )
        signature = self._signature_for(lead)
        if signature:
            body = f"{body}\n\n{signature}"
        return canonicalize(body, self._contacts)

    def execute_with_note(self, lead: Lead, note_limit: int,
                          cv_text: str = "") -> tuple[str, str]:
        """(письмо, записка) для канала, у которого есть отдельная короткая форма.

        Подпись приклеивается ТОЛЬКО к письму: в записку на ~200 символов она не
        влезает, а LinkedIn рядом с приглашением и так показывает, кто пишет.
        """
        letter, note = self._ai.generate_with_note(
            cv_text=cv_text or self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
            note_limit=note_limit,
        )
        signature = self._signature_for(lead)
        if signature:
            letter = f"{letter}\n\n{signature}"
        # Записка тоже: её читает тот же человек, и ник в ней такой же наш.
        return canonicalize(letter, self._contacts), canonicalize(note, self._contacts)


def generate_body(generator, lead, cv_text: str = ""):
    """(body, None) on success; (None, exc) if generation failed.

    Message generation calls out to OpenAI, so a network blip or an API outage
    raises mid-run. Letting that propagate aborts the ENTIRE send loop and strands
    every remaining lead (row 82 killed a 27-lead run on one DNS hiccup). A failed
    generation is transient and per-lead, so return the error for the caller to log
    and skip — the lead stays `new` and retries next run. Only real errors are
    absorbed; KeyboardInterrupt/SystemExit (BaseException) still stop the run.

    cv_text уходит генератору, только если его действительно передали: у некоторых
    вызывающих (например, у followup-цикла по принятым приглашениям) execute()
    собственных лёгких подмен generator параметр cv_text не принимает, и лишний
    позиционный аргумент такой вызов сломает."""
    try:
        if cv_text:
            return generator.execute(lead, cv_text), None
        return generator.execute(lead), None
    except Exception as exc:  # noqa: BLE001 — a generation failure must not abort the run
        return None, exc


def generate_for(generator, lead, channel, cv_text: str = ""):
    """(body, note, err) для конкретного канала.

    Канал, объявивший `note_limit`, получает два текста за один запрос; любой
    другой идёт прежним однотекстовым путём и о существовании записки не знает.
    Проверка по атрибуту, а не по имени канала: список каналов растёт, и правка
    ради LinkedIn не должна требовать помнить про этот if в каждом новом.

    Ошибки возвращаются, а не бросаются, ровно по той же причине, что и в
    `generate_body`: обвал OpenAI не должен уносить весь прогон.

    cv_text уходит в execute_with_note() так же осторожно, как в generate_body —
    см. её докстроку: не у всех подмен generator есть этот параметр.
    """
    note_limit = getattr(channel, "note_limit", None)
    if not note_limit:
        body, err = generate_body(generator, lead, cv_text)
        return body, "", err
    try:
        if cv_text:
            body, note = generator.execute_with_note(lead, note_limit, cv_text)
        else:
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
