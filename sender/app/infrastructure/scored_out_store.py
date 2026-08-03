"""Локальная память о вакансиях, которые скорер уже отверг.

Отвергнутая вакансия не записывалась никуда: `CandidatesRepo.known_urls()`
читает только СОХРАНЁННЫХ кандидатов, а не прошедшие порог в лист не попадают.
Из-за этого каждый следующий прогон снова качал их описания и снова платил за
скоринг — а так как порядок выдачи детерминированный, одни и те же отказники
занимали весь бюджет скоринга, и вакансии за ними не начинались никогда.

Файл локальный и не является источником истины: потерять его не страшно (в
худшем случае отказники переоценятся один раз), поэтому битый файл читается как
пустая память, а не роняет прогон.
"""
import json
from pathlib import Path

from app.domain.candidate import normalize_url

# Сколько ссылок держать. Сотни отказников в день за год дали бы мегабайты,
# которые читаются на каждом прогоне; при вытеснении теряются самые старые —
# именно те вакансии, которых уже нет в выдаче.
DEFAULT_MAX_URLS = 5000


class ScoredOutStore:
    def __init__(self, path: str, max_urls: int = DEFAULT_MAX_URLS):
        self._path = Path(path)
        self._max = max_urls
        self._urls: list[str] = self._load()
        self._dirty = False

    def _load(self) -> list[str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — нет файла или он битый: память пуста
            return []
        urls = data.get("urls") if isinstance(data, dict) else data
        return [str(u) for u in urls][-self._max:] if isinstance(urls, list) else []

    def known(self) -> set:
        return set(self._urls)

    def add(self, url) -> None:
        key = normalize_url(url)
        if not key or key in self._urls[-self._max:]:
            return
        self._urls.append(key)
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self._urls = self._urls[-self._max:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"urls": self._urls}, ensure_ascii=False),
                              encoding="utf-8")
        self._dirty = False
