"""The text a Telegram message really carries — including the links you can't see.

Telegram sends a hyperlink's destination out of band: the words the reader sees
stay in `text`, and the address lives in `entities` as
`{"type": "text_link", "offset": …, "length": …, "url": …}`. So a forwarded
hiring post that ends «её пост на LinkedIn», with the link laid over those two
words, arrives at anything reading `text` alone with no url in it at all —
`detect_contact` found nothing and the bot answered «Не нашёл контакт» to a
message that plainly named where to write.

Media messages carry the same pair under different names (`caption` /
`caption_entities`), and a hiring post forwarded together with its picture is the
ordinary case, not an exotic one — so both are read here.

The hidden addresses are APPENDED after the visible words rather than spliced in
at their offsets. Splicing would mean tracking UTF-16 offsets (Telegram counts in
UTF-16 code units, Python in code points — every emoji in the post shifts them)
to gain nothing: every rule downstream searches the whole message, and
`pick_vacancy_url` walks urls in order, so a url the sender typed out still wins
over one that was only ever a hyperlink.
"""

# (visible field, entity field) — a message uses exactly one of these pairs.
_FIELDS = (("text", "entities"), ("caption", "caption_entities"))


def message_text(message: dict) -> str:
    """`message`'s words plus the destinations of its hyperlinks, one per line."""
    message = message or {}
    body = ""
    entities = ()
    for text_key, entity_key in _FIELDS:
        if (message.get(text_key) or "").strip():
            body = message[text_key].strip()
            entities = message.get(entity_key) or ()
            break

    hidden = []
    for entity in entities:
        # Only `text_link` has a url; `text_mention` has a user object and the
        # rest (bold, url, mention, email) have neither — a blind
        # `entity["url"]` would append the string "None" to the message.
        if (entity or {}).get("type") != "text_link":
            continue
        url = (entity.get("url") or "").strip()
        # A url the writer typed out carries a `url` entity as well as being in
        # the text; a `text_link` can point at an address that IS already
        # written out too ("пиши на https://t.me/acme_hr" linked to itself).
        # Appending it again would double it in the summariser's prompt and in
        # the «Сырой текст» column.
        if url and url not in body and url not in hidden:
            hidden.append(url)

    return "\n".join([body, *hidden]).strip()
