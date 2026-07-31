import json

import pytest

from app.domain.channel import (
    ChannelError, ChannelUnavailable, InvitePendingError, InviteWithoutNoteError,
    ManualApplyRequired, OutreachContent, RateLimitedError,
)
from app.infrastructure.channels import linkedin as _li
from app.infrastructure.channels.linkedin import (
    SEL_FILE_INPUT,
    SEL_INVITE_SEND,
    SEL_MENU_CONNECT,
    SEL_MESSAGE_BTN,
    SEL_MORE_BTN,
    SEL_MSG_BOX,
    SEL_MSG_SEND,
    SEL_NOTE_BOX,
    SEL_PERSONALIZE,
    LinkedInChannel,
    connect_with_note,
    fill_and_send,
    message_or_connect,
)


def test_start_rejects_a_logged_out_session(tmp_path):
    """A state file with no `li_at` must stop the run (re-login), not start a
    guest browser that fails every profile at the authwall — the row-79 bug."""
    dead = tmp_path / "linkedin_state.json"
    dead.write_text(json.dumps({"cookies": [{"name": "bcookie", "value": "v=2"}]}))
    with pytest.raises(ChannelUnavailable):
        LinkedInChannel(str(dead)).start()


def test_start_rejects_a_missing_session(tmp_path):
    with pytest.raises(ChannelUnavailable):
        LinkedInChannel(str(tmp_path / "nope.json")).start()


class _FakePage:
    """Maps selector -> element count; records goto/click/fill/upload actions.

    The composer is modelled the way the live one behaves: «Отправить» is disabled
    while the box is empty, and a send empties the box. _press_send both waits on
    the first and checks the second, so a fake that answered "enabled" and kept the
    text would pass a send that never happened. See test_message_send_click.py.
    """

    def __init__(self, counts=None):
        self.actions = []
        self._counts = counts or {}
        self.text = ""
        self.keyboard = _FakeKeyboard(self)

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                return page._counts.get(selector, 0)

            @property
            def first(self_inner):
                return self_inner

            @property
            def last(self_inner):
                return self_inner

            def click(self_inner):
                page.actions.append(("click", selector))

            def focus(self_inner):
                page.actions.append(("focus", selector))

            def fill(self_inner, text):
                page.actions.append(("fill", selector, text))
                if selector == SEL_MSG_BOX:
                    page.text = text

            def set_input_files(self_inner, p):
                page.actions.append(("set_input_files", selector, p))

            def dispatch_event(self_inner, ev):
                page.actions.append(("dispatch", selector, ev))

            def is_enabled(self_inner):
                # The send button follows the box, like the real one.
                return bool(page.text) if selector == SEL_MSG_SEND else True

            def inner_text(self_inner, timeout=None):
                # An empty live composer answers '\n', never ''.
                return page.text if page.text else "\n"

            def evaluate(self_inner, expr, timeout=None):
                # _click_via_dom uses locator.evaluate("el => el.click()", timeout=…)
                page.actions.append(("jsclick", selector))
                if selector == SEL_MSG_SEND:
                    page.text = ""

            def wait_for(self_inner, state=None, timeout=None):
                # Model Playwright: a present element resolves, an absent one
                # times out (raises) — that's how _visible() reads readiness.
                if page._counts.get(selector, 0) == 0:
                    raise TimeoutError(f"wait_for timeout: {selector}")

            def scroll_into_view_if_needed(self_inner):
                pass

        return _Locator()

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, state, timeout=None):
        pass


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.actions.append(("press", key))
        if key == "Enter":
            self._page.text = ""


# A messageable profile: message button, compose box, and enabled send.
_MSG_OK = {SEL_MESSAGE_BTN: 1, SEL_MSG_BOX: 1, SEL_MSG_SEND: 1}


def test_fill_and_send_messages_connection():
    page = _FakePage(dict(_MSG_OK))
    fill_and_send(page, "https://linkedin.com/in/someone", OutreachContent(body="Hi there"))
    assert ("goto", "https://linkedin.com/in/someone") in page.actions
    assert ("jsclick", SEL_MESSAGE_BTN) in page.actions
    assert ("fill", SEL_MSG_BOX, "Hi there") in page.actions
    # Native click, not a hit-point one: a minimised overlay bubble parks the
    # button below a viewport that cannot scroll (lead #160).
    assert ("jsclick", SEL_MSG_SEND) in page.actions


