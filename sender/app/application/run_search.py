"""Run one search request: scrape each platform, optionally AI-score, append.

One platform failing neither stops the others nor kills the caller's loop.
Returns the number of new candidates written.
"""
import time

from app.application.relevance import score_and_filter
from app.domain.candidate import normalize_url


def _unique(candidates):
    """Одна вакансия — одна карточка, даже если её нашли несколько запросов.

    Локации перекрываются по построению: «Worldwide» включает все страны, а
    «European Union» — Германию, Нидерланды и Польшу, поэтому одна и та же
    вакансия приходит из нескольких запросов одного прогона. Замер живого
    LinkedIn 2026-08-03 по одному слову и трём локациям: 75 карточек, 65
    уникальных. Без этой склейки каждый дубль занимал бы отдельный слот в
    бюджете скоринга и стоил бы отдельного вызова модели.

    Дедупликация в листе (`known_urls`) от этого не спасает: она сравнивает с
    УЖЕ СОХРАНЁННЫМИ строками, а два одинаковых URL внутри одной выдачи для неё
    оба новые.
    """
    seen, out = set(), []
    for c in candidates:
        key = normalize_url(c.url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def run_search(platforms, searchers, candidates_repo, keywords, location, limit,
               on_error=None, scorer=None, profile="", threshold=0, max_jobs=0,
               scored_out=None, on_platform_done=None) -> int:
    """`scored_out` — память о вакансиях, которые скорер уже отверг.

    Без неё отказник не сохранялся никуда (`known_urls()` читает только
    сохранённых кандидатов), поэтому каждый прогон снова качал его описание и
    снова платил за скоринг. А так как порядок выдачи детерминированный, одни и
    те же отказники занимали весь бюджет max_jobs, и вакансии за ними не
    начинались никогда.
    """
    added = 0
    for platform in platforms:
        searcher = searchers[platform]
        # Замер идёт вокруг ВСЕЙ работы по площадке, включая скоринг: он и есть
        # самая долгая её часть (страница описания плюс вызов модели на каждую
        # вакансию), и без него цифра не отвечала бы на вопрос «где застряли».
        started = time.monotonic()
        gained = None
        try:
            searcher.start()
            found = _unique(searcher.search(keywords, location, limit))
            if scorer is not None:
                # Drop already-saved jobs BEFORE scoring so max_jobs counts fresh
                # ones and we never spend OpenAI calls on duplicates.
                known = candidates_repo.known_urls()
                if scored_out is not None:
                    known |= scored_out.known()
                found = [c for c in found if normalize_url(c.url) not in known]
                found = score_and_filter(
                    found, lambda c: searcher.describe(c.url),
                    scorer, profile, threshold, max_jobs,
                    # score_and_filter отдаёт кандидата, память хранит ссылку.
                    on_reject=(None if scored_out is None
                               else lambda c: scored_out.add(c.url)))
            gained = candidates_repo.add_new(found)
            added += gained
        except Exception as exc:  # noqa: BLE001 — isolate per-platform failures
            if on_error is not None:
                on_error(platform, exc)
        finally:
            try:
                searcher.stop()
            except Exception:  # noqa: BLE001
                pass
            if on_platform_done is not None:
                # `gained is None` = площадка упала. Без этого различия падение
                # на первой секунде читается как «просто ничего не нашлось».
                try:
                    on_platform_done(platform, time.monotonic() - started, gained)
                except Exception:  # noqa: BLE001 — отчёт не должен ронять поиск
                    pass
    if scored_out is not None:
        # После всех платформ: упасть на записи файла кэша значит потерять уже
        # найденных кандидатов, а они дороже памяти об отказниках.
        try:
            scored_out.save()
        except Exception:  # noqa: BLE001
            pass
    return added
