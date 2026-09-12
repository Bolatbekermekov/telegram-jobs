"""Ключ дедупа обязан различать вакансии, адресуемые query-строкой.

Живьём 2026-09-12: поиск по Indeed возвращал ноль при полной выдаче, и причина
была здесь. `normalize_url` выбрасывает query целиком, а Indeed адресует
вакансию параметром `jk`: `indeed.com/rc/clk?jk=…`. После нормализации ВСЕ
вакансии площадки превращались в один адрес `indeed.com/rc/clk`.

Дальше срабатывал конвейер: `run_search` отсеивает уже известное ДО скоринга, и
стоило одной вакансии попасть в память отказников, как весь Indeed навсегда
становился «уже известным». В файле памяти на момент находки лежали ровно эти
три строки: `/rc/clk`, `/viewjob`, `/addlLoc/redirect`.

Диагноз стоил трёх неверных версий подряд (холодный старт, ожидание видимости,
частота запросов), потому что снаружи это выглядело как пустая выдача.
"""
from app.domain.candidate import normalize_url


def test_two_indeed_vacancies_do_not_collapse_into_one():
    a = normalize_url("https://www.indeed.com/rc/clk?jk=99ddbd2071d46956&bb=xyz")
    b = normalize_url("https://www.indeed.com/rc/clk?jk=aaaaaaaaaaaaaaaa&bb=xyz")
    assert a != b


def test_the_job_id_survives_normalisation():
    assert "99ddbd2071d46956" in normalize_url(
        "https://www.indeed.com/rc/clk?jk=99ddbd2071d46956&bb=xyz")


def test_the_same_vacancy_under_different_tracking_is_one_key():
    """Ради чего query и выбрасывали: метки выдачи не должны плодить дубли."""
    a = normalize_url("https://www.indeed.com/viewjob?jk=591fcde7d2cf0699&from=serp")
    b = normalize_url("https://www.indeed.com/viewjob?jk=591fcde7d2cf0699&tk=1abc&vjs=3")
    assert a == b


def test_two_indeed_paths_to_the_same_vacancy_stay_two_keys():
    """Известное ограничение, зафиксированное намеренно.

    У Indeed одна вакансия доступна по двум путям: `/rc/clk?jk=X` из выдачи и
    `/viewjob?jk=X` из адресной строки. Ключи получаются разные, то есть
    присланная руками ссылка может задвоить вакансию, найденную поиском.

    Схлопывать их значит завести ещё одно частное правило про Indeed в функции,
    общей для всех площадок, ради случая, который на практике почти не
    встречается: поиск отдаёт только форму `/rc/clk`. Записано тестом, чтобы
    следующий читатель видел границу, а не думал, что о ней забыли.
    """
    a = normalize_url("https://www.indeed.com/rc/clk?jk=591fcde7d2cf0699")
    b = normalize_url("https://www.indeed.com/viewjob?jk=591fcde7d2cf0699")
    assert a != b


def test_other_platforms_are_untouched():
    """Правило узкое: у остальных площадок вакансию адресует путь, и query там
    это мусор выдачи, ради отсечения которого всё и затевалось."""
    assert normalize_url("https://hh.ru/vacancy/123?from=share_ios") \
        == normalize_url("https://hh.ru/vacancy/123")
    assert normalize_url("https://www.remocate.app/jobs/go-dev/?utm_source=x") \
        == "https://www.remocate.app/jobs/go-dev"
