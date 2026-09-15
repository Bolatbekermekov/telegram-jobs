"""Оценка поиска с запасной моделью, пока у основной кончилась квота.

Решение владельца 2026-09-15: «только для поиска с моделью nvidia, когда у gemini
лимит происходит … но всё равно gemini держать в приоритете». В тот день поиск
дважды упёрся в дневную квоту Gemini (flash-lite — 500 запросов в сутки, flash —
20), и до сброса в 12:00 по Астане оценивать вакансии было нечем.

Переключает ТОЛЬКО исчерпанная квота (`LLMQuotaExhausted`). Поминутный 429
пережидается внутри самого клиента, а прочие сбои (502, таймаут) касаются одной
вакансии и не повод уводить весь прогон на другую модель.
"""
import time

from app.domain.llm_quota import LLMQuotaExhausted

# Как часто, уйдя на запасную, снова пробовать основную. Квота Gemini возвращается
# разом, в полночь по тихоокеанскому времени, так что чаще проверять незачем, а
# реже значит лишние полчаса оценивать запасной после сброса.
RETRY_PRIMARY_AFTER_SECONDS = 15 * 60


class FallbackScorer:
    """Основная модель, пока у неё есть квота; запасная — на время, пока нет.

    Приоритет основной держат два правила: новый объект на каждый прогон (см.
    `_relevance_args`), и раз в `retry_primary_after` секунд после переключения
    основная пробуется снова. Неудачная проверка молчит — строка раз в 15 минут
    ничего не сообщает; слышны только уход на запасную и возврат.
    """

    def __init__(self, primary, fallback, fallback_name: str, on_notice=None,
                 retry_primary_after: float = RETRY_PRIMARY_AFTER_SECONDS,
                 clock=time.monotonic):
        self._primary = primary
        self._fallback = fallback
        self._fallback_name = fallback_name
        self._notice = on_notice or (lambda text: None)
        self._retry_after = retry_primary_after
        self._clock = clock
        # Когда основная в последний раз ответила «квота кончилась»; None — отвечает.
        self._primary_out_at = None

    def score(self, profile, title, description, location=""):
        if self._primary_out_at is None or \
                self._clock() - self._primary_out_at >= self._retry_after:
            try:
                result = self._primary.score(profile, title, description, location)
            except LLMQuotaExhausted as exc:
                if self._primary_out_at is None:
                    minutes = int(self._retry_after // 60)
                    self._notice(f"↪️ {exc} — оцениваю через {self._fallback_name}; "
                                 f"основную модель проверю снова через {minutes} мин.")
                self._primary_out_at = self._clock()
            else:
                if self._primary_out_at is not None:
                    self._primary_out_at = None
                    self._notice("↩️ Основная модель снова отвечает — оцениваю через неё.")
                return result
        return self._fallback.score(profile, title, description, location)
