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
    основная пробуется снова.

    Слышны только уход на запасную и подтверждённый возврат — когда основная
    ответила дважды подряд. Неудачная проверка и сорвавшийся возврат молчат:
    живьём 2026-09-15 в 10:40, больше чем за час до сброса, Gemini ответил на одну
    проверку и отказал на следующем же запросе, и в логе встала пара «↩️ снова
    отвечает» / «↪️ исчерпана», первая строка которой была неправдой.
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
        # Проверка прошла, но возврат ещё не подтверждён вторым ответом подряд.
        self._returning = False

    def score(self, profile, title, description, location=""):
        if self._primary_out_at is None or \
                self._clock() - self._primary_out_at >= self._retry_after:
            try:
                result = self._primary.score(profile, title, description, location)
            except LLMQuotaExhausted as exc:
                if self._primary_out_at is None and not self._returning:
                    minutes = int(self._retry_after // 60)
                    self._notice(f"↪️ {exc} — оцениваю через {self._fallback_name}; "
                                 f"основную модель проверю снова через {minutes} мин.")
                self._primary_out_at = self._clock()
                self._returning = False
            else:
                if self._primary_out_at is not None:
                    self._primary_out_at = None
                    self._returning = True
                elif self._returning:
                    self._returning = False
                    self._notice("↩️ Основная модель снова отвечает — оцениваю через неё.")
                return result
        return self._fallback.score(profile, title, description, location)
