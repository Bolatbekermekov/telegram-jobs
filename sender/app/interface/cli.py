"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

Leads are processed in sheet order (by id, top to bottom). At most one channel
is open at a time — browser channels and the Telegram userbot can't share a
process — so ChannelSwitcher stops the current channel and starts the next
whenever the platform changes between consecutive leads. Default mode asks
send/edit/skip per lead; AUTO_SEND=true sends automatically — except leads held
for a human by send_plan.hold_reason, which get `manual` instead of a send.
Per-platform daily limits and anti-ban delays apply.
"""
from collections import Counter
import random
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app import config
from app.application.classify_role import classify_role
from app.application.cv_library import CvLibrary
from app.application.format_content import format_for_channel
from app.application.generate_message import (
    GenerateMessage, generate_for, subject_for,
)
from app.application.send_outreach import SendOutreach
from app.application.channel_switcher import ChannelSwitcher
from app.application.send_plan import (
    CONFIRM_QUIT,
    CONFIRM_SEND,
    CONFIRM_SKIP,
    confirm_action,
    dm_fallback_reason,
    has_placeholder,
    hold_reason,
    needs_vacancy_refetch,
    pause_after,
    skip_reason,
    unresolved_thread,
)
from app.domain.invite_age import expired_note, invite_expired
from app.application.answer_log import answers_note
from app.domain.sent_note import cv_note
from app.domain.outreach_history import (
    SentRecord,
    duplicate_reason,
    normalize_address,
)
from app.domain.lead import (
    STATUS_FAILED, STATUS_INVITED, STATUS_MANUAL, STATUS_NEW, STATUS_SENT, STATUS_SKIPPED,
)
from app.infrastructure.channels.registry import build_channel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.openai_role import OpenAIRoleClassifier
from app.infrastructure.sheets_repo import SheetsRepo
from app.infrastructure.vacancy_fetcher import (
    fetch_vacancy_text, is_fetchable_vacancy_url,
)

# Platforms the send loop can build a channel for. A platform missing here is a
# per-lead skip in skip_reason(), so forgetting to add one silently buries its leads.
_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound", "threads",
          "remoteok", "external"}

# Longer than the intake bot's 8s. That budget exists because the bot answers a
# Telegram webhook from a serverless function; here a human is watching a terminal
# and the alternative to waiting is not sending at all.
_REFETCH_TIMEOUT = 20.0


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _show(message: str) -> None:
    print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")


def _reset_answer_log(channel) -> None:
    """Очистить журнал ответов перед лидом.

    Канал живёт между лидами одной платформы (ChannelSwitcher закрывает его
    только при смене площадки), поэтому без очистки ответы предыдущего лида
    приклеились бы к заметке следующего — и выглядели бы как вопросы, которых
    работодатель не задавал.
    """
    log = getattr(channel, "answer_log", None)
    if log is not None:
        log.reset()


def _sent_note(channel, attachment, attach_enabled: bool) -> str:
    """Заметка отправленной строки: какое резюме ушло и что модель ответила.

    Вопросы в формах отклика отвечает LLM, и её ответы нигде не сохранялись —
    заявка уходила, а чем именно мы представились работодателю, узнать было
    неоткуда. Журнал висит на канале (registry._with_answer_log) и заполняется
    одной обёрткой вокруг общего answerer-а, поэтому работает на всех
    площадках сразу: внешние формы, LinkedIn Easy Apply, RemoteOK и hh.
    """
    note = cv_note(attachment, getattr(channel, "supports_attachment", True),
                   attach_enabled)
    log = getattr(channel, "answer_log", None)
    qa = answers_note(getattr(log, "pairs", []) if log is not None else [])
    return f"{note}\n{qa}" if qa else note


def _record_sent(repo, lead, body: str, platform: str, history=None,
                 note: str = "") -> bool:
    """Write a delivered send to the sheet; report whether the write landed.

    The message is already in the recruiter's inbox by the time this runs, so a
    failed write must not raise: a traceback here ends the run with the lead still
    `new`, and the next run delivers the same message to the same person a second
    time. That is exactly what a Sheets 502 did on lead #148. `mark_sent` already
    retries transient failures; if it still fails, the only thing left that helps
    is telling the human precisely which row to fix, unmissably.

    `history` пополняется ПЕРЕД записью в лист и независимо от её исхода: письмо
    уже у человека, и для защиты от повтора важно именно это, а не то, приняла ли
    таблица строку. Так тот же инцидент #148 внутри прогона больше не приводит
    ко второй отправке — а без этого списка два лида на один адрес в одном
    прогоне уходят оба, потому что история читается один раз до цикла.
    """
    if history is not None:
        history.append(SentRecord(platform=platform,
                                  address=normalize_address(lead.target),
                                  vacancy=lead.vacancy_context or lead.raw_text,
                                  sent_at=datetime.now(), lead_id=lead.lead_id))
    try:
        repo.mark_sent(lead, body, STATUS_SENT, note=note)
        return True
    except Exception as exc:  # noqa: BLE001 — already delivered; never raise here
        print("\n" + "!" * 62)
        print("⚠️  СООБЩЕНИЕ ОТПРАВЛЕНО, НО В ТАБЛИЦУ НЕ ЗАПИСАНО")
        print(f"   Лид #{lead.lead_id} [{platform}] → {lead.target}")
        print(f"   Причина: {type(exc).__name__}: {exc}"[:300])
        print(f"   Проставь в строке {lead.row} руками: Статус='{STATUS_SENT}' "
              "и Дату отправки.")
        print("   Иначе следующий прогон отправит это сообщение повторно.")
        print("!" * 62)
        return False


def _notify_done(platforms, added: int, timings=None) -> None:
    """Best-effort Telegram ping after a search; no-op unless token+chat configured."""
    if not (config.TELEGRAM_BOT_TOKEN and config.NOTIFY_CHAT_ID):
        return
    from app.application.notify import search_done_message
    from app.infrastructure.telegram_notify import send_telegram
    send_telegram(config.TELEGRAM_BOT_TOKEN, config.NOTIFY_CHAT_ID,
                  search_done_message(list(platforms), added, timings))


def _scored_out_store():
    """Память об отвергнутых вакансиях, или None, когда скоринг выключен."""
    if not config.RELEVANCE_ENABLED:
        return None
    from app.infrastructure.scored_out_store import ScoredOutStore
    return ScoredOutStore(config.SCORED_OUT_PATH)


def _relevance_args() -> dict:
    """Kwargs that turn on AI relevance scoring in run_search, or {} when disabled."""
    if not config.RELEVANCE_ENABLED:
        return {}
    from app.infrastructure.cv_loader import load_text_file
    from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
    return dict(
        scorer=OpenAIRelevanceScorer(config.OPENAI_API_KEY, config.OPENAI_MODEL_CHEAP,
                                     max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS),
        profile=load_text_file(config.SEARCH_PROFILE_PATH),
        threshold=config.MATCH_THRESHOLD,
        max_jobs=config.MATCH_MAX_JOBS,
        scan_limit=config.MATCH_SCAN_LIMIT,
        # Обрез потолком объявляется вслух: иначе он неотличим от «на площадке
        # ничего не нашлось», хотя непросмотренное там осталось.
        on_scan_limit=lambda scanned, kept: print(
            f"   ⚠️ упёрлись в потолок оценок ({scanned}), набрано {kept} — "
            "остальное осталось непросмотренным"),
    )


def _warn_if_apply_profile_blank() -> None:
    """Say once, up front, that external application forms have nothing to fill.

    Without this the only symptom is a note in the sheet — «не заполнены
    обязательные поля ['First Name', 'Last Name', 'Email']» — which reads like the
    ATS asked for something exotic, when in fact the profile behind it is empty
    because the file was never created. EXTERNAL_APPLY_ENABLED defaults to true,
    so this is the state a fresh checkout runs in.
    """
    if not getattr(config, "EXTERNAL_APPLY_ENABLED", False):
        return
    from app.infrastructure.apply_profile_loader import load_apply_profile
    if not load_apply_profile(config.APPLY_PROFILE_PATH).is_blank():
        return
    print(f"\n⚠️  Автоотклик включён, но профиль пуст: {config.APPLY_PROFILE_PATH}")
    print("   Формы на сайтах компаний заполнять нечем — такие лиды будут уходить")
    print("   в 'manual' с пометкой про обязательные поля, каждый прогон заново.")
    print("   Заполни: cp sender/apply_profile.example.yml sender/apply_profile.yml")
    print("   Либо выключи автоотклик: EXTERNAL_APPLY_ENABLED=false в .env\n")


def _followup_invited(repo, switcher, generator, classifier, cv_library) -> None:
    """Re-check everyone we invited without a cover letter, and finish the job.

    A lead reaches `invited` only when LinkedIn's monthly personalized-invite
    quota was spent: the connection request went out, our letter did not. Nothing
    else can move it — the person has to accept first — so every run asks the
    profile where the invite stands before touching new leads.

    accepted -> they are a 1st-degree contact now, which is the one case LinkedIn
    lets us message for free AND attach the CV to, so the outreach happens here in
    full and the lead becomes `sent`.
    pending  -> left as `invited`, но не вечно: приглашение старше
    INVITE_MAX_WAIT_DAYS закрывается как `skipped`. Ответа на него нет и взяться
    ему неоткуда, а каждый прогон тратил на него открытие профиля — лид #79
    проверялся так 17 дней подряд. Возраст берётся из «Даты отправки»; если её
    не записали, приглашение тоже закрывается (см. domain/invite_age.py).
    gone     -> declined, withdrawn or expired. `manual`, not `new`: re-inviting is
    a decision about a person who has already said no once, and that is the human's
    to make, not a thing to loop on.
    """
    invited = repo.fetch_by_status(STATUS_INVITED)
    if not invited:
        return
    print(f"\n🔁 Проверяю {len(invited)} приглашённых (ждём подтверждения)...")
    for lead in invited:
        if lead.platform != "linkedin":
            continue
        try:
            channel = switcher.for_platform("linkedin")
            state = channel.invite_state(lead.target)
        except Exception as exc:  # noqa: BLE001 — one profile must not end the run
            print(f"   #{lead.lead_id}: не смог проверить ({type(exc).__name__}) — "
                  "оставляю 'invited'.")
            continue
        if state == "pending":
            # Возраст проверяется ПОСЛЕ ответа профиля: человек мог принять
            # приглашение и на тридцатый день, и тогда письмо важнее срока.
            # И строго ДО генерации — просроченному приглашению письмо не
            # нужно, а стоит оно вызова модели.
            now, window = datetime.now(), config.INVITE_MAX_WAIT_DAYS
            if invite_expired(lead.sent_at, now, window):
                note = expired_note(lead.sent_at, now, window)
                repo.mark_status(lead, STATUS_SKIPPED, note=note)
                print(f"   #{lead.lead_id}: {note}")
                continue
            print(f"   #{lead.lead_id}: ещё не принял — жду.")
            continue
        if state == "gone":
            repo.mark_status(lead, STATUS_MANUAL,
                             note="LinkedIn: приглашение отклонено, отозвано или "
                                  "истекло — решай вручную, слать ли заново")
            print(f"   #{lead.lead_id}: приглашение больше не висит — 'manual'.")
            continue

        print(f"   #{lead.lead_id}: принял! Пишу письмо с CV...")
        # The main loop re-reads an unusable vacancy before generating; this path
        # never did, and it is the one that matters most. A lead sits in `invited`
        # for days, so by the time the letter is written the stored text is the
        # oldest we have — and leads 159 and 160 entered `invited` on 2026-07-29
        # carrying a model refusal in that column. Their letters would have been
        # composed from "Нет данных о вакансии в сообщении".
        if (needs_vacancy_refetch(lead.vacancy_context)
                and is_fetchable_vacancy_url(lead.target)):
            print(f"   #{lead.lead_id}: вакансия в таблице непригодна, "
                  "перечитываю ссылку...")
            fetched = fetch_vacancy_text(lead.target, timeout=_REFETCH_TIMEOUT)
            if not fetched:
                # Still `invited`, so the next run re-checks the invite (it stays
                # accepted) and fetches again. Better a letter one run late than a
                # letter written from a refusal.
                print(f"   #{lead.lead_id}: ссылка снова не читается — "
                      "оставляю 'invited', повторю в следующем прогоне.")
                continue
            repo.update_vacancy(lead, fetched)
            lead = replace(lead, vacancy_context=fetched)
            print(f"   #{lead.lead_id}: прочитано {len(fetched)} симв., "
                  "записал в таблицу.")

        variant = cv_library.for_role(
            classify_role(classifier, lead.vacancy_context or lead.raw_text))
        print(f"   #{lead.lead_id}: роль {variant.role}, "
              f"CV {Path(variant.pdf_path).name}")
        body, note, gen_err = generate_for(generator, lead, channel, variant.text)
        if gen_err is not None:
            print(f"   #{lead.lead_id}: не смог сгенерировать текст "
                  f"({type(gen_err).__name__}) — оставляю 'invited'.")
            continue
        # Записка проверяется наравне с письмом: на этом пути нет ни гейта
        # AUTO_SEND, ни подтверждения человеком, так что эта проверка последняя.
        if has_placeholder(body) or has_placeholder(note):
            print(f"   #{lead.lead_id}: в тексте остался [плейсхолдер] — "
                  "оставляю 'invited', перегенерирую в следующий прогон.")
            continue
        subject = subject_for(lead.vacancy_context or lead.raw_text)
        attachment = variant.pdf_path if config.ATTACH_CV else None
        content = format_for_channel(channel, body, subject, attachment, note)
        _reset_answer_log(channel)
        result = SendOutreach(channel).execute(lead, content)
        if result.ok:
            if _record_sent(repo, lead, content.body, "linkedin",
                            note=_sent_note(channel, attachment, config.ATTACH_CV)):
                print(f"   ✅ #{lead.lead_id}: письмо отправлено.")
            continue
        if result.manual:
            # "InMail only" is LinkedIn telling us they are not a contact after
            # all — so the invite is still pending, whatever the page looked like.
            # Leave the lead where it is instead of burning it as `failed`.
            print(f"   #{lead.lead_id}: писать нельзя ({result.error}) — "
                  "значит ещё не в контактах, оставляю 'invited'.")
            continue
        repo.mark_status(lead, STATUS_FAILED, note=result.error)
        print(f"   ❌ #{lead.lead_id}: {result.error}")


def run() -> None:
    print("== telegram-jobs sender (multi-platform) ==")
    _warn_if_apply_profile_blank()
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL,
                               max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS),
        cv_text, profile_text, config.SIGNATURE_TEXT,
    )
    role_classifier = OpenAIRoleClassifier(config.OPENAI_API_KEY,
                                           config.OPENAI_MODEL_CHEAP)
    cv_library = CvLibrary(config.CV_DIR, config.CV_PATH)

    switcher = ChannelSwitcher(lambda p: build_channel(p, config))
    try:
        # Before anything else: the invited leads are the ones already waiting on
        # somebody, and a run that only ever looked at `new` would never finish
        # them — including a run with no new leads at all.
        _followup_invited(repo, switcher, generator, role_classifier, cv_library)
    except Exception as exc:  # noqa: BLE001 — never let the follow-up cost the run
        print(f"⚠️  Проверка приглашённых не отработала ({type(exc).__name__}: {exc}).")

    # Кого мы уже трогали. Один запрос, до первой отправки: без этого списка
    # каждая строка со статусом `new` выглядит как первый контакт, и один и тот
    # же рекрутёр получает второе письмо (замер листа: 10 повторов на 113
    # уникальных получателей). Пополняется по ходу прогона в `_record_sent`.
    sent_history = repo.fetch_sent_history()

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        switcher.close()
        return

    mode = "АВТО (без подтверждения)" if config.AUTO_SEND else "ручной"
    print(f"Новых лидов: {len(leads)}. Режим: {mode}.")

    sent_per_platform: dict[str, int] = {}
    # Сколько лидов площадка отказалась принять из-за лимита. Раньше это было
    # множество-выключатель («площадка выбыла»); теперь прогон идёт дальше, и
    # счётчик нужен только чтобы сказать в конце, сколько людей ждут следующего
    # раза — иначе про них знает только «Заметка» в таблице.
    rate_limited: Counter[str] = Counter()
    quit_requested = False
    gen_failures = 0                     # consecutive message-generation failures

    # Strict id order: walk leads top-to-bottom. ChannelSwitcher keeps a single
    # channel open and switches only when the platform changes (Telethon and
    # Playwright can't be live at once). skip_reason() runs before any channel
    # opens, so skipped leads never churn channels.
    try:
        for lead in leads:
            if quit_requested:
                break
            platform = lead.platform

            # Раньше здесь стоял guard: первый же лимит площадки выбрасывал все её
            # оставшиеся лиды из прогона. По прямому решению владельца аккаунта
            # (2026-08-22, повторено дважды) прогон идёт до конца и пробует
            # КАЖДЫЙ лид: лимит записывается в «Заметку», статус остаётся `new`,
            # и следующий прогон берёт этих же людей снова.
            #
            # Цена решения названа и принята: запросы продолжают уходить под
            # активным спам-флагом Telegram, а это то, что превращает суточное
            # ограничение в постоянный бан. Пауза между попытками поэтому
            # сохраняется — см. pause_after.

            reason = skip_reason(lead, _KNOWN)
            if reason is not None:
                status, note = reason
                repo.mark_status(lead, status, note=note)
                print(f"⏭  Лид #{lead.lead_id} [{platform}]: {note} — пропуск.")
                continue

            if lead.platform == "threads":
                # og:description gave the intake the root post only; the rest of the
                # vacancy and the contact live in the author's self-replies, which
                # need a browser. Anonymous render: reading a public post must not
                # touch the saved session. This runs BEFORE the channel is opened —
                # resolving changes lead.platform, and opening first would raise a
                # Threads browser for a lead that should go out over Telegram.
                from app.application.resolve_threads_lead import resolve_threads_lead
                from app.domain.contact import detect_contact
                from app.infrastructure.openai_contact import OpenAIContactDetector
                from app.infrastructure.telegram_chat import is_writable_telegram_target
                from app.infrastructure.threads_session import has_valid_session
                from app.infrastructure.threads_thread import render_thread
                print("Читаю тред Threads...")
                thread_url = lead.target      # resolving replaces it with the contact
                lead, review = resolve_threads_lead(
                    lead, repo,
                    render=lambda u: render_thread(u, headless=config.BROWSER_HEADLESS),
                    # Тред тоже подписывают каналом («ещё вакансии тут: @…»), а он
                    # такой же законный ник, как человеческий. Спрашиваем Telegram —
                    # тем же ботом, которым интейк спрашивает на своей стороне.
                    detect=lambda text: detect_contact(
                        text,
                        telegram_writable=lambda t: is_writable_telegram_target(
                            t, config.TELEGRAM_BOT_TOKEN)),
                    # The writing model, not the cheap one: once per lead, and a
                    # wrong answer is a message to the wrong person.
                    llm=OpenAIContactDetector(
                        config.OPENAI_API_KEY, config.OPENAI_MODEL,
                        max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS))
                if lead.platform != platform:
                    print(f"   контакт найден: {lead.platform} → {lead.target}")
                    platform = lead.platform
                elif unresolved_thread(lead.target):
                    # Still pointing at the post, so the thread never rendered and
                    # resolving handed the lead back untouched, writing no status.
                    # Leave it that way: `new` means the next run tries again, and
                    # that retry is worth protecting — a successful render may find a
                    # real contact in a self-reply and send over Telegram, never
                    # touching the DM fallback. There is nothing to send from the root
                    # post alone, and falling through would either kill the run (no
                    # session -> ChannelUnavailable -> SystemExit) or DM the author
                    # without the vacancy text. A lead already on the DM fallback
                    # points at a handle, not a post, so re-queueing it by hand works.
                    print(f"⏭  Лид #{lead.lead_id}: тред не прочитался — "
                          "оставляю 'new', повторю в следующем прогоне.")
                    continue
                else:
                    print(f"   контакта в треде нет, буду писать автору: {lead.target}")

                hold = hold_reason(config.AUTO_SEND, review=review,
                                   contact=f"{lead.platform} → {lead.target}",
                                   source_url=thread_url)
                if hold is not None:
                    # Checked before the channel opens and before the message is
                    # generated — nothing to generate for a lead we won't send.
                    # Also before the rate-limit re-test below: the hold has to be
                    # written now, because the row is already rewritten to an
                    # ordinary platform and the next run would raise no flag.
                    status, note = hold
                    repo.mark_status(lead, status, note=note)
                    print(f"✋ Лид #{lead.lead_id}: {note}")
                    continue

                gated = dm_fallback_reason(
                    platform, lambda: has_valid_session(config.THREADS_STATE_PATH),
                    author=lead.target, source_url=thread_url)
                if gated is not None:
                    # The lead is on the DM fallback and there is no burner session.
                    # Gated HERE, before the channel opens, precisely so start() is
                    # never reached: its ChannelUnavailable meets the handler below,
                    # which ends the whole run — correct for a channel that is meant
                    # to work, but this one has no session by default and may never
                    # get one. One contactless Threads lead must not cost every other
                    # platform's leads their run. Before generation too: nothing to
                    # pay OpenAI for on a message that cannot be sent.
                    status, note = gated
                    repo.mark_status(lead, status, note=note)
                    print(f"✋ Лид #{lead.lead_id}: {note}")
                    continue

            if (needs_vacancy_refetch(lead.vacancy_context)
                    and is_fetchable_vacancy_url(lead.target)):
                # Intake reads the link the moment it arrives, from a serverless
                # function on a datacenter IP with an ~8s budget. When that read
                # comes back empty the column is left EMPTY on purpose — the
                # summariser handed a bare URL answers "не удалось извлечь
                # содержание вакансии", and storing that answer is how a recruiter
                # ends up with a letter written from it. So the laptop reads the
                # link again here: same page, no serverless clock, and usually
                # minutes-to-days later, by which time a throttle has lifted. The
                # LinkedIn post that failed on lead #121 fetched fine on retry.
                #
                # Before the channel opens and before generation, like every other
                # guard above: nothing to pay OpenAI for on a lead with no vacancy.
                print("   вакансия не сохранилась при приёме, перечитываю ссылку...")
                fetched = fetch_vacancy_text(lead.target, timeout=_REFETCH_TIMEOUT)
                if not fetched:
                    # No status. `new` means the next run tries again, exactly as
                    # an unrendered Threads thread does above — the failure is far
                    # more often the site throttling us than the link being dead,
                    # and a retry costs one GET. Generating from nothing would cost
                    # a real recruiter a nonsense letter.
                    print(f"⏭  Лид #{lead.lead_id}: ссылка снова не читается — "
                          "оставляю 'new', повторю в следующем прогоне.")
                    continue
                repo.update_vacancy(lead, fetched)
                lead = replace(lead, vacancy_context=fetched)
                print(f"   прочитано {len(fetched)} симв., записал в таблицу.")

            # Писали ли мы уже этому человеку. Стоит ЗДЕСЬ, а не рядом со
            # skip_reason, по двум причинам: у лида из Threads адрес и площадка
            # становятся окончательными только после разрешения контакта выше, а
            # текст вакансии — только после перечитывания ссылки. Сравнивать
            # раньше значит сверять не тот адрес и не тот текст.
            # Всё ещё до открытия канала: поднимать браузер ради лида, которому
            # мы не пишем, незачем.
            dup = duplicate_reason(lead, sent_history, datetime.now(),
                                   config.DUPLICATE_WINDOW_DAYS)
            if dup is not None:
                status, note = dup
                repo.mark_status(lead, status, note=note)
                print(f"⏭  Лид #{lead.lead_id} [{platform}]: {note} — пропуск.")
                continue

            try:
                channel = switcher.for_platform(platform)
            except Exception as exc:  # noqa: BLE001
                # A channel that won't start is a setup problem (dead session, Chrome
                # not running, bad config) — never the lead's fault, it was never even
                # attempted. Write no status, so this lead and every lead after it stay
                # `new`. Stop the whole run: leads are walked in sheet-id order, so the
                # queue is interleaved across platforms and limping on would drain the
                # healthy ones while the broken session goes unnoticed.
                sent_so_far = sum(sent_per_platform.values())
                print(f"\n❌ Канал '{platform}' не поднялся: {exc}")
                print(f"   Лид #{lead.lead_id} и все следующие остаются 'new'.")
                print(f"   Отправлено до остановки: {sent_so_far}. По платформам: {sent_per_platform}")
                print(f"   Причина: {type(exc).__name__}. Если это протухшая сессия — "
                      "`make login`; иначе смотри сообщение выше.")
                raise SystemExit(1) from exc
            sender = SendOutreach(channel)

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            role = classify_role(role_classifier, lead.vacancy_context or lead.raw_text)
            variant = cv_library.for_role(role)
            print(f"Роль: {variant.role}  →  {Path(variant.pdf_path).name}")
            print("-" * 60)

            print("Генерирую сообщение...")
            body, note, gen_err = generate_for(generator, lead, channel, variant.text)
            if gen_err is not None:
                # Generation hit OpenAI/network — don't crash the run (row 82).
                # Leave the lead `new` and move on; bail after 3 in a row, since
                # that means OpenAI is down and every remaining lead would fail too.
                gen_failures += 1
                print(f"⚠️  #{lead.lead_id}: не смог сгенерировать сообщение "
                      f"({type(gen_err).__name__}). Оставляю 'new'.")
                if gen_failures >= 3:
                    print("🛑 OpenAI недоступен (3 ошибки подряд) — останавливаю прогон. "
                          "Остальные лиды остаются 'new'. Проверь сеть/квоту и запусти снова.")
                    break
                continue
            gen_failures = 0
            subject = subject_for(lead.vacancy_context or lead.raw_text)
            attachment = variant.pdf_path if config.ATTACH_CV else None
            content = format_for_channel(channel, body, subject, attachment, note)

            # Записка это тоже текст, который прочитает живой человек, и шаблон в
            # ней ничем не лучше шаблона в письме.
            if config.AUTO_SEND and (has_placeholder(content.body)
                                     or has_placeholder(content.note)):
                # What the README has always promised for auto mode: a template
                # must not reach a live recruiter just because nobody was there to
                # read it. NO status — unlike a contact, the body is regenerated
                # from scratch every run, so `new` self-heals for free next time.
                print(f"⏭  Лид #{lead.lead_id}: в тексте остался [плейсхолдер] — "
                      "оставляю 'new', перегенерирую в следующий прогон.")
                continue

            if not config.AUTO_SEND:
                _show(content.body)
                if content.note:
                    # Для не-контакта в LinkedIn уходит именно записка, а не
                    # письмо. Утверждать глазами надо тот текст, который
                    # действительно отправится.
                    print("\n--- записка к запросу на контакт ---")
                    _show(content.note)
                if "[" in content.body or "[" in content.note:
                    # No editor in this loop (only s/k/q), so the advice has to be
                    # something the human can actually do: quit and re-run, because
                    # generate_body runs fresh every run and the next roll is free.
                    print("⚠️  Остался [плейсхолдер]. Редактора здесь нет: выйди по q "
                          "и запусти прогон заново — текст генерится с нуля.")
                action = confirm_action(_prompt("[s]end / [k]skip / [q]uit: "))
                if action == CONFIRM_SKIP:
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    continue
                if action == CONFIRM_QUIT:
                    print("Выход по запросу.")
                    quit_requested = True
                    break
                if action != CONFIRM_SEND:
                    # Only an explicit `s` sends — see `confirm_action`. No status:
                    # the lead stays `new` and the next run offers it again.
                    print("↩️  Отправка только по 's'. Ничего не отправлено, "
                          "лид остаётся 'new'.")
                    continue

            _reset_answer_log(channel)
            result = sender.execute(lead, content)
            if result.ok:
                if not _record_sent(
                        repo, lead, content.body, platform, sent_history,
                        note=_sent_note(channel, attachment, config.ATTACH_CV)):
                    print("🛑 Останавливаю прогон, пока строка не поправлена.")
                    break
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"(всего за прогон: {sent_per_platform[platform]}).")
            elif result.invited:
                # Запрос на контакт уходит с ЗАПИСКОЙ, а не с письмом целиком (см.
                # _invite_note в linkedin.py) — и это весь охват на этого лида:
                # письмо следом не идёт, даже если контакт примут (InvitePendingError
                # в domain/channel.py). Пишем как обычную отправку (лид не
                # повторится), но в таблицу кладём то, что реально дошло: запись
                # content.body утверждала бы, что рекрутёр получил письмо, которого
                # никто не получал.
                if not _record_sent(
                        repo, lead, content.note or content.body, platform,
                        sent_history,
                        # Файл сюда не уходит по устройству LinkedIn: к запросу
                        # на контакт прикладывается только записка.
                        note="без CV (запрос на контакт — файл не прикладывается)"):
                    print("🛑 Останавливаю прогон, пока строка не поправлена.")
                    break
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"📨 Запрос на контакт с письмом отправлен [{platform}] "
                      f"(всего за прогон: {sent_per_platform[platform]}).")
            elif result.invited_plain:
                # The request reached them, our letter did not. Not a send: park
                # as `invited` so every later run checks whether they accepted,
                # and messages them properly when they do. mark_invited, а не
                # mark_status: вместе со статусом кладётся дата, иначе ждать
                # ответа будет нечем и _followup_invited закроет лид сразу.
                repo.mark_invited(lead, note=result.error)
                print(f"🤝 Запрос на контакт БЕЗ письма [{platform}] — жду подтверждения "
                      f"(лид #{lead.lead_id} в 'invited').")
            elif result.manual:
                # Couldn't auto-apply (gate/unknown form); leave for a manual apply.
                repo.mark_status(lead, STATUS_MANUAL, note=result.error)
                print(f"✋ Нужен ручной отклик [{platform}]: {result.error}")
            elif result.rate_limited:
                # Статус остаётся `new` — ровно поэтому следующий прогон возьмёт
                # этого человека снова. Но заметка теперь ПИШЕТСЯ: раньше строка
                # молчала, и по таблице нельзя было отличить лид, до которого не
                # дошли руки, от лида, которому площадка отказала.
                #
                # `new` пишется явно, а не «оставляется»: mark_status с этим
                # статусом ничего не меняет в колонке статуса, зато кладёт
                # заметку тем же вызовом.
                rate_limited[platform] += 1
                repo.mark_status(lead, STATUS_NEW,
                                 note=result.error or "rate-limited")
                print(f"🛑 Лимит площадки '{platform}' ({result.error or 'rate-limited'}) "
                      f"— лид #{lead.lead_id} остаётся 'new', пробую следующего.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")

            if pause_after(result):
                # Одна пауза на итерацию вместо трёх копий в ветках выше:
                # правило «ждём только после того, что площадка видит как
                # сообщение» живёт в send_plan.pause_after и закреплено тестом.
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
    finally:
        switcher.close()

    total = sum(sent_per_platform.values())
    print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")
    if rate_limited:
        held = sum(rate_limited.values())
        print(f"🛑 Уперлись в лимит на {held} лид(ах): {dict(rate_limited)}. "
              "Все они остались 'new' — следующий прогон возьмёт их снова.")


def run_worker():
    """Always-on loop: heartbeat, drain «Команды», auto-search ~3×/day. Ctrl+C to stop."""
    import datetime as _dt
    import time

    import gspread
    from google.oauth2.service_account import Credentials

    from app import config
    from app.application.auto_search import due_auto_search, parse_times
    from app.application.run_search import run_search
    from app.application.worker_tick import worker_tick
    from app.domain.search_request import SEARCH_PLATFORMS, SearchRequest, platforms_for
    from app.infrastructure.search_leads_repo import SearchLeadsRepo
    from app.infrastructure.control_repo import ControlRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    main_ws = book.worksheet(config.SHEET_TAB)
    cand_ws = book.worksheet(config.CANDIDATES_TAB)
    ctrl_ws = book.worksheet(config.CONTROL_TAB)

    control = ControlRepo(ctrl_ws)
    # Порядок аргументов обратный прежнему и это не опечатка: писать теперь надо
    # в ОСНОВНУЮ вкладку, а «Кандидаты» остались источником памяти для дедупа.
    candidates = SearchLeadsRepo(main_ws, cand_ws, config.CANDIDATES_PENDING_CAP)
    searchers = {p: build_searcher(p) for p in SEARCH_PLATFORMS}

    def run_one(req):
        plats = platforms_for(req.platform)
        timings = []
        added = run_search(
            plats, searchers, candidates,
            keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
            limit=config.SEARCH_LIMIT_PER_PLATFORM,
            on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
            scored_out=_scored_out_store(),
            on_platform_done=lambda p, secs, n: timings.append((p, secs, n)),
            **_relevance_args(),
        )
        _notify_done(plats, added, timings)
        return added

    tz = _dt.timezone(_dt.timedelta(hours=config.AUTO_SEARCH_TZ_OFFSET))
    times = parse_times(config.AUTO_SEARCH_TIMES)
    last_auto = _dt.datetime.now(tz)  # seed with boot time so startup never fires
    print("worker started; polling every", config.WORKER_POLL_SECONDS, "s")
    print(f"auto-search scheduled at {config.AUTO_SEARCH_TIMES} (UTC+{config.AUTO_SEARCH_TZ_OFFSET})")
    while True:
        try:
            worker_tick(control, run_one)
            now = _dt.datetime.now(tz)
            if due_auto_search(times, last_auto, now):
                print(f"auto-search {now:%Y-%m-%d %H:%M} (UTC+{config.AUTO_SEARCH_TZ_OFFSET}): all platforms")
                run_one(SearchRequest(id="auto", platform="all", status="running"))
                last_auto = now
        except Exception as exc:  # noqa: BLE001 — survive transient sheet errors
            print("tick error:", exc)
        time.sleep(config.WORKER_POLL_SECONDS)


def run_search_once(platforms):
    """One-shot search across `platforms`, write candidates, then exit.

    Standalone process (does not touch the worker). Wellfound rides the warm
    Chrome from `make login_wellfound` via CDP; if it is closed, Wellfound is
    skipped and the other platforms still run.
    """
    from pathlib import Path

    import gspread
    from google.oauth2.service_account import Credentials

    from app.application.run_search import run_search
    from app.infrastructure.search_leads_repo import SearchLeadsRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    candidates = SearchLeadsRepo(
        book.worksheet(config.SHEET_TAB), book.worksheet(config.CANDIDATES_TAB),
        config.CANDIDATES_PENDING_CAP)
    if "hh" in platforms and not Path(config.HH_STATE_PATH).exists():
        # Manual run: log in interactively now instead of failing with a hint.
        # (The worker never gets here — it builds its searchers itself.)
        run_login_hh()
    searchers = {p: build_searcher(p) for p in platforms}
    print(f"Ищу вакансии: {', '.join(platforms)}...")
    timings = []

    def _platform_done(platform, secs, n):
        from app.application.notify import format_duration
        timings.append((platform, secs, n))
        got = "ошибка" if n is None else (f"+{n}" if n else "пусто")
        print(f"   {platform}: {format_duration(secs)}, {got}")

    added = run_search(
        platforms, searchers, candidates,
        keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
        limit=config.SEARCH_LIMIT_PER_PLATFORM,
        on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
        scored_out=_scored_out_store(),
        on_platform_done=_platform_done,
        **_relevance_args(),
    )
    print(f"Готово. Новых кандидатов записано: {added}.")
    _notify_done(platforms, added, timings)


def run_login_browser():
    """Open the LinkedIn login window once and save the session.

    LinkedIn only (NOT Telegram — that's `make login_telegram`; NOT Wellfound —
    its Cloudflare loops on a launched browser, so it's handled interactively by
    `make wellfound`). Forces a visible browser (ignores BROWSER_HEADLESS) so you
    can actually log in. After this, the worker can run headless without prompting.
    """
    from app.application.login import login_all
    from app.infrastructure.search.linkedin_search import LinkedInSearcher

    searchers = [
        LinkedInSearcher(config.LINKEDIN_STATE_PATH, headless=False,
                         people_enabled=config.LINKEDIN_PEOPLE_ENABLED),
    ]
    print("Открываю окно входа в LinkedIn. Если сессия уже есть — окно просто закроется.")
    done = login_all(searchers)
    print(f"Готово. Сессии сохранены для: {', '.join(done) or '—'}")


def run_login_wellfound():
    """Open the user's real Chrome for a one-time Wellfound login.

    Wellfound's Cloudflare loops on any browser we launch headless/automated, so
    the user passes Cloudflare + logs in by hand here. The Chrome is left RUNNING
    with a debug port; every Wellfound search (worker / make search*) attaches to
    it over CDP. Does not scrape — that is `make search_wellfound` / the worker.
    """
    import subprocess

    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    args = build_chrome_debug_args(
        config.WELLFOUND_CHROME_PROFILE, config.WELLFOUND_CDP_PORT,
        "https://wellfound.com/login")
    print("Открываю твой Chrome для Wellfound...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Пройди проверку Cloudflare и залогинься в Wellfound в открывшемся Chrome.")
    print("2) Дождись, пока загрузится твоя лента (не страница «Один момент…»).")
    input("3) Потом вернись сюда и нажми Enter — проверю сессию...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.WELLFOUND_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            page = ctx.pages[0] if ctx and ctx.pages else None
            title = page.title() if page else ""
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог проверить сессию по CDP: {exc}. Chrome всё равно оставь открытым.")
        return

    if "момент" in title.lower() or "moment" in title.lower():
        print("⚠️ Похоже, ещё на проверке Cloudflare. Доделай вход и запусти команду снова.")
    else:
        print("✅ Сессия готова. Chrome НЕ закрывай — поиск Wellfound пойдёт через него.")


def run_login_hh():
    """Log in to hh.ru in the user's REAL Chrome, then export the session.

    hh.ru's anti-fraud blocks the login request (the SMS send) in any browser
    we launch through automation — the page opens, the submit spins forever.
    So the user logs in by hand in a real Chrome started with a debug port,
    and we pull the cookies over CDP into HH_STATE_PATH. Search and send then
    reuse the saved session silently; this Chrome may be closed afterwards.
    """
    import subprocess
    from pathlib import Path

    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    if Path(config.HH_STATE_PATH).exists():
        print(f"✅ Сессия hh.ru уже есть ({config.HH_STATE_PATH}). "
              "Удали этот файл, если хочешь перелогиниться.")
        return

    args = build_chrome_debug_args(
        config.HH_CHROME_PROFILE, config.HH_CDP_PORT, "https://hh.ru/account/login")
    print("Открываю твой Chrome для входа в hh.ru...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Залогинься в hh.ru в открывшемся Chrome (телефон → SMS-код).")
    input("2) Когда увидишь себя залогиненным — вернись сюда и нажми Enter...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.HH_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            if ctx is None:
                print("⚠️ Не нашёл открытую вкладку Chrome. Запусти команду снова.")
                return
            cookie_names = {c["name"] for c in ctx.cookies("https://hh.ru")}
            if "hhtoken" not in cookie_names:
                print("⚠️ Похоже, вход не завершён (нет куки hhtoken). "
                      "Дологинься в Chrome и запусти `make login_hh` снова.")
                browser.close()  # disconnect only — leaves Chrome running
                return
            ctx.storage_state(path=config.HH_STATE_PATH)
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог забрать сессию по CDP: {exc}")
        return

    print(f"✅ Сессия сохранена в {config.HH_STATE_PATH}. Этот Chrome можно закрыть.")


def run_login_remoteok():
    """Register/log in to RemoteOK in the user's REAL Chrome, then save the session.

    Поиск по RemoteOK аккаунта не требует — он идёт по открытому JSON API. Эта
    сессия нужна ровно для отклика: кнопка Apply ведёт на /l/<id>, а тот уводит
    гостя на /sign-up?user_type=worker (проверено живьём 2026-08-03), так что
    без входа адрес формы работодателя не показывают вообще.

    Chrome настоящий, а не запущенный автоматикой: регистрация на RemoteOK идёт
    через почту или Google, а Google в автоматизированном браузере обычно
    отвечает «this browser may not be secure». После входа куки забираются по
    CDP в REMOTEOK_STATE_PATH, и этот Chrome можно закрывать.
    """
    import subprocess
    from pathlib import Path

    from app.domain.remoteok_session import is_logged_in
    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    if Path(config.REMOTEOK_STATE_PATH).exists():
        print(f"✅ Сессия RemoteOK уже есть ({config.REMOTEOK_STATE_PATH}). "
              "Удали этот файл, если хочешь перелогиниться.")
        return

    args = build_chrome_debug_args(
        config.REMOTEOK_CHROME_PROFILE, config.REMOTEOK_CDP_PORT,
        "https://remoteok.com/sign-up?user_type=worker")
    print("Открываю твой Chrome для входа в RemoteOK...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Зарегистрируйся или войди в RemoteOK в открывшемся Chrome "
          "(почта или Google).")
    print("2) Дождись, пока окажешься на сайте залогиненным.")
    input("3) Вернись сюда и нажми Enter — проверю сессию...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.REMOTEOK_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            if ctx is None:
                print("⚠️ Не нашёл открытую вкладку Chrome. Запусти команду снова.")
                return
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://remoteok.com/", wait_until="domcontentloaded",
                      timeout=30000)
            if not is_logged_in(page.content()):
                # Файл не пишем намеренно: сессия гостя неотличима от рабочей на
                # диске и вскроется только на отклике, редиректом на /sign-up.
                print("⚠️ Похоже, вход не завершён — RemoteOK всё ещё предлагает "
                      "войти. Дологинься в Chrome и запусти `make login_remoteok` "
                      "снова.")
                browser.close()  # disconnect only — leaves Chrome running
                return
            ctx.storage_state(path=config.REMOTEOK_STATE_PATH)
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог забрать сессию по CDP: {exc}")
        return

    print(f"✅ Сессия сохранена в {config.REMOTEOK_STATE_PATH}. "
          "Этот Chrome можно закрыть.")


def run_login_threads():
    """One-time interactive Threads login; saves the browser session to a file.

    Use a SEPARATE (burner) Instagram account: Threads runs on Instagram, and a
    disabled Instagram disables its Threads profile automatically.

    Only the DM fallback needs this session. Reading a thread to find the real
    contact is anonymous (infrastructure/threads_thread.py), so skipping this
    login costs nothing until a thread turns out to carry no contact at all.
    """
    from playwright.sync_api import sync_playwright

    saved = False
    # `with`, and the session pull guarded, the same way run_login_hh and
    # run_login_wellfound do it. Not defensive padding: the natural thing to do
    # once you are logged in is to CLOSE the window, and then storage_state()
    # raises on a dead context. Unguarded that is a raw Playwright traceback on
    # top of a login that actually WORKED, with the browser and the driver both
    # left running — and it is the first thing the human does after creating the
    # burner account, so it is the worst possible place to be unhelpful.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            context.new_page().goto("https://www.threads.com/login")
            print("Войди в Threads в открывшемся окне (через отдельный "
                  "Instagram-аккаунт), затем нажми Enter здесь...")
            input()
            try:
                context.storage_state(path=config.THREADS_STATE_PATH)
                saved = True
            except Exception as exc:  # noqa: BLE001
                # Nothing to recover: the cookies live in that browser context and
                # a closed window takes them with it. Say so, instead of a stack
                # trace that reads like the login itself failed.
                print(f"⚠️ Не смог забрать сессию из браузера: {exc}")
                print("   Скорее всего окно закрыли до того, как ты нажал Enter — "
                      "куки живут внутри него, и после закрытия взять их уже "
                      "неоткуда. Запусти `make login_threads` ещё раз и НЕ закрывай "
                      "окно, пока не нажмёшь Enter здесь.")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 — already gone is the normal case here
                pass

    if not saved:
        return

    # A saved state is not a session: Playwright stores whatever cookies the
    # context held, and a logged-out context yields a file with no auth in it.
    from app.infrastructure.threads_session import has_valid_session
    if has_valid_session(config.THREADS_STATE_PATH):
        print(f"✅ Сессия Threads сохранена: {config.THREADS_STATE_PATH}")
    else:
        print("⚠️ Файл сохранён, но живого `sessionid` в нём нет — вход не удался. "
              "Проверь, что действительно залогинился, и повтори.")


def run_login_all():
    """One command: log in to every platform, skipping ones with a live session.

    Telegram runs the QR script in a subprocess (its own asyncio flow); wellfound
    goes last because its Chrome must stay open for CDP.
    """
    import subprocess
    import sys
    from pathlib import Path

    from app.application.login import (
        LOGIN_ORDER,
        cdp_alive,
        platforms_needing_login,
        telegram_session_file,
    )

    from app.infrastructure.linkedin_session import has_valid_session
    from app.infrastructure.threads_session import (
        has_valid_session as threads_has_valid_session,
    )

    has_session = {
        "telegram": Path(telegram_session_file(config.SESSION_PATH)).exists(),
        # A LinkedIn state file can exist yet be logged out (no live li_at); that
        # is not a session to skip — re-login instead.
        "linkedin": has_valid_session(config.LINKEDIN_STATE_PATH),
        "hh": Path(config.HH_STATE_PATH).exists(),
        # RemoteOK: файл пишется только после проверки страницы
        # (run_login_remoteok), так что его наличие уже значит живой вход.
        "remoteok": Path(config.REMOTEOK_STATE_PATH).exists(),
        # Same trap as LinkedIn: a state file without a live sessionid is a guest.
        "threads": threads_has_valid_session(config.THREADS_STATE_PATH),
        "wellfound": cdp_alive(config.WELLFOUND_CDP_URL),
    }
    todo = platforms_needing_login(has_session)
    for p in LOGIN_ORDER:
        if p not in todo:
            print(f"✅ {p}: сессия уже есть, пропускаю.")
    if not todo:
        print("Все платформы уже залогинены.")
        return

    def _login_telegram():
        qr_script = Path(__file__).resolve().parents[2] / "qr_login.py"
        subprocess.call([sys.executable, str(qr_script)])

    actions = {"telegram": _login_telegram, "linkedin": run_login_browser,
               "hh": run_login_hh, "remoteok": run_login_remoteok,
               "threads": run_login_threads,
               "wellfound": run_login_wellfound}
    for p in todo:
        print(f"\n🔑 {p}: вход...")
        try:
            actions[p]()
        except Exception as exc:  # noqa: BLE001 — one platform must not stop the rest
            print(f"⚠️ {p}: {exc}")
    print(f"\nГотово. Логин выполнялся для: {', '.join(todo)}.")


if __name__ == "__main__":
    run()
