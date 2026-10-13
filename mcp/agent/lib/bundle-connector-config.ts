/**
 * The instance-form fields of the nine bundle connectors, by connector id.
 *
 * app/api/marketplace/connectors/route.ts puts each list on its card, and both
 * Create and Edit on /connectors render the form from it, so a field missing
 * here can never be filled in from the UI. Each list must match that
 * connector's connector.yaml (bundles/spark/connectors/<id>/connector.yaml):
 * every configSchema property and every secretSlot, with the same name, the
 * same required flag, the same default and secret-ness.
 * scripts/test-bundle-connector-config.mjs fails when they drift.
 *
 * Descriptions are written for the operator filling in the form; the yaml
 * descriptions are written for the connector's author and are not copied.
 *
 * Erasable-syntax TypeScript only, so the test can import this file directly
 * with Node's type stripping.
 */

export interface BundleConfigField {
  display: string;
  name: string;
  type: string;
  required: boolean;
  defaultValue?: string;
  options?: string[];
  /** Words shown for each option value (a radio or select shows the value itself when absent). */
  optionLabels?: Record<string, string>;
  description?: string;
  /** Show this field only while the value of `field` is one of `in` (lib/connector-form.ts). */
  showWhen?: { field: string; in: string[] };
  /** When hidden, Edit sends this field empty because it would keep a hidden mode's routing alive. */
  clearWhenHidden?: boolean;
}

// http-sender shows the fields of the destination kind the operator picked
// (its `destinationMode`); see lib/connector-form.ts.
const HTTP_SENDER_HTTP = { field: "destinationMode", in: ["http", "both"] };
const HTTP_SENDER_CRIBL = { field: "destinationMode", in: ["cribl", "both"] };

