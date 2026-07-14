"""Map a platform string to a freshly-built (not yet started) OutreachChannel."""
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.telegram import TelegramChannel
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
        ai = OpenAIMessageGenerator(api_key, config.OPENAI_MODEL)
        cv = load_cv_text(config.CV_PATH)
        profile = load_text_file(config.PROFILE_PATH)
        return ai.answer_questions(cv, profile, vacancy_context, questions)

    return answer


def _external_apply_deps(config):
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
        "profile": load_apply_profile(config.APPLY_PROFILE_PATH),
        "cv_path": config.CV_PATH,
        "answerer": _hh_answerer(config),      # generic CV+profile AI answerer
        "dry_run": getattr(config, "APPLY_DRY_RUN", False),
        "email_channel": email_channel,
        "subject_maker": subject_for,
    }


def build_channel(platform: str, config):
    if platform == "telegram":
        return TelegramChannel(config.SESSION_PATH, config.TELEGRAM_API_ID,
                               config.TELEGRAM_API_HASH)
    if platform == "email":
        return EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                            config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    if platform == "hh":
        return HeadHunterChannel(config.HH_STATE_PATH, config.BROWSER_HEADLESS,
                                 _hh_answerer(config),
                                 getattr(config, "HH_ATTACH_CV_IN_CHAT", False))
    if platform == "linkedin":
        return LinkedInChannel(config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS,
                               external_apply_deps=_external_apply_deps(config))
    if platform == "wellfound":
        return WellfoundChannel(config.WELLFOUND_STATE_PATH, config.BROWSER_HEADLESS)
    raise ValueError(f"unknown platform: {platform}")
