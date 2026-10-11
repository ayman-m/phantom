"""Public IP pools for the profiles: where the benign users are, and where the attackers come from.

Why real addresses: Cortex geo-resolves the ACTUAL IP (country, city, ASN, ISP) and ignores any label in the
event, so a baseline built on RFC 5737 documentation addresses gives the geo / ASN / new-country detectors nothing
to profile. Every range here was checked on a Cortex tenant with XQL's `iploc` stage on three hosts of
the /24; the country, city and ASN below are what CORTEX returned, so an event that carries them agrees with the
enrichment the analytics engine does on its own.

HOME   24 Saudi /24s, from RIPE announced prefixes of four regional ISPs (AS25019, AS35819, AS39891
       and AS43766), ordered so consecutive users land on different ISPs.
ABROAD 18 /24s outside Saudi Arabia: consumer-ISP ranges in other countries plus VPN / hosting-provider
       ranges. Attackers and impossible-travel legs draw from here, so they never collide with a home range.

All of this is synthetic telemetry sent only to the operator's own tenant; no packet is ever sent to these networks.
"""
from __future__ import annotations

import hashlib
import ipaddress
import random
from typing import Mapping, NamedTuple


class Range(NamedTuple):
    cidr: str            # a /24
    asn: int
    isp: str
    country: str
    city: str | None
    region: str | None
    lat: float
    lon: float


