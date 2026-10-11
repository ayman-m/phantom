/**
 * Phantom marketplace endpoint — returns the three connectors that ship in
 * this bundle: xlog, caldera, xsiam. The connectors page (lifted from
 * Spark's workspace UI) calls /api/marketplace/connectors expecting a
 * GitHub-catalog-shaped JSON; in phantom standalone, the catalog IS the
 * bundle, so we serve hand-curated specs derived from the bundle's
 * `connectors/<id>/connector.yaml` files.
 *
 * If a connector ships in the bundle, it's marked `installed`. The
 * "instances" tab on the connectors page is the per-instance config
 * surface — that's where operator credentials live (filled in by the
 * setup form, materialized by the MCP into `connector_instances`).
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface Tool {
  name: string;
  method: string;
  description: string;
  args: Array<{
    name: string;
    type: string;
    description: string;
    required: boolean;
    defaultValue?: string;
  }>;
  outputPath?: string;
}

interface ConfigField {
  display: string;
  name: string;
  type: string;
  required: boolean;
  defaultValue?: string;
  options?: string[];
}

interface MarketplaceConnector {
  id: string;
  name: string;
  type: string;
  version: string;
  publisher: string;
  description: string;
  longDescription: string;
  category: string;
  tags: string[];
  icon: string;
  iconColor: string;
  iconBg: string;
  toolCount: number;
  installs: string;
  installCount: number;
  status: "installed" | "not_installed";
  reliability: string;
  authType: string;
  tools: Tool[];
  config: ConfigField[];
  versions: Array<{ version: string; date: string; changes: string[] }>;
  setupGuide: string;
  dockerImage: string;
  runtime: string;
  sdkLanguage: string;
  sdkPackage: string;
  ingestion: { enabled: boolean; mode: string; description: string };
  topAgents: Array<{ name: string; color: string }>;
}

const PHANTOM_CONNECTORS: MarketplaceConnector[] = [
  // ── xlog ────────────────────────────────────────────────────────────────
  {
    id: "xlog",
    name: "xlog",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Synthetic security log generation engine. Produces SYSLOG/CEF/JSON streams to webhooks, XSIAM, or files.",
    longDescription:
      "xlog is the log-generation backend for Phantom SOC simulation. It exposes a GraphQL API that the agent calls to spin up workers (port-scan, brute-force, malware-c2, exfil scenarios) which emit RFC-compliant logs into your downstream sink — XSIAM PAPI, webhook, or local file. Built on the rosetta-ce library.",
    category: "Security",
    tags: ["soc", "logs", "simulation", "xsiam"],
    icon: "data_object",
    iconColor: "#00f5ff",
    iconBg: "rgba(0, 245, 255, 0.12)",
    toolCount: 12,
    installs: "bundle-internal",
    installCount: 1,
    status: "installed",
    reliability: "stable",
    authType: "Bearer token",
    tools: [
      {
        name: "create_format_worker",
        method: "POST",
        description: "Spin up a worker that emits N logs/min in the given format (SYSLOG/CEF/JSON) to a sink.",
        args: [
          { name: "format", type: "enum", description: "SYSLOG | CEF | JSON", required: true },
          { name: "rate", type: "int", description: "logs per minute", required: true, defaultValue: "60" },
          { name: "sink", type: "url", description: "destination (webhook URL, XSIAM PAPI, or file://)", required: true },
        ],
      },
      {
        name: "create_scenario_worker",
        method: "POST",
        description: "Run a named scenario from scenarios/ready/*.json (port-scan, brute-force, etc.).",
        args: [
          { name: "scenario", type: "string", description: "scenario filename without .json", required: true },
        ],
      },
      {
        name: "list_workers",
        method: "GET",
        description: "List active log-generation workers with status/uptime.",
        args: [],
      },
      {
        name: "stop_worker",
        method: "POST",
        description: "Halt an active worker.",
        args: [{ name: "id", type: "string", description: "worker id", required: true }],
      },
      {
        name: "generate_coverage_report",
        method: "POST",
        description: "Run XQL queries against the configured XSIAM tenant and emit a coverage table.",
        args: [],
      },
    ],
    config: [
      // Field name matches bundles/spark/connectors/xlog/connector.yaml
      // (configSchema.properties.baseUrl); display name stays "xlog URL".
      // The default is https: xlog serves HTTPS on port 8000
      // unconditionally (mounts /tls/cert.pem from the shared phantom_tls
      // volume; uses TLS via priority-1 in its _resolve_ssl_args), so an
      // http URL fails at probe time with "Empty reply from server".
      { display: "xlog URL", name: "baseUrl", type: "url", required: true, defaultValue: "https://xlog:8000" },
      { display: "API Token", name: "apiToken", type: "secret", required: true },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "Set XLOG_URL to your xlog service (default https://xlog:8000) and XLOG_API_KEY to the matching bearer token.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-xlog-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-xlog-connector",
    ingestion: { enabled: true, mode: "push", description: "Worker logs are pushed to the configured sink" },
    topAgents: [{ name: "phantom-soc-simulation", color: "#00f5ff" }],
  },
  // ── caldera ─────────────────────────────────────────────────────────────
  {
    id: "caldera",
    name: "Caldera",
    type: "tool",
    version: "1.0.0",
    publisher: "MITRE / ayman-m",
    description:
      "MITRE Caldera — adversary emulation platform. Run operations, list abilities, drive red-team scenarios.",
    longDescription:
      "Caldera connector wraps Caldera 5.3's v2 REST API. The agent can list abilities, start/stop operations, and stream operation results. Used in Phantom for end-to-end attack-chain simulation alongside xlog for realistic telemetry.",
    category: "Security",
    tags: ["red-team", "mitre", "attack-emulation"],
    icon: "shield",
    iconColor: "#ff5f8a",
    iconBg: "rgba(255, 95, 138, 0.12)",
    toolCount: 9,
    installs: "bundle-internal",
    installCount: 1,
    status: "installed",
    reliability: "stable",
    authType: "API key (KEY: header)",
    tools: [
      {
        name: "list_abilities",
        method: "GET",
        description: "List all Caldera abilities with their MITRE ATT&CK technique mappings.",
        args: [],
      },
      {
        name: "list_adversaries",
        method: "GET",
        description: "List all adversary profiles available in this Caldera tenant.",
        args: [],
      },
      {
        name: "start_operation",
        method: "POST",
        description: "Kick off a Caldera operation against a group with a chosen adversary.",
        args: [
          { name: "name", type: "string", description: "operation name", required: true },
          { name: "adversary_id", type: "string", description: "adversary id", required: true },
          { name: "group", type: "string", description: "agent group", required: true, defaultValue: "red" },
        ],
      },
      {
        name: "list_operations",
        method: "GET",
        description: "List active and completed operations.",
        args: [],
      },
    ],
    config: [
      // Field name matches the canonical bundles/spark/connectors/caldera/
      // connector.yaml (configSchema.properties.baseUrl); a mismatch
      // would leave the connector with "caldera instance has no baseUrl
      // configured." Display name stays "Caldera URL".
      { display: "Caldera URL", name: "baseUrl", type: "url", required: true, defaultValue: "http://caldera:8888" },
      { display: "API Key", name: "apiKey", type: "secret", required: true },
      { display: "Red user", name: "redUser", type: "string", required: false, defaultValue: "red" },
      { display: "Red password", name: "redPassword", type: "secret", required: false },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "Provision a Caldera 5.3 instance, create an API key under Settings, and supply CALDERA_URL + CALDERA_API_KEY.",
    dockerImage: "aymanam/caldera:5.3.0",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-caldera-connector",
    ingestion: { enabled: false, mode: "pull", description: "Tools pull operation results on demand" },
    topAgents: [{ name: "phantom-soc-simulation", color: "#ff5f8a" }],
  },
  // ── xsiam ───────────────────────────────────────────────────────────────
  {
    id: "xsiam",
    name: "Cortex XSIAM",
    type: "tool",
    version: "1.0.0",
    publisher: "Palo Alto Networks / ayman-m",
    description:
      "Palo Alto Cortex XSIAM connector — execute XQL queries via PAPI, run remote scripts in the issue war room.",
    longDescription:
      "Bridges Phantom to your Cortex XSIAM tenant. The agent can run XQL queries, fetch detection results, list incidents, and execute remote scripts inside the war-room runtime. Used by validation skills to confirm that ingested logs actually triggered the expected XQL detections.",
    category: "Security",
    tags: ["siem", "xql", "cortex", "detection"],
    icon: "query_stats",
    iconColor: "#1f7bff",
    iconBg: "rgba(31, 123, 255, 0.12)",
    toolCount: 7,
    installs: "bundle-internal",
    installCount: 1,
    status: "installed",
    reliability: "stable",
    authType: "PAPI bearer + auth-id",
    tools: [
      {
        name: "execute_xql_query",
        method: "POST",
        description: "Run an XQL query against the XSIAM tenant and return rows.",
        args: [
          { name: "query", type: "string", description: "XQL query text", required: true },
          { name: "tenant_id", type: "string", description: "XSIAM tenant id", required: false },
        ],
      },
      {
        name: "list_incidents",
        method: "GET",
        description: "List recent XSIAM incidents.",
        args: [],
      },
      {
        name: "execute_remote_script",
        method: "POST",
        description: "Run a script in the issue war room.",
        args: [
          { name: "script", type: "string", description: "script content", required: true },
        ],
      },
    ],
    config: [
      // Field names (api_url/api_key/api_id) match the Cortex XDR connector.
      // Connector code + probe also accept the older papiUrl/papiAuthHeader/
      // papiAuthId pair at read time.
      { display: "API URL", name: "api_url", type: "url", required: true },
      { display: "API key", name: "api_key", type: "secret", required: true },
      { display: "API ID", name: "api_id", type: "string", required: true },
      { display: "Playground ID", name: "playgroundId", type: "string", required: true },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "In XSIAM, create a PAPI key with detection-read + remote-script-exec scopes, then supply CORTEX_MCP_PAPI_* env values.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-xsiam-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-xsiam-connector",
    ingestion: { enabled: false, mode: "pull", description: "Queries run on demand" },
    topAgents: [{ name: "phantom-soc-simulation", color: "#1f7bff" }],
  },
  // ── web ────────────────────────────────────────────────────────
  {
    id: "web",
    name: "Web Browser",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Headless browser tools — fetch web pages, extract text/links, screenshot, click, fill forms. Backed by a profile-gated chromedp/headless-shell sidecar.",
    longDescription:
      "Lets the agent reach the public web for IOC pivots, vendor advisories, threat-intel portal scraping, and 'go read this CVE writeup' requests. Talks to phantom-browser (a profile-gated sidecar) over Chrome DevTools Protocol via Playwright Python. The Allowed Domains list is the primary safety control — restrict the agent to vetted hosts. By default web.navigate is approval-gated; use the chat-header dropdown or a job's bypass slider to opt out per session/job.",
    category: "Security",
    tags: ["browser", "scraping", "intel"],
    icon: "language",
    iconColor: "#a855f7",
    iconBg: "rgba(168, 85, 247, 0.12)",
    toolCount: 10,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "preview",
    authType: "None (internal CDP)",
    tools: [
      {
        name: "navigate",
        method: "goto",
        description: "Open a URL in a new or existing page. Approval-gated by default.",
        args: [
          { name: "url", type: "string", description: "Absolute URL to navigate to.", required: true },
          { name: "session_id", type: "string", description: "Reuse a tab across calls; omit for one-shot.", required: false },
        ],
      },
      {
        name: "get_text",
        method: "innerText + readability",
        description: "Extract main-content text (Trafilatura), or document.body.innerText. Token-efficient for LLM consumption.",
        args: [
          { name: "session_id", type: "string", description: "Page handle.", required: true },
          { name: "mode", type: "string", description: "'readable' | 'body' | 'markdown'.", required: false },
        ],
      },
      {
        name: "screenshot",
        method: "page.screenshot",
        description: "Capture base64 PNG of the page (or JPEG for smaller payload).",
        args: [{ name: "session_id", type: "string", description: "Page handle.", required: true }],
      },
      {
        name: "click",
        method: "page.click",
        description: "Click an element matched by CSS / text= / role= selector.",
        args: [
          { name: "session_id", type: "string", description: "Page handle.", required: true },
          { name: "selector", type: "string", description: "Playwright selector.", required: true },
        ],
      },
      {
        name: "fill",
        method: "page.fill",
        description: "Type a value into an input/textarea matched by selector.",
        args: [
          { name: "session_id", type: "string", description: "Page handle.", required: true },
          { name: "selector", type: "string", description: "Playwright selector.", required: true },
          { name: "value", type: "string", description: "Text to fill in.", required: true },
        ],
      },
      {
        name: "extract_links",
        method: "querySelectorAll a[href]",
        description: "Return all links on the page with text + href + host.",
        args: [{ name: "session_id", type: "string", description: "Page handle.", required: true }],
      },
    ],
    config: [
      {
        display: "CDP URL",
        name: "cdp_url",
        type: "text",
        required: true,
        defaultValue: "http://phantom-browser:9222",
      },
      {
        display: "Default timeout (ms)",
        name: "default_timeout_ms",
        type: "text",
        required: false,
        defaultValue: "30000",
      },
      {
        display: "User-Agent override",
        name: "user_agent",
        type: "text",
        required: false,
      },
      {
        display: "Allowed Domains",
        name: "allowed_domains",
        type: "array",
        required: false,
        defaultValue: "[]",
      },
      {
        display: "Block resource types",
        name: "block_resource_types",
        type: "array",
        required: false,
        defaultValue: "[]",
      },
      {
        display: "Default extractor mode",
        name: "extractor_mode",
        type: "select",
        required: false,
        defaultValue: "readable",
        options: ["readable", "body", "markdown"],
      },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "1) Bring up the sidecar: `docker compose --profile browser up -d phantom-browser`. 2) Click 'Add instance', leave cdp_url as the default. 3) Set Allowed Domains to your vetted threat-intel + vendor-doc hosts (use `.example.com` to match all subdomains). 4) Save. The agent will see web.* tools on its next refresh.",
    dockerImage: "ghcr.io/ayman-m/phantom-browser-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-web-connector",
    ingestion: {
      enabled: false,
      mode: "pull",
      description: "Pages are fetched on demand by the agent — no continuous ingestion.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#a855f7" }],
  },
  // ── cortex-docs ─────────────────────────────────────────────────
  {
    id: "cortex-docs",
    name: "Cortex Docs",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Ask the public Palo Alto Networks Cortex documentation (XDR / XSIAM / XSOAR / Cortex Cloud / AgentiX / Xpanse / XQL) a question and read its pages. Six tools: question search with sources, page suggestions, focused XQL stage and function lookup, page fetch, book listing, and multi-question research briefs.",
    longDescription:
      "Bridges the agent's query-authoring path with authoritative Palo Alto Cortex documentation, which now lives on GitBook (cortex-docs.paloaltonetworks.com). cortex-docs/search asks the docs a question in plain words and returns the docs' own answer, the pages it came from and follow-up questions; cortex-docs/xql_lookup asks the same about one XQL stage or function (dedup, alter, arrayindexof, json_extract_scalar) and pairs with the cortex_xql_query_authoring foundation skill; fetch_topic reads one page as Markdown; fetch_toc lists a book; deep_research chains the docs' follow-up questions into a brief with citations. A question nobody asked before takes about 30 seconds; a repeat returns at once. Public site, no credentials, and only cortex-docs.paloaltonetworks.com pages can be fetched.",
    category: "Security",
    tags: ["cortex", "xql", "documentation", "research", "palo-alto"],
    icon: "menu_book",
    iconColor: "#fa582d",
    iconBg: "rgba(250, 88, 45, 0.12)",
    toolCount: 6,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "stable",
    authType: "None (public Cortex documentation)",
    tools: [
      {
        name: "search",
        method: "GET <page>.md?ask=<question>",
        description:
          "Ask the Palo Alto Networks Cortex documentation (XDR, XSIAM, XSOAR, Cortex Cloud, AgentiX, Xpanse) a question in plain words. Returns the docs' own answer, the pages it came from (`hits`, each with a `reader_url`) and follow-up questions. Auto-detects the product from the question when `product` is omitted (XSIAM when none is named). Use cortex_fetch_topic with a `reader_url` for a page's full text.",
        args: [
          { name: "query", type: "string", description: "A question or topic in plain words, e.g. 'How do I send logs to XSIAM from Cribl?'.", required: true },
          { name: "product", type: "string", description: "Optional scope: agentix, xdr, xsiam, xsoar, xql, cloud, dspm, cspm, ciem, xpanse. When omitted, read from the question.", required: false },
          { name: "per_page", type: "integer", description: "At most this many source pages in `hits` (1-100, default 20).", required: false },
          { name: "page", type: "integer", description: "Accepted for compatibility; the docs site answers a question and does not paginate.", required: false },
        ],
      },
      {
        name: "suggest",
        method: "GET <book>/sitemap-pages.xml",
        description:
          "Pages whose address contains every word typed so far (what a search box offers while you type).",
        args: [
          { name: "input_text", type: "string", description: "Partial search text, e.g. 'ingest cribl'.", required: true },
          { name: "product", type: "string", description: "Optional product scope (same vocabulary as cortex_search).", required: false },
        ],
      },
      {
        name: "xql_lookup",
        method: "GET <page>.md?ask=<question>",
        description:
          "What one XQL stage or function does, with its syntax, arguments and examples, as answered by the docs. Pass the bare name (dedup, comp, arrayindexof, json_extract_scalar); a leading \"stage\", \"function\" or \"XQL\" is ignored. Use it before writing an XQL query that uses a stage or function you are not sure of.",
        args: [
          { name: "term", type: "string", description: "Stage or function name, e.g. dedup or arrayindexof.", required: true },
          { name: "kind", type: "string", description: "'auto' (default), 'stage' or 'function'.", required: false },
          { name: "product", type: "string", description: "Product scope; default xql (the XSIAM/XDR language reference).", required: false },
          { name: "per_page", type: "integer", description: "At most this many source pages are listed (default 8).", required: false },
          { name: "suggest", type: "boolean", description: "Also return pages whose address matches the term (default false).", required: false },
        ],
      },
      {
        name: "fetch_topic",
        method: "GET <page>.md",
        description:
          "The Markdown of one documentation page, cleaned. Pass a `reader_url` from cortex_search, cortex_suggest or cortex_fetch_toc. Only pages on cortex-docs.paloaltonetworks.com can be fetched.",
        args: [
          { name: "url", type: "string", description: "The page address (a hits[].reader_url, or a path such as /cortex-xsiam/...).", required: true },
          { name: "max_chars", type: "integer", description: "Cut the content at this many characters (default 12000); `truncated` says when it was cut.", required: false },
        ],
      },
      {
        name: "fetch_toc",
        method: "GET <book>/sitemap-pages.xml",
        description:
          "The pages of one documentation book in site order, with their depth. XSIAM has over 2,000 pages, so the list is cut at `max_items`; prefer cortex_search or cortex_suggest to find a page.",
        args: [
          { name: "book", type: "string", description: "A product (xsiam, xdr, xsoar, agentix, cloud, xpanse), a book slug (cortex-xsiam) or a page URL of the book.", required: true },
          { name: "max_items", type: "integer", description: "Cut the list after this many pages (default 300).", required: false },
        ],
      },
      {
        name: "deep_research",
        method: "GET <page>.md?ask=<question> (several)",
        description:
          "Research a topic across several linked questions and return one brief with citations: it asks the docs the request, then the follow-up questions the docs suggest, up to `max_sections` questions. Slower than cortex_search (a few seconds per question); use it for a deliverable, not a single fact.",
        args: [
          { name: "request", type: "string", description: "What to research, e.g. 'How XSIAM ingests data from Cribl, and what each source needs'.", required: true },
          { name: "max_sections", type: "integer", description: "At most this many questions (1-12, default 3; a new question takes about 30 seconds, and it stops starting new ones after 75 seconds).", required: false },
          { name: "hits_per_section", type: "integer", description: "At most this many sources kept per section (default 4).", required: false },
          { name: "enable_gap_check", type: "boolean", description: "Accepted for compatibility; ignored (the docs site searches the whole book per question).", required: false },
          { name: "model", type: "string", description: "Accepted for compatibility; ignored (no model is used).", required: false },
        ],
      },
    ],
    config: [],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "1) Click 'Add instance' on the cortex-docs row. 2) There is nothing to configure: the Cortex documentation is public and needs no credentials. 3) Save. The agent will see cortex-docs.* tools on the next refresh and the cortex_xql_query_authoring skill becomes operational.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-cortex-docs-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-cortex-docs-connector",
    ingestion: {
      enabled: false,
      mode: "pull",
      description: "Cortex docs are fetched on demand per tool call — no continuous ingestion.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#fa582d" }],
  },
  // ── cortex-content ──────────────────────────────────────────────
  {
    id: "cortex-content",
    name: "Cortex Content",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Cortex content catalog bundled with Phantom — XSIAM/XSOAR content packs, ModelingRules, ParsingRules, CorrelationRules. Ten tools for listing/searching packs, fetching rule bundles, plus index_kb to embed pack content into the agent's semantic-search KB.",
    longDescription:
      "Gives the chat agent a reference for canonical XSIAM content. When operators ask 'show me how Cortex models cisco_esa_raw' or 'pull the F5APM modeling rule so I can adapt it', the agent uses cortex-content/get_modeling_rule to fetch the three-file bundle (.xif + .yml + _schema.json) from the local catalog. The agent uses these as references when authoring or updating data models for the operator's tenant — instead of guessing XDM paths (which produces broken parsers), it can ground each mapping against the canonical implementation. cortex_index_kb walks a pack's rules and upserts each into the agent's knowledge_search KB (kb_name='cortex-content'), enabling semantic search across the ~200 packs that ship ModelingRules without round-tripping through list/get tools per rule. Idempotent — source_hash dedupe means re-indexing is cheap. All reads are local file reads; no network calls.",
    category: "Security",
    tags: ["cortex", "xsiam", "xdm", "modeling-rules", "parsing-rules", "correlation-rules", "kb-embedding"],
    icon: "library_books",
    iconColor: "#1963b3",
    iconBg: "rgba(25, 99, 179, 0.12)",
    toolCount: 10,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "stable",
    authType: "None — local catalog bundled with Phantom.",
    tools: [
      {
        name: "list_packs",
        method: "internal — pack listing",
        description:
          "List all packs in the bundled catalog, optionally filtered by supportedModules. Returns name + description + version + supportedModules per pack.",
        args: [
          { name: "supported_module", type: "string", description: "Filter by supportedModules (e.g. 'xsiam', 'agentix').", required: false },
          { name: "limit", type: "integer", description: "Max packs per page (default 100, max 500).", required: false },
          { name: "offset", type: "integer", description: "Pagination offset (default 0).", required: false },
        ],
      },
      {
        name: "search_packs",
        method: "GET + fuzzy match",
        description: "Fuzzy-search packs by name/description/keywords/categories.",
        args: [
          { name: "query", type: "string", description: "Search term — vendor / log source / category.", required: true },
          { name: "limit", type: "integer", description: "Max results (default 20, max 100).", required: false },
        ],
      },
      {
        name: "get_pack",
        method: "internal — pack lookup",
        description: "Fetch pack_metadata.json + top-level file tree + README for one pack.",
        args: [
          { name: "pack_name", type: "string", description: "Exact pack name (e.g. 'F5APM').", required: true },
        ],
      },
      {
        name: "list_modeling_rules",
        method: "internal — ModelingRules listing",
        description: "List ModelingRules directories under a pack with their datasets parsed from _schema.json.",
        args: [
          { name: "pack_name", type: "string", description: "Pack to list ModelingRules under.", required: true },
        ],
      },
      {
        name: "get_modeling_rule",
        method: "internal — three-file bundle",
        description:
          "Fetch the three-file bundle for ONE modeling rule: .xif (XQL code), .yml (metadata), _schema.json (dataset → field-type schema).",
        args: [
          { name: "pack_name", type: "string", description: "Pack containing the rule.", required: true },
          { name: "rule_name", type: "string", description: "Modeling rule directory name (usually same as pack name).", required: true },
        ],
      },
      {
        name: "list_parsing_rules",
        method: "internal — ParsingRules listing",
        description: "List ParsingRules directories under a pack.",
        args: [
          { name: "pack_name", type: "string", description: "Pack to list ParsingRules under.", required: true },
        ],
      },
      {
        name: "get_parsing_rule",
        method: "internal — three-file bundle",
        description: "Fetch .xif + .yml + _schema.json for one parsing rule.",
        args: [
          { name: "pack_name", type: "string", description: "Pack containing the rule.", required: true },
          { name: "rule_name", type: "string", description: "Parsing rule directory name.", required: true },
        ],
      },
      {
        name: "list_correlation_rules",
        method: "internal — CorrelationRules listing",
        description: "List CorrelationRules directories under a pack.",
        args: [
          { name: "pack_name", type: "string", description: "Pack to list CorrelationRules under.", required: true },
        ],
      },
      {
        name: "get_correlation_rule",
        method: "internal — .yml + .xql",
        description: "Fetch the .yml metadata + .xql query for one correlation rule.",
        args: [
          { name: "pack_name", type: "string", description: "Pack containing the rule.", required: true },
          { name: "rule_name", type: "string", description: "Correlation rule name.", required: true },
        ],
      },
    ],
    config: [],
    setupGuide:
      "No setup required. The Cortex content catalog is bundled with Phantom and read from local files — no configuration, no network, no credentials.",
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    dockerImage: "ghcr.io/ayman-m/phantom-connector-cortex-content-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-cortex-content-connector",
    ingestion: {
      enabled: false,
      mode: "pull",
      description: "Pack content fetched on demand per tool call; cached locally for 24h by default.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#1963b3" }],
  },

  // ── cortex-xdr ───────────────
  {
    id: "cortex-xdr",
    name: "Cortex XDR",
    type: "tool",
    version: "1.0.0",
    publisher: "Palo Alto Networks / ayman-m",
    description:
      "Cortex XDR API wrapper — list incidents and alerts, drill into specific cases, and run XQL queries against the XDR data lake. General-purpose interface for incident response, threat hunting, investigation reporting, and detection coverage validation.",
    longDescription:
      "Phantom's interface to your Cortex XDR tenant's Public API. The chat agent can answer operator questions like 'show me unresolved high-severity incidents in the last 24 hours', 'pull the alerts from incident <id>', or 'run XQL: dataset=xdr_data | filter agent_hostname=\"win-host-01\" and event_type=ENUM.PROCESS | dedup actor_process_image_name | limit 50'. Four tools cover the core read paths: get_cases_and_issues (incident listing with filters by time, endpoint, severity, status), get_incident_extra_data (full alerts + network/file artifacts for a specific incident), run_xql_query (synchronous XQL with bounded polling — returns rows when complete or execution_id for long queries), and get_xql_results (poll an in-flight async execution). Same Cortex Public API family + Authorization + x-xdr-auth-id auth pattern as XSIAM; unified api_url / api_id / api_key field names. Use cases: incident response (triage + drill-down), threat hunting (XQL ad-hoc queries), investigation reporting (incident details + related artifacts), and detection coverage validation (combine with Phantom's caldera connector — fire attacks, then query XDR for what fired). Read-only: no write/action endpoints (isolate endpoint, run remote script, etc.).",
    category: "Security",
    tags: ["cortex", "xdr", "edr", "siem", "incidents", "alerts", "xql", "threat-hunting", "investigation", "incident-response"],
    icon: "shield_lock",
    iconColor: "#ef4444",
    iconBg: "rgba(239, 68, 68, 0.12)",
    toolCount: 4,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "stable",
    authType: "XDR Advanced API Key + auth-id",
    tools: [
      {
        name: "get_cases_and_issues",
        method: "POST /incidents/get_incidents",
        description: "List Cortex XDR incidents (cases) and the alerts (issues) within them. Supports filters by time, endpoint, severity, status.",
        args: [
          { name: "from_time", type: "string", description: "ISO timestamp lower bound. Default: 24h ago.", required: false },
          { name: "to_time", type: "string", description: "ISO timestamp upper bound. Default: now.", required: false },
          { name: "endpoint", type: "string", description: "Filter by endpoint hostname.", required: false },
          { name: "severity", type: "array", description: "Subset of ['low','medium','high','critical'].", required: false },
          { name: "status", type: "array", description: "Subset of XDR status values.", required: false },
          { name: "limit", type: "integer", description: "Max incidents (default 50, max 100).", required: false },
        ],
      },
      {
        name: "get_incident_extra_data",
        method: "POST /incidents/get_incident_extra_data",
        description: "Drill into one incident — full alerts, network/file artifacts, related users/hosts.",
        args: [
          { name: "incident_id", type: "string", description: "From a prior get_cases_and_issues hit.", required: true },
          { name: "alerts_limit", type: "integer", description: "Cap on alerts returned (default 50).", required: false },
        ],
      },
      {
        name: "run_xql_query",
        method: "POST /xql/start_xql_query + poll /xql/get_query_results",
        description: "Execute an XQL query synchronously against the XDR data lake. Returns rows if complete within the poll window, or execution_id if still running.",
        args: [
          { name: "query", type: "string", description: "XQL query text.", required: true },
          { name: "tenant_ids", type: "array", description: "Optional multi-tenant scope.", required: false },
          { name: "timeframe_from", type: "string", description: "ISO timestamp lower bound.", required: false },
          { name: "timeframe_to", type: "string", description: "ISO timestamp upper bound. Default: now.", required: false },
        ],
      },
      {
        name: "get_xql_results",
        method: "POST /xql/get_query_results",
        description: "Retrieve results from an in-flight XQL query by execution_id.",
        args: [
          { name: "execution_id", type: "string", description: "From a prior run_xql_query call.", required: true },
          { name: "limit", type: "integer", description: "Max rows (default 1000, max 10000).", required: false },
        ],
      },
    ],
    // Unified api_url / api_id / api_key field names, matching the XSIAM
    // connector. Both connectors share the same Cortex Public API auth
    // model — operators don't translate.
    config: [
      { display: "API URL", name: "api_url", type: "url", required: true },
      { display: "API key", name: "api_key", type: "secret", required: true },
      { display: "API ID", name: "api_id", type: "string", required: true },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "1) In the Cortex XDR console, navigate to Settings → Configurations → API Keys. 2) Generate a key with 'Advanced' security level (required for x-xdr-auth-id header path). 3) Copy the api_id (integer next to the key), api_key (long alphanumeric — paste raw, no 'Bearer' prefix), and api_url (format: https://api-yourtenant.xdr.us.paloaltonetworks.com). 4) Click 'Add instance' on the Cortex XDR card. 5) Paste, save. 6) Click 'Test Connection' on the new instance card — green check means creds valid. 7) Try natural-language queries via chat: 'show me unresolved high-severity incidents in the last 24h', 'pull the alerts from incident <id>', 'run XQL to count process events on hostname X yesterday'. The agent picks the right tool (get_cases_and_issues / get_incident_extra_data / run_xql_query) automatically based on your question.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-cortex-xdr-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-spark-cortex-xdr-connector",
    ingestion: {
      enabled: false,
      mode: "pull",
      description: "Incidents + XQL results fetched on demand per tool call. No background polling.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#ef4444" }],
  },

  // ── http-sender (ships in the release as a bundle connector) ──
  // Tools are overlaid live from connectors/http-sender/connector.yaml (see
  // loadLiveTools below); the config[] here must match that file's configSchema
  // + secretSlots, because the Add-instance form is built from it.
  {
    id: "http-sender",
    name: "HTTP Sender",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Send synthetic JSON events to a Cortex XSIAM HTTP Log Collector, or to the Cortex Cribl integration endpoint under a source's own identifier so the Analytics detectors treat them as that vendor's native feed.",
    longDescription:
      "Phantom's sender for sources that Cortex collects over HTTP or through its Cribl integration. A collector you create in your own tenant fixes the vendor, the product and so the dataset; this connector posts one JSON object per event to it. Built-in event profiles cover Okta System Log, Proofpoint TAP, Google Workspace (Drive and Login), AWS CloudTrail, GCP Cloud Audit, Azure AD audit and Windows Security events. Every profile has benign baseline scenarios (stable identities, so a baseline exists) and one attack scenario per proven detector (fresh identities on every call). Four tools: list_destinations (the collectors and Cribl sources this instance can reach), send_test_event (one identifiable event, to prove a destination before anything else), generate_events (a built-in profile and scenario, with counts, timing and identities handled for you) and send_events (your own JSON objects, sent as given). With the Cribl endpoint and token configured, each Cribl source is its own destination (cribl_okta_sso, cribl_aws_audit, cribl_gcp_cloud_logging, cribl_azure_ad_audit, cribl_azure_ad_signins, cribl_azure_event_hub, cribl_windows_events, cribl_proofpoint_tap). cribl_windows_events takes the same structured Windows events as the WEC Sender and renders the XML itself, so the Windows identity detectors can fire without a Broker or a certificate. Events go only to the collector URLs and Cribl endpoint you configure, in your own tenant; a collector with the source's content pack installed gets parsing and modeling, one without it is raw-only.",
    category: "Security",
    tags: ["http", "http-collector", "cribl", "log-generation", "xsiam", "okta", "aws", "gcp", "azure", "windows"],
    icon: "cloud_upload",
    iconColor: "#2dd4bf",
    iconBg: "rgba(45, 212, 191, 0.12)",
    toolCount: 4,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "stable",
    authType: "Collector API key (+ Cribl token, optional)",
    tools: [],
    config: [
      { display: "Collector URL", name: "collectorUrl", type: "url", required: true },
      { display: "Vendor (as set on the collector)", name: "vendor", type: "string", required: true },
      { display: "Product (as set on the collector)", name: "product", type: "string", required: true },
      { display: "Collector API key", name: "collectorKey", type: "secret", required: true },
      { display: "Additional destinations (JSON array)", name: "additionalDestinations", type: "string", required: false },
      { display: "Additional destination keys (JSON object)", name: "additionalKeys", type: "secret", required: false },
      { display: "Cribl endpoint URL", name: "criblUrl", type: "url", required: false },
      { display: "Cribl token", name: "criblToken", type: "secret", required: false },
      { display: "Cribl integration name", name: "criblIntegration", type: "string", required: false, defaultValue: "phantom-http-sender" },
      { display: "User domain for generated identities", name: "userDomain", type: "string", required: false, defaultValue: "phantom-lab.example" },
      { display: "DNS suffix for Windows computer names", name: "windowsDnsSuffix", type: "string", required: false, defaultValue: "phantom.lab" },
      { display: "Verify the collector's TLS certificate", name: "verifyTls", type: "boolean", required: false, defaultValue: "true" },
      { display: "Request timeout (seconds)", name: "timeoutSeconds", type: "number", required: false, defaultValue: "15" },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "1) In Cortex, open Settings → Data Sources & Integrations → Custom Collectors and add an HTTP Log Collector: Log Format JSON, plus the Vendor and Product of the source you want to simulate. Use Save & Generate Token and copy the URL and the key (the key is shown once). 2) Click 'Add instance' on the HTTP Sender card, paste the collector URL, the vendor, the product and the key. More collectors go in 'Additional destinations' with their keys in 'Additional destination keys'. 3) For native Analytics treatment, create a Cribl collector in the same place, paste its endpoint URL and token, and each Cribl source appears as a cribl_<source> destination. 4) Ask the agent to run list_destinations, then send_test_event to a destination: it sends one identifiable event and says whether Cortex accepted it. 5) Ask for a scenario, for example 'send a benign Okta baseline' and then 'run the Okta password-spray scenario', or open a Cortex Analytics trigger skill that names this connector. The collector decides the dataset, so check where the test event landed before trusting a name.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-http-sender-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-connector-http-sender",
    ingestion: {
      enabled: false,
      mode: "push",
      description: "Events are built and sent on demand per tool call, or by a scheduled job that calls the tool. Nothing runs in the background by itself.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#2dd4bf" }],
  },

  // ── wec-sender (ships in the release as a bundle connector) ──
  {
    id: "wec-sender",
    name: "WEC Sender",
    type: "tool",
    version: "1.0.0",
    publisher: "ayman-m",
    description:
      "Deliver synthetic Windows events to your Cortex Broker VM's Windows Event Collector over WS-Management with mutual TLS, so they ingest as a real Windows Event Collector feed.",
    longDescription:
      "Phantom's sender for the Windows detections that only a Windows Event Collector feed can reach. The Broker stamps every event it receives through its WEC applet with _collector_type = WEC; that value cannot be set from an event body, so the parsing rules, the Analytics detectors and the identity entities that depend on it are out of reach over syslog or CEF. This connector acts as a source-initiated Windows forwarder: it enumerates the collector's subscriptions and pushes events to it over WS-Management (mutual TLS, TCP 5986) with the client certificate you issue in the Cortex console. Four tools: list_subscriptions (what the collector will accept), send_test_event (one identifiable Windows event), generate_events (a built-in Windows profile and scenario: logons, administrative activity and one attack scenario per Windows trigger skill) and send_events (your own structured events, rendered to Windows Event XML for you). It needs a Broker VM with the Windows Event Collector applet enabled and reachable on TCP 5986, plus the client certificate bundle and its password. It sends only to the Broker you configure, in your own environment. If you have no Broker, the HTTP Sender's cribl_windows_events destination fires the same Windows detectors without one (AD FS events still need a Windows Event Collector).",
    category: "Security",
    tags: ["wec", "windows", "log-generation", "xsiam", "ws-management"],
    icon: "desktop_windows",
    iconColor: "#60a5fa",
    iconBg: "rgba(96, 165, 250, 0.12)",
    toolCount: 4,
    installs: "bundle-internal",
    installCount: 0,
    status: "installed",
    reliability: "stable",
    authType: "Client certificate (mutual TLS)",
    tools: [],
    config: [
      { display: "Subscription Manager URL", name: "subscriptionManagerUrl", type: "string", required: true },
      { display: "Client certificate bundle (PFX, base64)", name: "clientPfx", type: "secret", required: true },
      { display: "Client certificate password", name: "clientPfxPassword", type: "secret", required: true },
      { display: "Sender computer name", name: "senderComputerName", type: "string", required: false, defaultValue: "phantom-wec-sender.phantom.lab" },
      { display: "Domain NetBIOS name", name: "domainNetbios", type: "string", required: false, defaultValue: "PHANTOM" },
      { display: "Domain DNS suffix", name: "domainDns", type: "string", required: false, defaultValue: "phantom.lab" },
      { display: "Hosts in the synthetic domain", name: "hostCount", type: "number", required: false, defaultValue: "32" },
      { display: "Request timeout (seconds)", name: "timeoutSeconds", type: "number", required: false, defaultValue: "30" },
    ],
    versions: [{ version: "1.0.0", date: "", changes: ["Initial release."] }],
    setupGuide:
      "1) In the Cortex console, create a Windows Event Collector configuration on your Broker VM (the applet must be enabled, and TCP 5986 must be reachable from where Phantom runs). It gives you the Subscription Manager value, a client certificate bundle (PFX) and its password. 2) Base64-encode the PFX on one line: base64 < client.pfx | tr -d '\\n'. 3) Click 'Add instance' on the WEC Sender card and paste the Subscription Manager value, the base64 text and the password. The certificate and password are stored as secrets and never pass through the chat. 4) Ask the agent to run list_subscriptions: a list of subscriptions means the certificate and the route work. 5) Run send_test_event, then a scenario, for example 'run the Windows password-spray scenario', or open a Cortex Analytics trigger skill that names this connector.",
    dockerImage: "ghcr.io/ayman-m/phantom-connector-wec-sender-oss:latest",
    runtime: "python",
    sdkLanguage: "Python",
    sdkPackage: "phantom-connector-wec-sender",
    ingestion: {
      enabled: false,
      mode: "push",
      description: "Events are built and forwarded on demand per tool call, or by a scheduled job that calls the tool. Nothing runs in the background by itself.",
    },
    topAgents: [{ name: "phantom-soc-simulation", color: "#60a5fa" }],
  },
];

/**
 * Overlay live `spec.tools[]` from each connector.yaml on top of the
 * hardcoded metadata. The toolCount + tools[] arrays here are
 * hand-maintained and would drift from the real tool surface, so the
 * live YAML wins.
 *
 * Resolution order for the bundle dir:
 *   1. /app/bundle/connectors/<id>/connector.yaml   (production, image-mounted)
 *   2. <repo>/bundles/spark/connectors/<id>/connector.yaml  (local dev)
 *
 * If neither exists OR the YAML parse fails, fall back to the hardcoded
 * tools[] + toolCount for that entry so the UI stays functional.
 */
