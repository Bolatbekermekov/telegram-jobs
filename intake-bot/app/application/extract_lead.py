"""Use-case: detect contact + summarize a raw vacancy message, then save a lead."""
from app.domain.lead import ExtractedLead
from app.domain.post_contact import (
    DIRECT_PLATFORMS, pick_post_contact, post_author_profile_url,
)
from app.domain.vacancy_text import (
    is_fetchable_vacancy_url, is_link_only, is_linkedin_post_url, pick_vacancy_url,
)

_FALLBACK_LEN = 280


class ExtractLeadFromText:
    def __init__(self, detector, summarizer, repo, fetcher=None, resolve_link=None):
        # detector: callable(text) -> Contact | None
        # summarizer: object with .summarize(text) -> str
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        # fetcher: callable(url) -> str, the vacancy text behind a link ("" if
        #          unavailable). Optional so the use-case still runs offline.
        # resolve_link: callable(url) -> str, undoes LinkedIn's `lnkd.in` rewrite so
        #          a t.me link inside a post can be seen. Optional for the same
        #          reason; without it only a plain @handle in a post is found.
        self._detect = detector
        self._summarizer = summarizer
        self._repo = repo
        self._fetch = fetcher
        self._resolve_link = resolve_link

    def execute(self, raw_text: str) -> ExtractedLead:
        contact = self._detect(raw_text)
        if contact is None:
            raise ValueError("no_contact")

        url = self._vacancy_url(raw_text, contact)
        read = self._worth_reading(raw_text, url)
        page_text = self._fetch(url) if read else ""

        platform, target, note = self._route(contact, url, page_text)
        lead = ExtractedLead(
            platform=platform,
            target=target,
            vacancy_context=self._vacancy_text(raw_text, page_text, read),
            raw_text=raw_text,
            note=note,
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

    def _vacancy_text(self, raw_text: str, page_text: str, read: bool) -> str:
        """The «Вакансия» column for this message — or "" when it can't be known.

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
            source = page_text if is_link_only(raw_text) else f"{page_text}\n\n{raw_text}"
            return self._summarise(source)
        if read and is_link_only(raw_text):
            return ""
        return self._summarise(raw_text)

    def _summarise(self, text: str) -> str:
        summary = self._summarizer.summarize(text)
        return summary or text.strip()[:_FALLBACK_LEN]