def test_fill_and_send_raises_without_message_button():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="Сообщение"):
        fill_and_send(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))


def test_fill_and_send_attaches_cv_when_present():
    page = _FakePage({**_MSG_OK, SEL_FILE_INPUT: 1})
    fill_and_send(page, "https://linkedin.com/in/someone",
                  OutreachContent(body="Hi", attachment_path="/cv/me.pdf"))
    assert ("set_input_files", SEL_FILE_INPUT, "/cv/me.pdf") in page.actions


def test_fill_and_send_fails_loud_when_no_file_input():
    # Attachment requested but composer has no file input -> don't send CV-less.
    page = _FakePage(dict(_MSG_OK))
    with pytest.raises(ChannelError, match="вложения"):
        fill_and_send(page, "https://linkedin.com/in/someone",
                      OutreachContent(body="Hi", attachment_path="/cv/me.pdf"))


def test_fill_and_send_no_attachment_skips_upload():
    page = _FakePage(dict(_MSG_OK))
    fill_and_send(page, "https://linkedin.com/in/someone", OutreachContent(body="Hi"))
    assert not any(a[0] == "set_input_files" for a in page.actions)


def test_message_or_connect_messages_a_first_degree_contact():
    # 1st-degree: no Connect action anywhere -> free message. The button is
    # opened with a native in-page click to clear LinkedIn's sticky nav layer.
    page = _FakePage(dict(_MSG_OK))
    message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))
    assert ("jsclick", SEL_MESSAGE_BTN) in page.actions
    assert ("fill", SEL_MSG_BOX, "Hi") in page.actions


# A non-contact reached through the "…"/Еше menu (the only Connect path).
_CONNECT_OK = {SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
               SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1}


def test_connect_with_note_sends_invite():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "Здравствуйте, интересна ваша вакансия QA")
    assert ("jsclick", SEL_MORE_BTN) in page.actions       # opened the … menu
    assert ("jsclick", SEL_MENU_CONNECT) in page.actions   # native-click, overlay-proof
    assert ("click", SEL_PERSONALIZE) in page.actions
    assert any(a[0] == "fill" and a[1] == SEL_NOTE_BOX for a in page.actions)
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_connect_with_note_truncates_note_to_limit():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "x" * 500)
    note = next(a[2] for a in page.actions if a[0] == "fill" and a[1] == SEL_NOTE_BOX)
    assert len(note) == 200


def test_connect_with_note_raises_when_modal_missing():
    # Menu opens with a Connect entry, but clicking it never surfaces the note
    # modal — a real failure, not a silent skip.
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1})
    with pytest.raises(ChannelError, match="приглашения"):
        connect_with_note(page, "hi")


def test_invite_limit_sends_the_request_without_the_letter():
    """Monthly personalized-invite quota spent: "Персонализировать" shows a Premium
    upsell instead of the note field. The request still goes out — just plain — and
    the lead waits as `invited` for the person to accept. Stopping the platform
    (the old behaviour) left those leads `new` and untouched for a month."""
    from app.infrastructure.channels.linkedin import SEL_INVITE_LIMIT
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1, SEL_PERSONALIZE: 1,
                      SEL_INVITE_LIMIT: 1, SEL_INVITE_SEND: 1})   # note box absent
    with pytest.raises(InviteWithoutNoteError, match="БЕЗ письма"):
        message_or_connect(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))

    assert ("click", SEL_INVITE_SEND) in page.actions        # the invite was sent
    assert not any(a[0] == "fill" and a[1] == SEL_NOTE_BOX for a in page.actions)


def test_a_known_spent_quota_skips_the_upsell_entirely():
    """Once one lead has hit the limit, the rest of the run must not re-open the
    Premium upsell for every profile — it is account-wide, not per person."""
    # The modal still offers «Персонализировать» — it is the upsell trigger — so
    # the point is that we never press it, not that it is absent.
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
                      SEL_PERSONALIZE: 1, SEL_INVITE_SEND: 1})
    with pytest.raises(InviteWithoutNoteError):
        message_or_connect(page, "https://linkedin.com/in/x",
                           OutreachContent(body="Hi"), allow_note=False)

    assert ("click", SEL_PERSONALIZE) not in page.actions
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_the_channel_remembers_the_quota_is_spent(monkeypatch):
    calls = []

    def fake(page, url, content, allow_note=True):
        calls.append(allow_note)
        raise InviteWithoutNoteError("нет письма")

    monkeypatch.setattr("app.infrastructure.channels.linkedin.message_or_connect", fake)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    for _ in range(2):
        with pytest.raises(InviteWithoutNoteError):
            ch.send("https://linkedin.com/in/x", OutreachContent(body="Hi"))

    assert calls == [True, False]