async function loadLiveTools(connectorId: string): Promise<Tool[] | null> {
  const fs = await import("fs/promises");
  const path = await import("path");
  const yaml = await import("js-yaml");

  const candidates = [
    `/app/bundle/connectors/${connectorId}/connector.yaml`,
    path.resolve(
      process.cwd(),
      "..",
      "..",
      "bundles",
      "spark",
      "connectors",
      connectorId,
      "connector.yaml",
    ),
    // Inside the build at agent's working dir (cwd=mcp/agent in dev)
    path.resolve(process.cwd(), "bundles", "spark", "connectors", connectorId, "connector.yaml"),
  ];

  for (const p of candidates) {
    try {
      const text = await fs.readFile(p, "utf-8");
      const doc = yaml.load(text) as { spec?: { tools?: Array<Record<string, unknown>> } };
      const yamlTools = doc?.spec?.tools;
      if (!Array.isArray(yamlTools)) return null;
      const out: Tool[] = [];
      for (const t of yamlTools) {
        const name = typeof t.name === "string" ? t.name : null;
        if (!name) continue;
        const method =
          typeof t.method === "string"
            ? t.method.startsWith("GET")
              ? "GET"
              : t.method.startsWith("PUT")
                ? "PUT"
                : t.method.startsWith("DELETE")
                  ? "DELETE"
                  : t.method.startsWith("POST")
                    ? "POST"
                    : "POST"
            : "POST";
        const description =
          typeof t.description === "string"
            ? t.description.trim().split("\n")[0].slice(0, 220)
            : "";
        const args: Tool["args"] = [];
        if (Array.isArray(t.args)) {
          for (const a of t.args as Array<Record<string, unknown>>) {
            const aname = typeof a.name === "string" ? a.name : null;
            if (!aname) continue;
            args.push({
              name: aname,
              type: typeof a.type === "string" ? a.type : "string",
              description: typeof a.description === "string" ? a.description : "",
              required: a.required === true,
              defaultValue:
                typeof a.defaultValue === "string"
                  ? a.defaultValue
                  : typeof a.default === "string"
                    ? a.default
                    : undefined,
            });
          }
        }
        out.push({ name, method, description, args });
      }
      return out;
    } catch {
      // try next candidate
    }
  }
  return null;
}

export async function GET() {
  // Build a deep copy so concurrent requests don't see each other's overlay
  const out = PHANTOM_CONNECTORS.map((c) => ({ ...c, tools: [...c.tools] }));
  await Promise.all(
    out.map(async (c) => {
      const live = await loadLiveTools(c.id);
      if (live && live.length > 0) {
        c.tools = live;
        c.toolCount = live.length;
      }
    }),
  );
  return NextResponse.json(out);
}
