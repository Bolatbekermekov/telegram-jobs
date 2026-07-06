"""Map a platform string to a freshly-built (not yet started) OutreachChannel."""
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.telegram import TelegramChannel
from app.infrastructure.channels.wellfound import WellfoundChannel


def build_channel(platform: str, config):
    if platform == "telegram":
        return TelegramChannel(config.SESSION_PATH, config.TELEGRAM_API_ID,
                               config.TELEGRAM_API_HASH)
    if platform == "email":
        return EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                            config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    if platform == "hh":
        return HeadHunterChannel(config.HH_STATE_PATH, config.BROWSER_HEADLESS)
    if platform == "linkedin":
        return LinkedInChannel(config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS)
    if platform == "wellfound":
        return WellfoundChannel(config.WELLFOUND_STATE_PATH, config.BROWSER_HEADLESS)
    raise ValueError(f"unknown platform: {platform}")
