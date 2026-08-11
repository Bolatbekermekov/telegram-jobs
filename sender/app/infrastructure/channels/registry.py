"""Map a platform string to a freshly-built (not yet started) OutreachChannel."""
from app.application.answer_log import AnswerLog, wrap_answerer
from app.application.hh_questions import canonicalize_answers
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.remoteok import RemoteOKChannel
from app.infrastructure.channels.telegram import TelegramChannel
from app.infrastructure.channels.threads import ThreadsChannel
from app.infrastructure.channels.wellfound import WellfoundChannel


def _hh_answerer(config):
    """Callable that answers hh employer questions with the AI, or None if no
    OpenAI key is configured (then such vacancies are skipped, not answered)."""
    api_key = getattr(config, "OPENAI_API_KEY", "")
    if not api_key:
        return None

    def answer(questions, vacancy_context):
        from app.infrastructure.cv_loader import load_cv_text, load_text_file
        from app.infrastructure.openai_client import OpenAIMessageGenerator
        ai = OpenAIMessageGenerator(api_key, config.OPENAI_MODEL,
                                    max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS)
        cv = load_cv_text(config.CV_PATH)
        profile = load_text_file(config.PROFILE_PATH)
        answers = ai.answer_questions(cv, profile, vacancy_context, questions)
        # Один и тот же ник во всех ответах — тот, что стоит в подписи. Правка
        # здесь, а не в каждом канале: этот answerer обслуживает и hh, и внешние
        # формы, и LinkedIn Easy Apply. Журнал ответов вешается снаружи, поэтому
        # в «Заметку» попадёт уже исправленное — то, что реально ушло.
        return canonicalize_answers(answers, getattr(config, "CONTACTS", None))

    return answer


def _external_apply_deps(config, log=None):
    if not getattr(config, "EXTERNAL_APPLY_ENABLED", False):
        return {"enabled": False, "fn": None}
    from app.infrastructure.apply_profile_loader import load_apply_profile
    from app.infrastructure.channels.external_apply import external_apply
    from app.application.generate_message import subject_for
    email_channel = None
    if getattr(config, "SMTP_HOST", "") and getattr(config, "SMTP_USER", ""):
        email_channel = EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                                     config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    return {
        "enabled": True,
        "fn": external_apply,
        "profile": load_apply_profile(config.APPLY_PROFILE_PATH,
                                      getattr(config, "CONTACTS", None)),
        "cv_path": config.CV_PATH,
        # generic CV+profile AI answerer, обёрнутый журналом ответов
        "answerer": wrap_answerer(_hh_answerer(config), log) if log else _hh_answerer(config),
        "dry_run": getattr(config, "APPLY_DRY_RUN", False),
        "email_channel": email_channel,
        "subject_maker": subject_for,
    }


def _with_answer_log(channel, answerer_holder):
    """Повесить журнал ответов на канал, чтобы его прочитал цикл отправки.

    Атрибутом, а не через протокол: канал, который вопросов не задаёт, о
    журнале знать не обязан — ровно как с supports_attachment.
    """
    channel.answer_log = answerer_holder
    return channel


def build_channel(platform: str, config):
    if platform == "telegram":
        return TelegramChannel(config.SESSION_PATH, config.TELEGRAM_API_ID,
                               config.TELEGRAM_API_HASH)
    if platform == "email":
        return EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                            config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    if platform == "hh":
        log = AnswerLog()
        return _with_answer_log(HeadHunterChannel(
            config.HH_STATE_PATH, config.BROWSER_HEADLESS,
            wrap_answerer(_hh_answerer(config), log),
            getattr(config, "HH_ATTACH_CV_IN_CHAT", False),
            getattr(config, "HH_SUBMIT_TIMEOUT_SECONDS", 100) * 1000), log)
    if platform == "linkedin":
        log = AnswerLog()
        return _with_answer_log(LinkedInChannel(
            config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS,
            external_apply_deps=_external_apply_deps(config, log)), log)
    if platform == "wellfound":
        # Apply runs through the warm CDP Chrome from `make login_wellfound`
        # (past Cloudflare + logged in), not a launched browser off storage_state.
        return WellfoundChannel(config.WELLFOUND_CDP_URL,
                                dry_run=getattr(config, "APPLY_DRY_RUN", False))
    if platform == "remoteok":
        # Свой браузер с сохранённой сессией, а не CDP как у Wellfound: у
        # RemoteOK нет Cloudflare, и сессия работает в headless (проверено
        # живьём). Отклик целиком внешний — своей формы у площадки нет.
        log = AnswerLog()
        return _with_answer_log(RemoteOKChannel(
            config.REMOTEOK_STATE_PATH, headless=config.BROWSER_HEADLESS,
            external_apply_deps=_external_apply_deps(config, log)), log)
    if platform == "threads":
        # The DM fallback: only reached when the thread carried no contact at all.
        return ThreadsChannel(config.THREADS_STATE_PATH, config.BROWSER_HEADLESS)
    raise ValueError(f"unknown platform: {platform}")
