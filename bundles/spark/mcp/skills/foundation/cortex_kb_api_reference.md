---
name: cortex_kb_api_reference
displayName: Cortex documentation site reference (GitBook)
category: foundation
description: 'How the Cortex documentation site works, for when a tool call behaves unexpectedly or the operator asks where an answer came from: GitBook pages as Markdown, the per-page question endpoint, per-book sitemaps, the books and their slugs, and what the site rejects. Load only when cortex_kb_search is not enough.'
icon: api
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Cortex documentation site reference

## Category

foundation

## What the site is

The Cortex documentation lives at `https://cortex-docs.paloaltonetworks.com`, a GitBook site. The `cortex-docs` connector needs no credential; it only reads this one host.

## The three things the site offers

| What | How | The tool that uses it |
|---|---|---|
| A page as clean Markdown | append `.md` to the page URL | `cortex-docs/fetch_topic` |
| An answer to a question, with its sources | `GET <any page>.md?ask=<question>` (optional `&goal=<what you are trying to do>`) | `cortex-docs/search`, `xql_lookup`, `deep_research` |
| The pages of a book | `GET /<book>/sitemap-pages.xml` | `cortex-docs/fetch_toc`, `suggest` |

The question endpoint searches the whole book, not only the page it hangs on. Its reply is Markdown: the answer, then `# Suggested Follow-up Questions:` (links whose `ask` parameter is the next question), then `# Sources:` (the pages used). The connector turns that into `answer`, `follow_ups` and `hits`.

## Books

Each product is a book with a slug: `cortex-xsiam` (about 2,200 pages), `cortex-xdr-5.x`, `cortex-xsoar-8-saas`, `cortex-agentix` (about 1,000), `cortex-cloud-posture-management`, `cortex-xpanse`. Release notes (`-rn`), API references (`xsiam-api`, `cortex-cloud-api`), the XSIAM developer guide and the older XDR and XSOAR versions are separate books. The book list is at `/sitemap.xml`.

## Behaviour to expect

- A question nobody asked before is answered live and takes about 30 seconds; asking it again returns in well under a second. The connector allows 90 seconds for a question and 30 for a page.
- Backticks, parentheses and similar punctuation in a question make the site's edge answer `403` at once. The connector replaces them with spaces.
- The book root (`/cortex-xsiam`) does not answer questions; the connector hangs the question on a real content page.
- Answers can contain links the site could not resolve (`broken://...`); the connector removes them.
- `fetch_topic` refuses any host except `cortex-docs.paloaltonetworks.com`.
