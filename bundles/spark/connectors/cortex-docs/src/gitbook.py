"""The Cortex documentation on GitBook (https://cortex-docs.paloaltonetworks.com).

The documentation lives on GitBook (the older Fluid Topics site, docs-cortex.paloaltonetworks.com/api/khub/*, is retired).
What the site offers, and what this module uses:

  * every page is clean Markdown when `.md` is appended to its URL;
  * every page answers `?ask=<question>` (optionally `&goal=<what you are trying to do>`) with a direct answer, follow-up
    questions and the source pages it drew on, searching the whole book, not only that page;
  * each book has `<book>/sitemap-pages.xml`, a flat list of its pages (the book's table of contents, in URL form).

Nothing here needs a credential. Every request goes to the docs host only (`fetch` refuses any other host), so a model
cannot use the connector to read an arbitrary URL."""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://cortex-docs.paloaltonetworks.com"
TIMEOUT = 30
ASK_TIMEOUT = 90  # a question nobody asked before is answered live and takes about 30 s; a repeat comes back in well under a second
UA = "phantom-cortex-docs/2.0 (+detection-engineering lab)"

# The product vocabulary the tools accept, mapped to the book that answers for it.
BOOKS = {
    "xsiam": "cortex-xsiam", "xql": "cortex-xsiam", "xdr": "cortex-xdr-5.x", "xsoar": "cortex-xsoar-8-saas",
    "agentix": "cortex-agentix", "cloud": "cortex-cloud-posture-management", "cspm": "cortex-cloud-posture-management",
    "dspm": "cortex-cloud-posture-management", "ciem": "cortex-cloud-posture-management", "xpanse": "cortex-xpanse",
}
# Words in a question that name a product, most specific first. The default is XSIAM, the platform this lab runs on.
_PRODUCT_WORDS = (("agentix", "agentix"), ("xsoar", "xsoar"), ("xpanse", "xpanse"), ("dspm", "dspm"), ("cspm", "cspm"),
                  ("ciem", "ciem"), ("cortex cloud", "cloud"), ("xdr", "xdr"), ("xql", "xql"), ("xsiam", "xsiam"))


class DocsError(RuntimeError):
    """The docs site could not be reached or answered with something unusable. Carries a message fit for the operator."""


