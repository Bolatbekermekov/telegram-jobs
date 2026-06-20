"""Run one search request: scrape each platform, optionally AI-score, append.

One platform failing neither stops the others nor kills the caller's loop.
Returns the number of new candidates written.
"""
from app.application.relevance import score_and_filter


def run_search(platforms, searchers, candidates_repo, keywords, location, limit,
               on_error=None, scorer=None, profile="", threshold=0, max_jobs=0) -> int:
    added = 0
    for platform in platforms:
        searcher = searchers[platform]
        try:
            searcher.start()
            found = searcher.search(keywords, location, limit)
            if scorer is not None:
                found = score_and_filter(
                    found, lambda c: searcher.describe(c.url),
                    scorer, profile, threshold, max_jobs)
            added += candidates_repo.add_new(found)
        except Exception as exc:  # noqa: BLE001 — isolate per-platform failures
            if on_error is not None:
                on_error(platform, exc)
        finally:
            try:
                searcher.stop()
            except Exception:  # noqa: BLE001
                pass
    return added