export const BUNDLE_CONFIG: Record<string, BundleConfigField[]> = {
  xlog: [
    // The default is https: xlog serves HTTPS on port 8000 unconditionally, so an
    // http URL fails at probe time with "Empty reply from server".
    {
      display: "xlog URL",
      name: "baseUrl",
      type: "url",
      required: true,
      defaultValue: "https://xlog:8000",
      description: "Where the xlog service is reachable from Phantom. Leave the default unless xlog sits behind your own reverse proxy.",
    },
    {
      display: "API Token",
      name: "apiToken",
      type: "secret",
      required: true,
      description: "The xlog API token (XLOG_API_KEY in /opt/phantom/.env on the host).",
    },
  ],

  caldera: [
    { display: "Caldera URL", name: "baseUrl", type: "url", required: true, defaultValue: "http://caldera:8888", description: "Where the Caldera server is reachable from Phantom." },
    { display: "API Key", name: "apiKey", type: "secret", required: true, description: "The Caldera REST API key (CALDERA_API_KEY in /opt/phantom/.env on the host)." },
  ],

  xsiam: [
    { display: "API URL", name: "api_url", type: "url", required: true, description: "The Copy API URL value from your tenant's API Keys page, without a path." },
    { display: "API key", name: "api_key", type: "secret", required: true, description: "A Standard API key, pasted raw (no Bearer prefix). An Advanced key does not work." },
    { display: "API ID", name: "api_id", type: "string", required: true, description: "The ID shown next to the key in the API Keys table." },
    { display: "Playground ID", name: "playgroundId", type: "string", required: false, description: "Optional. The issue (war room) id used as the context for remote script calls." },
    { display: "Webhook endpoint", name: "webhookEndpoint", type: "url", required: false, description: "Optional. Your XSIAM webhook URL for raw log ingestion." },
    { display: "Webhook key", name: "webhookKey", type: "secret", required: false, description: "Optional. The Authorization value for the webhook endpoint, pasted raw (no Bearer prefix)." },
  ],

  web: [
    {
      display: "CDP URL",
      name: "cdp_url",
      type: "text",
      required: true,
      defaultValue: "http://phantom-browser:9222",
      description: "The Chromium DevTools address. Start the sidecar first: docker compose --profile browser up -d phantom-browser.",
    },
    { display: "Default timeout (ms)", name: "default_timeout_ms", type: "number", required: false, defaultValue: "30000", description: "How long a browser action may take before it gives up." },
    { display: "User-Agent override", name: "user_agent", type: "text", required: false, description: "Optional. A fixed User-Agent string, for sites that refuse the default browser one." },
    {
      display: "Allowed Domains",
      name: "allowed_domains",
      type: "array",
      required: false,
      defaultValue: "[]",
      description: "Hosts the browser may open. Start an entry with a dot (.vendor.example) to allow its subdomains. Empty means no restriction.",
    },
    {
      display: "Block resource types",
      name: "block_resource_types",
      type: "array",
      required: false,
      defaultValue: "[]",
      description: "Optional. Resource types not to load (image, media, font, stylesheet, script, websocket) for faster text-only pages.",
    },
    {
      display: "Default extractor mode",
      name: "extractor_mode",
      type: "select",
      required: false,
      defaultValue: "readable",
      options: ["readable", "body", "markdown"],
      description: "How page text is extracted: readable (main content), body (the whole page) or markdown.",
    },
  ],

  "cortex-docs": [],

  "cortex-content": [],

  "cortex-xdr": [
    { display: "API URL", name: "api_url", type: "url", required: true, description: "The Copy API URL value from your tenant's API Keys page, without a path." },
    { display: "API key", name: "api_key", type: "secret", required: true, description: "A Standard API key, pasted raw (no Bearer prefix). An Advanced key does not work." },
    { display: "API ID", name: "api_id", type: "string", required: true, description: "The ID shown next to the key in the API Keys table." },
    { display: "Poll interval (seconds)", name: "pollIntervalSeconds", type: "number", required: false, defaultValue: "3", description: "How often a running XQL query is checked for results." },
    { display: "Maximum poll attempts", name: "maxPollAttempts", type: "number", required: false, defaultValue: "40", description: "How many checks to make before returning an execution id to collect the results later." },
  ],

  "http-sender": [
    {
      display: "Destination",
      name: "destinationMode",
      type: "radio",
      required: false,
      defaultValue: "http",
      options: ["http", "cribl", "both"],
      optionLabels: { http: "XSIAM HTTP collector", cribl: "Cribl integration", both: "Both" },
      description:
        "Which kind of destination this instance sends to. The XSIAM HTTP collector takes a collector URL, a vendor, a product and a key. The Cribl integration takes the Cribl endpoint and its token and gives every Cribl source its own destination.",
    },
    { display: "Collector URL", name: "collectorUrl", type: "url", required: true, showWhen: HTTP_SENDER_HTTP, clearWhenHidden: true, description: "The HTTP Log Collector URL from your tenant (https://api-<tenant>/logs/v1/event)." },
    { display: "Vendor (as set on the collector)", name: "vendor", type: "string", required: true, showWhen: HTTP_SENDER_HTTP, clearWhenHidden: true, description: "The vendor configured on the collector. The collector decides the dataset." },
    { display: "Product (as set on the collector)", name: "product", type: "string", required: true, showWhen: HTTP_SENDER_HTTP, clearWhenHidden: true, description: "The product configured on the collector." },
    { display: "Collector API key", name: "collectorKey", type: "secret", required: true, showWhen: HTTP_SENDER_HTTP, description: "The collector's key, shown once when the collector is created." },
    { display: "Additional destinations (JSON array)", name: "additionalDestinations", type: "string", required: false, showWhen: HTTP_SENDER_HTTP, clearWhenHidden: true, description: "Optional. More collectors as a JSON array of objects with url, vendor and product." },
    { display: "Additional destination keys (JSON object)", name: "additionalKeys", type: "secret", required: false, showWhen: HTTP_SENDER_HTTP, description: "Optional. The keys of the additional destinations, as a JSON object keyed by destination name." },
    { display: "Cribl endpoint URL", name: "criblUrl", type: "url", required: true, showWhen: HTTP_SENDER_CRIBL, clearWhenHidden: true, description: "The Cribl endpoint from your tenant (https://api-<tenant>/logs/v1/integrated/cribl/data)." },
    { display: "Cribl token", name: "criblToken", type: "secret", required: true, showWhen: HTTP_SENDER_CRIBL, description: "The Cribl collector's token, shown once when the collector is created." },
    { display: "Cribl integration name", name: "criblIntegration", type: "string", required: false, defaultValue: "phantom-http-sender", showWhen: HTTP_SENDER_CRIBL, description: "The name that appears as the collector name on the rows." },
    { display: "User domain for generated identities", name: "userDomain", type: "string", required: false, defaultValue: "phantom-lab.example", description: "The domain used for the synthetic users' logins." },
    { display: "DNS suffix for Windows computer names", name: "windowsDnsSuffix", type: "string", required: false, defaultValue: "phantom.lab", showWhen: HTTP_SENDER_CRIBL, description: "Added to short computer names in Windows events sent through Cribl." },
    { display: "Verify the collector's TLS certificate", name: "verifyTls", type: "boolean", required: false, defaultValue: "true", description: "Turn off only behind a TLS-inspecting proxy." },
    { display: "Request timeout (seconds)", name: "timeoutSeconds", type: "number", required: false, defaultValue: "15", description: "How long one request may take." },
  ],

  "wec-sender": [
    { display: "Subscription Manager URL", name: "subscriptionManagerUrl", type: "string", required: true, description: "The Subscription Manager value from the Cortex console's Windows Event Collector configuration, pasted as issued." },
    { display: "Client certificate bundle (PFX, base64)", name: "clientPfx", type: "secret", required: true, description: "The client certificate bundle from the Cortex console, as base64 text." },
    { display: "Client certificate password", name: "clientPfxPassword", type: "secret", required: true, description: "The password of the client certificate bundle." },
    { display: "Sender computer name", name: "senderComputerName", type: "string", required: false, defaultValue: "phantom-wec-sender.phantom.lab", description: "The computer name this sender announces to the collector." },
    { display: "Domain NetBIOS name", name: "domainNetbios", type: "string", required: false, defaultValue: "PHANTOM", description: "The NetBIOS name of the synthetic domain used in generated events." },
    { display: "Domain DNS suffix", name: "domainDns", type: "string", required: false, defaultValue: "phantom.lab", description: "The DNS suffix of the synthetic domain." },
    { display: "Hosts in the synthetic domain", name: "hostCount", type: "number", required: false, defaultValue: "32", description: "How many hosts the synthetic domain has (8 to 100)." },
    { display: "Request timeout (seconds)", name: "timeoutSeconds", type: "number", required: false, defaultValue: "30", description: "How long one request may take." },
  ],
};
