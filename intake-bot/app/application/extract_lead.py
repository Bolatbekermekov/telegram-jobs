"""Use-case: detect contact + summarize a raw vacancy message, then save a lead."""
from app.domain.lead import ExtractedLead
from app.domain.post_contact import (
    DIRECT_PLATFORMS, pick_post_contact, post_author_profile_url,
)
from app.domain.vacancy_text import (
    expand_short_links, is_fetchable_vacancy_url, is_link_only,
    is_linkedin_post_url, pick_vacancy_url,
)

_FALLBACK_LEN = 280

# Сколько текста вакансии уходит в оценку. Страница сюда приезжает уже урезанной
# (app/domain/vacancy_text.py режет каждый сайт своим потолком, агрегаторы — на
# 4000 символов), но к ней приклеивается ещё и сообщение владельца, а платит за
# длину промпта та же serverless-функция с бюджетом ~10 секунд на всё. Резать
# сильнее нельзя: уровень («Principal») и запреты («must be authorized to work
# in the US») живут в середине текста, а не в первом абзаце.
_SCORE_INPUT_LIMIT = 6000


class ExtractLeadFromText:
    def __init__(self, detector, summarizer, repo, fetcher=None, resolve_link=None,
                 score=None):
        # detector: callable(text) -> Contact | None
        # summarizer: object with .summarize(text) -> str
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        # fetcher: callable(url) -> str, the vacancy text behind a link ("" if
        #          unavailable). Optional so the use-case still runs offline.
        # resolve_link: callable(url) -> str, undoes LinkedIn's `lnkd.in` rewrite.
        #          Read twice: on the MESSAGE, so a post shared as `lnkd.in/p/…`
        #          is seen as the post it is, and inside the POST, so a t.me link
        #          the author wrote becomes a contact. Optional; without it a
        #          short-link-only message is refused as «Не нашёл контакт».
        # score: callable(title, description) -> (0-100, причина) | None — насколько
        #          вакансия подходит профилю поиска. Тот же вопрос, который поиск на
        #          ноуте задаёт о каждой найденной вакансии, и до этого шага интейк
        #          его не задавал вообще: замер 2026-08-23 на партии из 15
        #          пересланных вакансий Remocate дал Principal, два Senior и два
        #          Lead при профиле «Intern / Junior / Junior+ / Middle», то есть
        #          треть партии уходила в очередь с письмом и поднятым браузером.
        #          Необязателен, как fetcher и resolve_link: без него интейк
        #          работает как раньше. Оценка НИЧЕГО не отбрасывает — см. _relevance.
        self._detect = detector
        self._summarizer = summarizer
        self._repo = repo
        self._fetch = fetcher
        self._resolve_link = resolve_link
        self._score = score

    def execute(self, raw_text: str) -> ExtractedLead:
        # Before anything reads the message: a post shared from the LinkedIn app
        # arrives as `https://lnkd.in/p/<code>`, which matches no contact rule and
        # no fetchable-url rule, so intake answered «Не нашёл контакт» and dropped
        # a perfectly ordinary hiring post. Expanded here rather than in the
        # detector because it costs a request, and this is the one place that
        # knows a request is affordable. `raw_text` below still stores what the
        # user actually sent.
        text = expand_short_links(raw_text, self._resolve_link)

        contact = self._detect(text)
        if contact is None:
            raise ValueError("no_contact")

        url = self._vacancy_url(text, contact)
        read = self._worth_reading(text, url)
        page_text = self._fetch(url) if read else ""

        platform, target, note = self._route(contact, url, page_text)
        # Один и тот же текст кормит и суммаризацию, и оценку — иначе оценка
        # считалась бы по пересказу, написанному под сопроводительное письмо.
        source = self._vacancy_source(text, page_text, read)
        vacancy = self._summarise(source) if source else ""
        score, reason = self._relevance(vacancy, source)
        lead = ExtractedLead(
            platform=platform,
            target=target,
            vacancy_context=vacancy,
            raw_text=raw_text,
            note=note,
            score=score,
            score_reason=reason,
        )
        self._repo.append_lead(lead)
        return lead

    @staticmethod
    def _vacancy_url(raw_text: str, contact) -> str:
        """The page to read this lead's description from, or "".

        The contact's own target first, when that target IS a readable page: it has
        been through `detect_contact`'s cleaning, which for hh means
        `canonical_hh_url` — one national domain instead of six, and the sharer's
        `?from=share_ios` dropped. Scanning the message myself would hand the fetch
        the raw shared string and quietly lose that.

        Only when the contact is NOT a page — a handle, a t.me link, an email —
        does the message get scanned for the link the vacancy actually lives at.
        That is the whole gap this closes: `detect_contact` ranks an address above
        every url, so «посмотри <ссылка> пиши @ivan_hr» aimed the fetch at
        «@ivan_hr», read nothing, and saved the lead with an empty «Вакансия».
        """
        if is_fetchable_vacancy_url(contact.target):
            return contact.target
        return pick_vacancy_url(raw_text)

    def _worth_reading(self, raw_text: str, url: str) -> bool:
        """Whether `url` is worth an http request inside this function's budget.

        Two reasons, and the second is why this is not just `is_link_only`:

        A message that is nothing but a link has no description to summarise, so
        the page is the only source there is — that was the original reason.

        A LinkedIn POST is read no matter how much the message says, because the
        post's body is the only place the address to apply to can be found. Before
        this, «посмотри, вроде под тебя: <ссылка>» carried enough prose to clear
        `is_link_only`, so the post was never opened and «Вакансия» became a summary
        of the forwarder's aside.

        An hh page or a LinkedIn job stays behind the old gate on purpose: you
        apply to those through the site itself, there is no contact to find in
        them, and this runs on a serverless function whose whole budget is ~10s —
        a fetch bought for nothing is a killed request that Telegram then retries.
        """
        if self._fetch is None or not url:
            return False
        return is_linkedin_post_url(url) or is_link_only(raw_text)

    def _route(self, contact, url: str, page_text: str):
        """(platform, target, note) — whom this lead is for.

        The order the user asked for: an address named in the MESSAGE wins, then
        one named inside the POST, then the post's author.

        A post that could not be read keeps the lead pointing at the post url, and
        that is deliberate rather than a leftover: an author profile is not a page
        the vacancy can be re-read from, and `needs_vacancy_refetch` together with
        `is_fetchable_vacancy_url(target)` on the laptop is what fills «Вакансия»
        on the second, unhurried attempt. Trading that away for a better-looking
        «Источник» would strand every throttled read with no description at all.
        """
        if contact.platform in DIRECT_PLATFORMS:
            return contact.platform, contact.target, ""
        if not (page_text and is_linkedin_post_url(url)):
            return contact.platform, contact.target, ""

        found = pick_post_contact(page_text, self._detect, self._resolve_link)
        if found is not None:
            return found.platform, found.target, f"контакт из LinkedIn-поста: {url}"

        author = post_author_profile_url(url)
        if not author:
            return contact.platform, contact.target, ""
        return "linkedin", author, f"автор LinkedIn-поста: {url}"

    @staticmethod
    def _vacancy_source(raw_text: str, page_text: str, read: bool) -> str:
        """The text «Вакансия» is made of — or "" when it can't be known.

        Отдан отдельным шагом, потому что читателей у него теперь два:
        суммаризация (из него получается колонка «Вакансия») и оценка
        соответствия профилю. Оценивать пересказ вместо текста нельзя —
        суммаризация пишется под сопроводительное письмо и режет ровно то, по
        чему считается пригодность: слово Principal в третьем абзаце, список
        стран найма, «must be authorized to work in the US».

        A phone share carries only a URL. The summariser can't open links, so it
        answers "не удалось извлечь содержание вакансии, пришлите текст", and that
        sentence lands in «Вакансия» and becomes the brief the cover letter is
        written from. Reading the page first is what prevents it.

        When a read was attempted and came back empty, return "" — do NOT fall
        through to summarising the bare URL. That fall-through is precisely how the
        refusal got stored anyway: the guard covered the path where the fetch worked
        and left the failing one alone, and rows 121 and 141 were saved with the
        model's apology as their vacancy text.

        Empty is honest and it is recoverable. This bot runs on a serverless
        function with an ~8s budget and a datacenter IP that LinkedIn and hh both
        throttle, so an empty read is far more often a moment's throttling than a
        dead link — the same LinkedIn post that failed for row 121 fetched fine
        later. The sender re-reads the link from the laptop before it generates
        anything (send_plan.needs_vacancy_refetch), which is where the second,
        unhurried attempt happens.

        When the message carried words of its own, they are summarised TOGETHER with
        the page rather than replaced by it. A forwarder writes things the advert
        does not say — «готовы на релокацию», a salary they happen to know, which
        team it is for — and those are exactly the facts a cover letter needs.
        """
        if page_text:
            return page_text if is_link_only(raw_text) else f"{page_text}\n\n{raw_text}"
        if read and is_link_only(raw_text):
            return ""
        return raw_text

    def _relevance(self, vacancy: str, source: str):
        """(оценка 0-100, причина) для «Заметки» и ответа бота — или (None, "").

        Не оценить можно по трём причинам, и все три оставляют лид ровно таким,
        каким он был до появления оценки. Отбросить вакансию нельзя ни при
        какой: постоянное указание владельца — никогда не пропускать вакансию
        молча, поэтому оценка только РАССКАЗЫВАЕТ.

        Скорер не подключён — интейк работает как до 2026-08-23.

        Оценивать нечего (`source == ""`) — это лид, чья ссылка не прочиталась в
        отведённые функции секунды. Спросить модель о голом URL значит получить
        выдуманное «0/100» на вакансию, которую никто не читал, и в «Заметке»
        оно будет неотличимо от вердикта. Ноут дочитает ссылку перед отправкой
        (send_plan.needs_vacancy_refetch); оценки просто не будет.

        Скорер не смог — сюда попадает ВСЁ: таймаут OpenAI, 429, кривой ответ,
        исчерпанный бюджет сообщения. Ловится здесь, а не в реализации скорера,
        потому что решение «лид дороже оценки» принимается на этом уровне и
        должно защищать любой подставленный скорер, а не только наш. До этого
        шага сбою тут было неоткуда взяться — теперь это самый вероятный новый
        способ потерять пересланную вакансию.

        «Название» для промпта — это суммаризация: единственное, что у
        пересланного текста есть похожего на заголовок (поиску на ноуте
        заголовок отдаёт карточка выдачи). Полный текст идёт описанием.
        """
        if self._score is None or not source:
            return None, ""
        try:
            verdict = self._score(vacancy, source[:_SCORE_INPUT_LIMIT])
            if not verdict:
                return None, ""
            score, reason = verdict
        except Exception:  # noqa: BLE001 — лид дороже оценки, всегда
            return None, ""
        return score, reason

    def _summarise(self, text: str) -> str:
        summary = self._summarizer.summarize(text)
        return summary or text.strip()[:_FALLBACK_LEN]