def test_message_or_connect_sends_invite_when_only_connect():
    # Can't message, only connect -> invite with note, signalled InvitePendingError.
    page = _FakePage(dict(_CONNECT_OK))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_message_or_connect_raises_when_no_action():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="не найдены"):
        message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))


# A 3rd-degree profile (Daria, row 79): messaging is InMail-only (Premium), and
# Connect lives under the "Еще" overflow menu, not the top card.
_THIRD_DEGREE = {SEL_MESSAGE_BTN: 1, SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
                 SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1}


def test_message_or_connect_connects_when_message_is_inmail_only():
    """Row-79 fix: don't message a non-contact into the InMail paywall — connect.

    The Connect action is reached through the "Еще" menu, and the outcome is a
    pending invite, not a delivered message."""
    page = _FakePage(dict(_THIRD_DEGREE))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/daria", OutreachContent(body="Hi"))
    assert ("jsclick", SEL_MORE_BTN) in page.actions      # opened the … menu
    assert ("jsclick", SEL_MENU_CONNECT) in page.actions  # picked Connect
    assert ("click", SEL_INVITE_SEND) in page.actions               # invite sent
    # Never fell through to the InMail message composer.
    assert not any(a[0] == "fill" and a[1] == SEL_MSG_BOX for a in page.actions)


def test_message_or_connect_connects_a_second_degree_via_top_card(monkeypatch):
    """2nd-degree (a hiring post's author, e.g. rodion-kozlov): Connect is a
    primary top-card control, not in the menu. Use it — don't fall through to the
    InMail paywall. _topcard_connect anchors it past the recommendation cards."""
    page = _FakePage({SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1})
    monkeypatch.setattr(_li, "_topcard_connect", lambda p: p.locator("TOPCARD_CONNECT"))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/rodion", OutreachContent(body="Hi"))
    assert ("jsclick", "TOPCARD_CONNECT") in page.actions   # clicked the top-card Connect
    assert ("click", SEL_INVITE_SEND) in page.actions       # invite sent
    assert not any(a[0] == "jsclick" and a[1] == SEL_MORE_BTN for a in page.actions)  # menu not used


def test_message_or_connect_prefers_connect_over_message():
    """When both a top-level Connect and a Message button exist (2nd-degree),
    connect+note wins — a free invite beats a paid InMail."""
    page = _FakePage({SEL_MESSAGE_BTN: 1, SEL_MSG_BOX: 1, **_CONNECT_OK})
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/b", OutreachContent(body="Hi"))
    assert not any(a[0] == "fill" and a[1] == SEL_MSG_BOX for a in page.actions)


def test_message_raises_manual_when_only_inmail(monkeypatch):
    """A non-contact with no Connect anywhere (InMail-only, no invite path) must
    be flagged for a manual apply, not sent a message into a composer that never
    opens."""
    from app.domain.channel import ManualApplyRequired
    page = _FakePage({SEL_MESSAGE_BTN: 1})   # message button exists, but no msg box
    with pytest.raises(ManualApplyRequired):
        message_or_connect(page, "https://linkedin.com/in/c", OutreachContent(body="Hi"))


from app.infrastructure.channels.linkedin import (
    SEL_APPLY_NEXT,
    SEL_APPLY_SUBMIT,
    SEL_EASY_APPLY,
    _APPLY_MAX_STEPS,
    easy_apply_via_page,
    LinkedInChannel,
    _ExternalApplyNeeded,
)


