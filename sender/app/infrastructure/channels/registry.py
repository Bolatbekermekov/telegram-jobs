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
        return LinkedInChannel(config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS)
    if platform == "wellfound":
        return WellfoundChannel(config.WELLFOUND_STATE_PATH, config.BROWSER_HEADLESS)
    raise ValueError(f"unknown platform: {platform}")
