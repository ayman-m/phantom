# Phantom headless-browser sidecar.
#
# Wraps chromedp/headless-shell:latest with Phantom-specific defaults
# baked in so the docker-compose service block doesn't have to repeat
# every Chromium flag. The phantom-agent's `web` connector
# (bundles/spark/connectors/web/) connects here over CDP via Playwright
# Python's `connect_over_cdp("http://phantom-browser:9222")`.
#
# # What this layer adds on top of chromedp/headless-shell:
#   - Bind CDP on 0.0.0.0:9222 (default upstream binds 127.0.0.1, which
#     is unreachable from the agent's container in the compose network)
#   - --disable-dev-shm-usage so Chromium doesn't crash on small /dev/shm
#     (Docker's default /dev/shm is 64MB; Chromium tabs hit this on
#     JS-heavy pages and abort)
#   - --no-sandbox because the container runs as root (chromedp's
#     default is to run unprivileged, but our base image isn't multi-
#     user-aware enough to make that work without a userns rebuild)
#   - A realistic Chrome User-Agent so threat-intel portals that 403
#     on "HeadlessChrome" treat the sidecar like a normal browser
#   - HEALTHCHECK against /json/version so docker-compose can wait for
#     CDP-up rather than just "process started"
#
# # Why pin :latest at the FROM line rather than a digest
#
# chromedp publishes images per Chromium release (e.g. 131.0.6778.108)
# AND :latest. We tag :latest here so customers' `docker compose pull`
# always grabs the newest stable Chromium without our release cadence
# blocking security fixes. The trade-off — an upstream Chromium change
# could break the connector — is mitigated by:
#   1. The agent's `_ensure_browser` returns a friendly error if CDP
#      goes wrong, rather than crashing the whole MCP.
#   2. Operators can pin a specific tag in their .env via a future
#      `PHANTOM_BROWSER_BASE` build arg if they want immutability.
#
# # What about CVEs?
#
# chromedp/headless-shell rebuilds on every Chromium release. The base
# is pinned by digest so Phantom-browser's image is stable across
# source-unchanged rebuilds. Operator picks up Chromium patches by
# running the digest-update recipe below — explicit, auditable, NOT
# automatic on every Phantom release.
#
# Update Chromium base with:
#   docker pull chromedp/headless-shell:latest && \
#     docker inspect --format='{{index .RepoDigests 0}}' chromedp/headless-shell:latest
#
# Then paste the new sha256:... into the FROM below, commit, push.
# build-dev-installer.yml's REBUILT/UNCHANGED diagnostic will surface
# phantom-browser as STABLE-ADVANCED on the next release that
# includes the bumped base.
FROM chromedp/headless-shell:latest@sha256:313ed7255ae1e155fb157631a6d4c0eb8b65bbe06de9e704ed834399bdf678ff

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom headless-browser sidecar — chromedp/headless-shell with Phantom-specific defaults baked in"
LABEL org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 9222

# No HEALTHCHECK directive: chromedp/headless-shell:latest is a
# minimal image without wget, curl, sh, python, or even nc — there's
# no portable command to probe /json/version from inside the
# container. The agent's connector code does a friendlier liveness
# check anyway via Playwright's `connect_over_cdp()` on first call,
# which gives a concrete operator-actionable error if the sidecar
# is wedged. Docker's "running" status is the floor we settle for.

# CMD adds Phantom-specific Chromium flags ON TOP OF the chromedp
# entrypoint's defaults. The entrypoint (`/headless-shell/run.sh`)
# already starts Chromium with:
#   --remote-debugging-port=9223
#   --remote-debugging-address=0.0.0.0
#   --no-sandbox
#   --use-gl=angle --use-angle=swiftshader
# and uses socat to forward 9222 → 127.0.0.1:9223. So this CMD must
# NOT specify the debugging port itself — Chromium errors out with
# "Multiple targets are not supported." otherwise. Same for --no-
# sandbox (already added when running as root).
#
# Only --disable-dev-shm-usage is essential here (Chromium tab crashes
# without it on Docker's 64MB /dev/shm under JS-heavy pages).
#
# Why no --user-agent override here: Chromium's CLI parses the value
# as a quoted token, but the chromedp wrapper script that invokes
# Chromium uses `exec ... "$@"` and with a UA containing spaces +
# parens (e.g. "(X11; Linux x86_64)"), POSIX argv parsing treats
# parts of the value as separate arguments which Chromium then mis-
# reads as additional navigation targets ("Multiple targets are not
# supported"). The default chromedp UA (HeadlessChrome) is fine for
# 99% of SOC lookups; sites that 403 on HeadlessChrome can be handled
# with a `command:` override in compose using the env-var form
# (`-e CHROME_USER_AGENT=...`) once we ship a wrapper script that
# reads it.
# --remote-allow-origins=* is REQUIRED for non-localhost CDP clients.
# Pre-Chromium-111 the headless-shell DevTools server enforced
# "Host header must be localhost or an IP" which DNS-rebind-protects
# the dev server. When Playwright connects via http://phantom-browser:9222,
# its outbound `Host: phantom-browser:9222` fails that check, /json/version
# returns HTTP 500 with the message "Host header is specified and is
# not an IP address or localhost.", and connect_over_cdp() bails. The
# `--remote-allow-origins=*` flag tells Chromium to skip the host-
# header check entirely — safe here because the sidecar is on an
# internal docker network with no host-port published, and the only
# clients reaching it are inside the compose network.
CMD ["--disable-dev-shm-usage", \
     "--disable-features=VizDisplayCompositor", \
     "--remote-allow-origins=*"]