class _FakeApplyPage:
    """Maps selector -> element count; records goto/click actions.

    `counts` may hold a list per selector, one entry per step of the walk, so a
    multi-screen flow can be modelled: SEL_APPLY_SUBMIT absent on the first
    screens and present on the last. A bare int means "always this many".
    """

    def __init__(self, counts, href=None):
        self._counts = counts
        self._href = href
        self.actions = []
        self.url = "https://www.linkedin.com/jobs/view/9/apply/"
        self.wander_to = None          # set to model a click that navigates away
        self._seen = {}

    def goto(self, url, **kw):
        # A real Page's url follows its navigations, and the walk checks it to
        # notice when a click has taken the browser off the job.
        self.actions.append(("goto", url))
        self.url = url

    # _settle() drives both of these on a real Page.
    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def _count_for(self, selector):
        v = self._counts.get(selector, 0)
        if isinstance(v, int):
            return v
        i = self._seen.get(selector, 0)
        self._seen[selector] = i + 1
        return v[i] if i < len(v) else v[-1]

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                return page._count_for(selector)

            @property
            def first(self_inner):
                return self_inner

            def nth(self_inner, i):
                return self_inner

            def get_attribute(self_inner, name):
                return page._href if name == "href" else None

            def click(self_inner, timeout=None):
                page.actions.append(("click", selector))

            def evaluate(self_inner, js, timeout=None):
                page.actions.append(("native-click", selector))
                # Model the click that navigates away instead of advancing.
                if page.wander_to and selector == SEL_APPLY_NEXT:
                    page.url = page.wander_to

        return _Locator()


def test_easy_apply_enters_the_flow_by_navigating_to_the_anchor_href():
    """Measured live: a click on the entry point does nothing under automation —
    no dialog, no tab, no URL change. The anchor's href is the way in."""
    href = "https://www.linkedin.com/jobs/view/9/apply/?openSDUIApplyFlow=true"
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1}, href=href)
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))

    assert ("goto", "https://www.linkedin.com/jobs/view/9") in page.actions
    assert ("goto", href) in page.actions
    assert ("click", SEL_EASY_APPLY) not in page.actions
    assert ("native-click", SEL_EASY_APPLY) not in page.actions


def test_easy_apply_falls_back_to_a_native_click_without_an_href():
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1}, href=None)
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert ("native-click", SEL_EASY_APPLY) in page.actions


def test_easy_apply_single_step_submits():
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1},
                          href="https://www.linkedin.com/jobs/view/9/apply/")
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert ("native-click", SEL_APPLY_SUBMIT) in page.actions


def test_easy_apply_external_job_signals_handoff():
    # No Easy Apply entry point = external apply -> signal hand-off; the channel
    # then runs the external-apply driver instead of erroring here.
    page = _FakeApplyPage({})
    with pytest.raises(_ExternalApplyNeeded):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/1",
                            OutreachContent(body="hi"))


def test_easy_apply_walks_a_multistep_flow_to_the_submit():
    """The real flow measured live is Contact info -> … -> Submit, never one step.
    The old code called anything past screen one unautomatable and gave up."""
    page = _FakeApplyPage({SEL_EASY_APPLY: 1,
                           SEL_APPLY_SUBMIT: [0, 0, 1],
                           SEL_APPLY_NEXT: 1},
                          href="https://www.linkedin.com/jobs/view/2/apply/")
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                        OutreachContent(body="hi"))

    assert page.actions.count(("native-click", SEL_APPLY_NEXT)) == 2
    assert ("native-click", SEL_APPLY_SUBMIT) in page.actions


def test_a_screen_with_neither_submit_nor_next_is_manual_not_failed():
    """ChannelError here writes `failed` — a terminal status on a lead nothing was
    wrong with. A flow we can't drive is work for a human, which is `manual`."""
    page = _FakeApplyPage({SEL_EASY_APPLY: 1},
                          href="https://www.linkedin.com/jobs/view/2/apply/")
    with pytest.raises(ManualApplyRequired, match="дожми вручную"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                            OutreachContent(body="hi"))


def test_the_walk_is_bounded_and_never_submits_on_giving_up():
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 0,
                           SEL_APPLY_NEXT: 1},
                          href="https://www.linkedin.com/jobs/view/2/apply/")
    with pytest.raises(ManualApplyRequired, match="шагов"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                            OutreachContent(body="hi"))

    assert page.actions.count(("native-click", SEL_APPLY_NEXT)) == _APPLY_MAX_STEPS
    assert ("native-click", SEL_APPLY_SUBMIT) not in page.actions


def test_dry_run_reaches_the_submit_but_does_not_press_it():
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1},
                          href="https://www.linkedin.com/jobs/view/9/apply/")
    with pytest.raises(ManualApplyRequired, match="DRY_RUN"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                            OutreachContent(body="hi"), dry_run=True)

    assert ("native-click", SEL_APPLY_SUBMIT) not in page.actions