def get(url: str, accept: str = "text/markdown", timeout: int = TIMEOUT) -> str:
    """One GET against the docs host. The only function here that touches the network (tests replace it)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise DocsError(f"the docs site answered HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DocsError(f"could not reach the docs site ({exc})") from exc


def product_key(product: str | None, query: str = "") -> str:
    """`product` if it is a known key, else the product named in `query`, else xsiam."""
    if product and product.strip().lower() in BOOKS:
        return product.strip().lower()
    low = (query or "").lower()
    for word, key in _PRODUCT_WORDS:
        if word in low:
            return key
    return "xsiam"


def book_slug(book_or_product: str) -> str:
    """A book slug from a product key ('xsiam'), a slug ('cortex-xsiam') or a docs URL."""
    text = (book_or_product or "").strip()
    if text.lower() in BOOKS:
        return BOOKS[text.lower()]
    if text.startswith("http"):
        path = urllib.parse.urlsplit(text).path.strip("/")
        return path.split("/")[0] if path else ""
    return text.strip("/").split("/")[0]


# ---------------------------------------------------------------- sitemaps (cached for an hour)
_SITEMAPS: dict[str, tuple[float, list[str]]] = {}
_TTL = 3600


def sitemap(slug: str) -> list[str]:
    """Every page URL of a book, the book root first. Raises DocsError when the book does not exist."""
    now = time.time()
    hit = _SITEMAPS.get(slug)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    xml = get(f"{BASE_URL}/{slug}/sitemap-pages.xml", "application/xml")
    urls = [u.strip() for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)]
    if not urls:
        raise DocsError(f"no pages found for the book {slug!r}; known products: {', '.join(sorted(BOOKS))}")
    _SITEMAPS[slug] = (now, urls)
    return urls


def anchor_page(slug: str) -> str:
    """A real content page of the book to hang `?ask=` on (the book root does not answer it)."""
    pages = sitemap(slug)
    return pages[1] if len(pages) > 1 else pages[0]


def title_of(url: str) -> str:
    """A readable title from the last path segment: .../ingest-data-from-cribl -> 'Ingest data from cribl'."""
    last = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1].replace(".md", "")
    text = re.sub(r"[-_]+", " ", urllib.parse.unquote(last)).strip()
    return text[:1].upper() + text[1:] if text else url


# ---------------------------------------------------------------- Markdown cleaning
_HEADER = re.compile(r"\A\s*>\s*For the complete documentation index.*?\n", re.S)
_FOOTER = re.compile(r"\n#+\s*Agent Instructions.*|\n-{3,}\s*\nThis documentation is published with GitBook.*", re.S)


def clean(md: str, page_url: str = BASE_URL) -> str:
    """GitBook boilerplate, custom-block markers and root-relative links removed, so the text reads on its own."""
    md = _HEADER.sub("", md)
    md = _FOOTER.sub("", md)
    md = re.sub(r"\{%\s*(end)?(hint|stepper|step|tabs|tab|code)[^%]*%\}", "", md)
    md = re.sub(r"<div data-gb-custom-block[^>]*>|</div>", "", md)
    md = re.sub(r"\s*\[Broken mention\]\(broken://[^)]*\)", "", md)  # a link the site could not resolve; the text around it still reads
    md = re.sub(r"\]\((/[^)\s]*)", lambda m: "](" + BASE_URL + m.group(1), md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


# ---------------------------------------------------------------- ask
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def parse_answer(md: str) -> dict:
    """The three parts of an `?ask=` reply: the answer, the suggested follow-up questions and the source pages."""
    f = re.search(r"^#\s*Suggested Follow-up Questions:?\s*$", md, re.M)
    s = re.search(r"^#\s*Sources:?\s*$", md, re.M)
    cuts = [m.start() for m in (f, s) if m]
    answer = md[:min(cuts)] if cuts else md
    follow = md[f.end():(s.start() if s and s.start() > f.end() else len(md))] if f else ""
    sources = md[s.end():] if s else ""
    questions = []
    for text, url in _LINK.findall(follow):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("ask")
        questions.append(q[0] if q else text)
    seen, hits = set(), []
    for text, url in _LINK.findall(sources):
        url = re.sub(r"\.md$", "", url)
        if url not in seen:
            seen.add(url)
            hits.append({"title": text.strip(), "reader_url": url})
    answer = re.sub(r"\A\s*#\s+[^\n]*\n+", "", answer)  # the site starts its answer with the question as a heading
    return {"answer": clean(answer), "follow_ups": questions, "hits": hits}


def _plain(text: str, limit: int = 300) -> str:
    """A question the site accepts. Backticks, parentheses, brackets and similar punctuation make its edge answer 403 at once
    (seen on a question with `dedup` in backticks), so they become spaces, and the text is cut at `limit` characters."""
    return re.sub(r"\s+", " ", re.sub(r"[`()\[\]{}<>|;$\\^~\"]", " ", text or "")).strip()[:limit]


def ask(question: str, product: str | None = None, goal: str | None = None) -> dict:
    """Ask the docs a question. Returns {product, book, answer, follow_ups, hits: [{title, reader_url}]}."""
    key = product_key(product, question)
    slug = BOOKS[key]
    query = {"ask": _plain(question)}
    if goal:
        query["goal"] = _plain(goal)
    body = get(f"{anchor_page(slug)}.md?{urllib.parse.urlencode(query)}", timeout=ASK_TIMEOUT)
    if not body.strip():
        raise DocsError("the docs site returned an empty answer")
    return {"product": key, "book": slug, **parse_answer(body)}


# ---------------------------------------------------------------- pages
def _allowed(url: str) -> str:
    parts = urllib.parse.urlsplit(url if url.startswith("http") else BASE_URL + "/" + url.lstrip("/"))
    if parts.scheme != "https" or parts.netloc != urllib.parse.urlsplit(BASE_URL).netloc:
        raise DocsError(f"only pages on {urllib.parse.urlsplit(BASE_URL).netloc} can be fetched")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.removesuffix(".md").rstrip("/"), "", ""))


def fetch(url: str, max_chars: int = 12000) -> dict:
    """The Markdown of one docs page, cleaned and cut at `max_chars`."""
    page = _allowed(url)
    md = clean(get(page + ".md"), page)
    first = re.search(r"^#\s+(.+)$", md, re.M)
    truncated = len(md) > max_chars
    return {"title": first.group(1).strip() if first else title_of(page), "reader_url": page,
            "content": md[:max_chars], "truncated": truncated, "total_chars": len(md)}


def toc(book_or_product: str, max_items: int = 300) -> dict:
    """The pages of a book as {title, reader_url, depth}, in site order, cut at `max_items`."""
    slug = book_slug(book_or_product)
    if not slug:
        raise DocsError("give a product (xsiam, xdr, xsoar, agentix, cloud, xpanse) or a book slug")
    pages = sitemap(slug)
    items = []
    for url in pages[:max_items]:
        depth = len([p for p in urllib.parse.urlsplit(url).path.split("/") if p]) - 1
        items.append({"title": title_of(url), "reader_url": url, "depth": max(depth, 0)})
    return {"book": slug, "total_pages": len(pages), "items": items, "truncated": len(pages) > max_items}


def suggest(text: str, product: str | None = None, limit: int = 8) -> list[dict]:
    """Pages whose address contains every word of `text`: what a search box would offer while typing."""
    words = [w for w in re.split(r"\W+", (text or "").lower()) if w]
    if not words:
        return []
    out = []
    for url in sitemap(BOOKS[product_key(product, text)]):
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower().replace("-", " ").replace("_", " ")
        if all(w in path for w in words):
            out.append({"title": title_of(url), "reader_url": url})
            if len(out) >= limit:
                break
    return out