HOME: tuple[Range, ...] = (
    Range('144.86.80.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('37.121.160.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Al Qaţīf', 'Eastern Province', 26.5651, 50.0118),
    Range('51.235.191.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('185.5.155.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('168.149.64.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('37.141.8.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('2.90.64.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('51.39.2.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Riyadh', 'Riyadh Region', 24.6869, 46.7224),
    Range('77.31.81.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Medina', 'Medina Region', 24.4668, 39.6167),
    Range('31.166.128.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('176.47.64.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Makkah', 'Mecca Region', 21.423, 39.821),
    Range('51.36.184.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('188.55.20.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Riyadh', 'Riyadh Region', 24.6869, 46.7224),
    Range('37.242.29.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Khobar', 'Eastern Province', 26.2846, 50.208),
    Range('151.254.90.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Riyadh', 'Riyadh Region', 24.6869, 46.7224),
    Range('51.39.134.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('184.26.96.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('176.16.208.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Medina', 'Medina Region', 24.4668, 39.6167),
    Range('64.65.106.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('77.232.102.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Dammam', 'Eastern Province', 26.4336, 50.1116),
    Range('51.211.188.0/24', 25019, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('109.82.16.0/24', 35819, 'Etihad Etisalat, a joint stock company', 'Saudi Arabia', 'Riyadh', 'Riyadh Region', 24.6869, 46.7224),
    Range('95.185.87.0/24', 39891, 'Example Telecom JSC', 'Saudi Arabia', 'Jeddah', 'Mecca Region', 21.4913, 39.1841),
    Range('51.39.52.0/24', 43766, 'Mobile Telecommunication Company Saudi Arabia Joint-Stock company', 'Saudi Arabia', 'Riyadh', 'Riyadh Region', 24.6869, 46.7224),
)

ABROAD: tuple[Range, ...] = (
    Range('210.150.20.0/24', 2514, 'NTT PC Communications, Inc.', 'Japan', 'Himurochō', 'Osaka', 34.8363, 135.5839),
    Range('1.126.44.0/24', 1221, 'Telstra Limited', 'Australia', 'Perth', 'Western Australia', -31.92, 115.861),
    Range('80.130.44.0/24', 3320, 'Deutsche Telekom AG', 'Germany', 'Cologne', 'North Rhine-Westphalia', 50.9178, 6.8882),
    Range('41.134.20.0/24', 10474, 'Dimension Data', 'South Africa', None, None, -29.0, 24.0),
    Range('49.36.20.0/24', 55836, 'Reliance Jio Infocomm Limited', 'India', 'Bhopal', 'Madhya Pradesh', 23.2505, 77.4065),
    Range('187.10.20.0/24', 27699, 'TELEFONICA BRASIL S.A', 'Brazil', 'São Paulo', 'São Paulo', -23.5475, -46.6361),
    Range('171.98.20.0/24', 17552, 'True Online', 'Thailand', 'Bangkok', 'Bangkok', 13.7326, 100.4863),
    Range('45.83.220.0/24', 39351, '31173 Services AB', 'Sweden', 'Malmö', 'Skåne County', 55.6078, 12.9982),
    Range('194.165.16.0/24', 48721, 'Flyservers S.A.', 'Panama', None, None, 9.0, -80.0),
    Range('195.206.105.0/24', 9009, 'M247 Europe SRL', 'Switzerland', 'Zurich', 'Zurich', 47.394, 8.445),
    Range('37.120.210.0/24', 9009, 'M247 Europe SRL', 'Japan', 'Tokyo', 'Tokyo', 35.6164, 139.7425),
    Range('185.159.157.0/24', 209103, 'Proton AG', 'Switzerland', None, None, 47.1449, 8.1551),
    Range('217.138.128.0/24', 16247, 'Convergence Group (Wireless) Networks Limited', 'United Kingdom', 'Fulham', 'England', 51.5043, -0.2211),
    Range('156.146.60.0/24', 212238, 'Datacamp Limited', 'Austria', 'Vienna', 'Vienna', 48.2049, 16.3662),
    Range('66.181.1.0/24', 21623, 'Spacelink Systems', 'United States', 'Dulzura', 'California', 32.6442, -116.7814),
    Range('104.244.72.0/24', 53667, 'FranTech Solutions', 'Switzerland', None, None, 47.1449, 8.1551),
    Range('77.68.1.0/24', 8560, 'IONOS SE', 'United Kingdom', None, None, 51.4964, -0.1224),
    Range('64.44.40.0/24', 20278, 'Nexeon Technologies, Inc.', 'United States', 'Buffalo', 'New York', 42.8864, -78.8781),
)


class TorExit(NamedTuple):
    ip: str
    country: str
    org: str             # the hosting organisation, for `securityContext`; Cortex derives its own from the IP


# Dated SNAPSHOTS of Tor exit relays. Unlike HOME and ABROAD they are NOT iploc-verified and they go stale: relays leave
# the network and a departed exit stops being flagged, so the Tor detectors silently stop firing. Two lists:
#
# TOR_EXITS (Okta tor_signin and fastpass_phishing): 19 exits whose alert text on a Cortex tenant said "routed through a
#   known tunnel operator: TOR_PROXY"; country and organisation are what Cortex returned.
# CLOUD_TOR_EXITS (AWS and GCP tor_api_call): the 6 exits that fired the cloud Tor detectors, country is the network's
#   registered one (UNVERIFIED by iploc), organisation left generic. Evidence per exit: 185.220.101.140 raised the AWS
#   "Suspicious API call from a Tor exit node" and high-risk-IP alerts; 185.220.101.34, 185.220.101.45, 185.220.102.8,
#   and 171.25.193.20 are the GCP generator's list, from which the four GCP Tor events that raised the same
#   two alerts were drawn (which four is not recorded); 171.25.193.25 comes from the Azure sign-in probe, whose feed
#   produced no detections, so it has the weakest evidence of the six. 199.249.230.87 was dropped: an AWS tor_api_call replay that drew it
#   stayed silent for 11 minutes, while 185.220.101.140, 185.220.101.34 and 171.25.193.20 each fired.
#
# Refresh: fetch the current exit list from a host that has internet (the check.torproject.org bulk list, or
# https://torstatus.rueckgr.at/ip_list_exit.php/Tor_ip_list_EXIT.csv), replace the rows below, and update TOR_EXITS_SNAPSHOT.
# Until then, pass a current exit as `source_ip`. All of this is synthetic telemetry sent only to the operator's tenant.
TOR_EXITS_SNAPSHOT = "2026-10-04"
TOR_EXITS: tuple[TorExit, ...] = (
    TorExit('103.109.187.71', 'Vietnam', 'VR VIET NAM COMPANY LIMITED'),
    TorExit('103.166.187.253', 'Bangladesh', 'Digicon Telecommunication Ltd'),
    TorExit('109.70.100.10', 'Austria', 'Foundation for Applied Privacy'),
    TorExit('141.98.11.62', 'Lithuania', 'UAB Host Baltic'),
    TorExit('172.104.186.73', 'Singapore', 'Akamai Connected Cloud'),
    TorExit('178.175.148.155', 'Moldova', 'Trabia SRL'),
    TorExit('178.83.122.52', 'United Kingdom', 'CloudBlast LLC'),
    TorExit('182.231.115.136', 'South Korea', 'LG POWERCOMM'),
    TorExit('185.191.204.254', 'Israel', 'Rachamim Aviel Twito'),
    TorExit('185.246.190.137', 'Iceland', 'FlokiNET ehf'),
    TorExit('185.35.202.222', 'Norway', 'Blix Solutions AS'),
    TorExit('185.56.83.5', 'Seychelles', 'Datashield, Inc'),
    TorExit('190.103.179.98', 'Mexico', 'SONDATECH S.A.S'),
    TorExit('193.218.118.128', 'France', 'Epinatura LLC'),
    TorExit('200.122.181.2', 'Costa Rica', 'RADIOGRAFICA COSTARRICENSE'),
    TorExit('204.8.96.67', 'United States', 'Quintex Alliance Consulting'),
    TorExit('216.73.159.75', 'Chile', 'Zappie Host LLC'),
    TorExit('217.60.198.95', 'United Arab Emirates', '12651980 CANADA INC'),
    TorExit('94.72.104.135', 'United Kingdom', 'Contabo GmbH'),
)
CLOUD_TOR_EXITS: tuple[TorExit, ...] = (
    TorExit('185.220.101.140', 'Germany', 'Tor exit relay'),
    TorExit('185.220.101.34', 'Germany', 'Tor exit relay'),
    TorExit('185.220.101.45', 'Germany', 'Tor exit relay'),
    TorExit('185.220.102.8', 'Germany', 'Tor exit relay'),
    TorExit('171.25.193.20', 'Sweden', 'Tor exit relay'),
    TorExit('171.25.193.25', 'Sweden', 'Tor exit relay'),
)
ALL_TOR_EXITS: tuple[TorExit, ...] = TOR_EXITS + CLOUD_TOR_EXITS


def _host(cidr: str, host: int) -> str:
    return str(ipaddress.ip_network(cidr).network_address + host)


def home_for(index: int) -> tuple[str, Range]:
    """The stable home address of user number `index`: same user, same range, same host, on every run."""
    rng = HOME[index % len(HOME)]
    return _host(rng.cidr, 11 + (index * 13) % 200), rng


def abroad_pick(rng: random.Random) -> tuple[str, Range]:
    """A random address in a random out-of-country range."""
    pick = rng.choice(ABROAD)
    return _host(pick.cidr, rng.randint(2, 253)), pick


def tor_exits(rng: random.Random, n: int, pool: tuple[TorExit, ...] = TOR_EXITS) -> list[TorExit]:
    """`n` exits of `pool` in random order: all different while `n` fits the pool, then the order repeats."""
    order = list(pool)
    rng.shuffle(order)
    return [order[i % len(order)] for i in range(max(n, 0))]


def host_in(pool_range: Range, host: int) -> str:
    """Host number `host` of the range's /24."""
    return _host(pool_range.cidr, host)


def index_of(login: str, numbered: Mapping[str, int]) -> int:
    """The user number behind `login`: its number in the profile's pool, or, for an identity outside the pool,
    a number derived from the name, so any identity keeps one home address across runs and profiles."""
    if login in numbered:
        return numbered[login]
    return int(hashlib.sha1(login.encode()).hexdigest(), 16) % len(HOME)


def range_of(ip: str) -> Range | None:
    """The pool range `ip` belongs to, or None for any other (or malformed) address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    return next((r for r in HOME + ABROAD if addr in ipaddress.ip_network(r.cidr)), None)