def _patch_routes(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content, **kw: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.message_or_connect",
                        lambda page, url, content, **kw: called.setdefault("msg", url))
    return called


def test_send_routes_job_url_to_easy_apply(monkeypatch):
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/jobs/view/9", OutreachContent(body="hi"))
    assert called == {"easy": "https://www.linkedin.com/jobs/view/9"}


def test_send_routes_profile_url_to_message(monkeypatch):
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/in/jane", OutreachContent(body="hi"))
    assert called == {"msg": "https://www.linkedin.com/in/jane"}


def test_send_routes_post_url_to_author_message(monkeypatch):
    # A post URL -> message the AUTHOR resolved from the post slug.
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/posts/ilyas-mustafin-44b575144_x-activity-7-CmC7/",
            OutreachContent(body="hi"))
    assert called == {"msg": "https://www.linkedin.com/in/ilyas-mustafin-44b575144/"}


def test_the_walk_stops_when_a_click_leaves_the_job_page():
    """«Далее» is also the caption on the similar-jobs rail. When the flow is not
    open, the walk paged through search results — leads 118/119/123/129 all ended
    eight clicks deep in somebody else's vacancy. The link handed back must be the
    job we started from, not wherever the browser drifted to."""
    job = "https://www.linkedin.com/jobs/view/4350293983/"
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 0,
                           SEL_APPLY_NEXT: 1}, href=job + "apply/")
    page.wander_to = "https://www.linkedin.com/jobs/search-results/?currentJobId=4327959909"

    with pytest.raises(ManualApplyRequired) as err:
        easy_apply_via_page(page, job, OutreachContent(body="hi"))

    assert "форма закрылась" in str(err.value)
    assert job in str(err.value)
    assert page.actions.count(("native-click", SEL_APPLY_NEXT)) == 1


def test_an_easy_apply_badge_on_a_similar_job_is_not_this_job_s_button():
    """Leads 123 and 129: the similar-jobs rail badges other vacancies with the
    same caption — 7 and 4 matches, every href a `/jobs/search-results/` link.
    Following one paged through somebody else's search results AND cost both
    leads the external apply they should have had. No href naming this job means
    no Easy Apply here."""
    page = _FakeApplyPage(
        {SEL_EASY_APPLY: 7},
        href="https://www.linkedin.com/jobs/search-results/?keywords=Software+Engineer")

    with pytest.raises(_ExternalApplyNeeded):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/4429172553/",
                            OutreachContent(body="hi"))

    assert not any(a[0] == "goto" and "search-results" in a[1] for a in page.actions)


def test_a_lone_caption_only_control_is_still_accepted():
    """One match with no href is plausibly an older rendering of the real button;
    several are the rail, and guessing among them is what went wrong."""
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1}, href=None)
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert ("native-click", SEL_EASY_APPLY) in page.actions


def test_invite_state_resolves_a_post_url_to_its_author(monkeypatch):
    """An `invited` lead usually points at the hiring POST, not the person. Read
    as-is, the post page has no top card, no pending marker and no Connect — which
    used to fall through to "accepted" and burn the lead."""
    seen = {}
    def _fake(page, url):
        seen["url"] = url
        return "pending"

    monkeypatch.setattr("app.infrastructure.channels.linkedin.read_invite_state", _fake)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    post = ("https://www.linkedin.com/posts/anastasiya-lipkina_excited-"
            "ugcPost-7474748735390900225-jjeN/")

    assert ch.invite_state(post) == "pending"
    assert "/in/" in seen["url"]


def test_invite_state_passes_a_profile_url_through(monkeypatch):
    seen = {}
    def _fake(page, url):
        seen["url"] = url
        return "pending"

    monkeypatch.setattr("app.infrastructure.channels.linkedin.read_invite_state", _fake)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.invite_state("https://www.linkedin.com/in/daria-yakovleva/")

    assert seen["url"] == "https://www.linkedin.com/in/daria-yakovleva/"


def test_a_page_with_no_message_affordance_reads_as_pending():
    """Never guess "accepted": anything unreadable costs one re-check, while a
    wrong "accepted" costs the lead."""
    from app.infrastructure.channels.linkedin import read_invite_state
    page = _FakePage({})            # no pending marker, no connect, no compose
    assert read_invite_state(page, "https://linkedin.com/in/x") == "pending"
