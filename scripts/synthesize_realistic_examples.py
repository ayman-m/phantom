#!/usr/bin/env python3
"""synthesize_realistic_examples.py — replace generic 'example_value' with
name-pattern-derived synthetic examples that look like real vendor data.

After T1+T2+T3+T4 polish there were ~7,575 fields with `example: example_value`
because my mass-polish script's synthesis dict mapped `type:string` (the
fallback type) to the generic placeholder. Operators looking at the drawer
see "example_value" instead of a vendor-realistic sample.

This pass:
  1. Reads each pack's metadata (vendor, product) for context.
  2. For every field with `example_value`, infers a realistic example from
     a name-pattern library + the pack's vendor/product when relevant.
  3. Special-cases meta fields (`_raw_log`, `_vendor`, `_product`, `_id`):
     these have *known* shapes — `_vendor` is literally the pack vendor.
  4. Validates each pack against the schema after rewrite.

Per scripts/CLAUDE.md: one-shot maintainer migration; runtime never invokes;
output is the committed YAMLs.
"""
from __future__ import annotations
import json, re, sys, uuid
from pathlib import Path
import yaml
from jsonschema import Draft7Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT / 'bundles/spark/data-sources'
SCHEMA = json.loads((BASE / 'data_source.schema.json').read_text())
V = Draft7Validator(SCHEMA)

# Stable UUIDs for reproducibility — same field gets the same example across runs
_NAMESPACE = uuid.UUID('5d41402a-bc4b-2a76-b971-9d911017c592')

def stable_id(field_name: str, pack: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f'{pack}::{field_name}'))


def name_example(name: str, ftype: str, vendor: str, product: str) -> str | None:
    """Best-effort example synthesis from name + type + pack context.

    Many specific patterns short-circuit first; the plain-string fallback
    is a name-derived sample without a vendor prefix (a vendor-prefixed
    token like `Amazon Web Services-httprequest` would be ugly).
    """
    n = name.lower()
    last = n.rsplit('.', 1)[-1].rsplit('_', 1)[-1].lower()

    # ─── META FIELDS (cortex-injected, known values) ──────────────────
    if name == '_raw_log':
        # Synthesize a vendor-realistic raw log line. We default to a
        # CEF-ish shape since most XSIAM connectors emit CEF or
        # syslog-with-key-value.
        return (f'<14>{ "2024-01-15T14:23:01+0000" } {vendor.lower().replace(" ", "")}'
                f': {product.lower()}={product} action=allow user=jdoe')
    if name == '_vendor':
        return vendor or 'Vendor'
    if name == '_product':
        return product or 'Product'
    if name == '_id':
        return stable_id(name, f'{vendor}-{product}')[:36]
    if name in ('_log_source_file_name', '_log_source_file'):
        return f'/var/log/{product.lower().replace(" ", "_") or "vendor"}.log'
    if name == '_log_type':
        return 'audit'
    if name == '_collector_type':
        return 'syslog'
    if name == '_ENTRY_STATUS':
        return 'OK'
    # Cortex meta passthroughs
    if name.startswith('_raw_log.'):
        suffix = name.split('.', 1)[1]
        if 'action' in suffix.lower(): return 'allow'
        if 'protocol' in suffix.lower(): return 'tcp'
        return 'raw_value'

    # ─── COMMON SEMANTIC PATTERNS ─────────────────────────────────────
    # Names / identifiers
    if last in ('uuid', 'guid') or n.endswith('_uuid') or n.endswith('_guid'):
        return stable_id(name, vendor)[:36]
    if last in ('eventid', 'event_id', 'alertid', 'alert_id', 'incidentid',
                'incident_id', 'logid', 'log_id'):
        return f'evt-{stable_id(name, vendor)[:8]}'
    if last == 'sessionid' or n.endswith('session_id') or n.endswith('sessionid'):
        return f'sess-{stable_id(name, vendor)[:12]}'
    if last == 'requestid' or n.endswith('request_id') or 'requestid' in last:
        return f'req-{stable_id(name, vendor)[:12]}'
    if last in ('correlationid', 'traceid', 'spanid'):
        return stable_id(name, vendor)[:32]
    if last in ('userid', 'user_id') or n.endswith('user_id') or n.endswith('userid'):
        return f'usr-{stable_id(name, vendor)[:8]}'
    if last in ('resourceid', 'resource_id') or n.endswith('resourceid') or n.endswith('resource_id'):
        return f'res-{stable_id(name, vendor)[:8]}'
    if last in ('messageid', 'message_id') or 'messageid' in last:
        return f'msg-{stable_id(name, vendor)[:12]}'
    if last in ('externalid', 'external_id', 'identifier'):
        return f'ext-{stable_id(name, vendor)[:12]}'
    if last in ('parentid', 'parent_id'):
        return f'par-{stable_id(name, vendor)[:8]}'
    if last in ('clientid', 'client_id'):
        return f'cli-{stable_id(name, vendor)[:8]}'
    if last in ('deviceid', 'device_id', 'agentid', 'agent_id', 'hostid', 'host_id', 'machineid'):
        return f'dev-{stable_id(name, vendor)[:8]}'
    if last in ('processid', 'process_id', 'pid'):
        return '4242'
    if last in ('threadid', 'thread_id', 'tid'):
        return '1024'
    if last in ('threatid', 'threat_id'):
        return f'thr-{stable_id(name, vendor)[:8]}'
    if last in ('policyid', 'policy_id', 'ruleid', 'rule_id', 'signatureid', 'signature_id'):
        return f'pol-{stable_id(name, vendor)[:8]}'
    if last in ('webaclid', 'aclid', 'acl_id'):
        return f'acl-{stable_id(name, vendor)[:8]}'
    if last == 'id' or n.endswith('._id') or n.endswith('_id'):
        return f'obj-{stable_id(name, vendor)[:8]}'

    # AWS-ish ARN-shaped identifiers — these are common in cloud packs
    if last == 'arn' or 'arn' in n.split('.')[-1] or n.endswith('.arn'):
        return 'arn:aws:iam::123456789012:user/jdoe'
    if last in ('principalid', 'principal_id', 'invokedby', 'invoked_by'):
        return 'AIDAJDPLRKLG7UEXAMPLE'
    if last in ('accesskeyid', 'access_key_id'):
        return 'AKIAIOSFODNN7EXAMPLE'

    # User / actor / account names
    if n in ('username', 'user_name', 'actor_name', 'account_name') or last == 'username':
        return 'jdoe'
    if last == 'displayname' or 'display_name' in n or 'displayname' in n:
        return 'John Doe'
    if 'firstname' in n or 'first_name' in n: return 'John'
    if 'lastname' in n or 'last_name' in n: return 'Doe'
    if last == 'fullname': return 'John Doe'
    if last in ('user', 'actor', 'principal', 'subject', 'caller'):
        return 'jdoe'
    if last in ('usertype', 'user_type'): return 'IAMUser'
    if last in ('actortype',): return 'user'
    if last in ('upn',): return 'jdoe@example.com'

    # Hosts / addresses
    if n.endswith('.ip') or n == 'ip' or last == 'ip' or 'ipaddress' in n or 'ip_address' in n:
        return '192.0.2.45'
    if last in ('src', 'source'): return '192.0.2.45'
    if last in ('dst', 'dest', 'destination'): return '198.51.100.7'
    if last in ('srcip', 'sourceip', 'src_ip', 'source_ip'): return '192.0.2.45'
    if last in ('dstip', 'destip', 'destinationip', 'dst_ip', 'dest_ip'): return '198.51.100.7'
    if 'hostname' in n or n.endswith('.host') or n == 'host':
        return 'host01.example.com'
    if last == 'fqdn' or 'fqdn' in n: return 'host01.example.com'
    if last in ('mac', 'macaddress', 'mac_address'): return '00:1B:44:11:3A:B7'
    if last == 'address' or 'address' in n:
        # Could be IP, MAC, or street — be generic
        return '192.0.2.45'

    # Network
    if last == 'port' or 'port' in n: return '443'
    if last in ('proto', 'protocol'): return 'tcp'
    if last == 'method' or 'http_method' in n: return 'GET'
    if last in ('interface', 'iface'): return 'eth0'
    if last in ('vlan',): return '100'
    if last in ('netmask', 'subnet'): return '255.255.255.0'
    if last in ('cidr',): return '10.0.0.0/24'
    if last in ('bytes', 'bytesin', 'bytes_in', 'bytesout', 'bytes_out',
                'bytessent', 'bytesreceived'):
        return '4096'
    if last in ('packets', 'packetsin', 'packetsout'): return '12'
    if last in ('connections', 'sessions'): return '3'

    # Type / category / classification
    if last in ('type', 'classifier'): return 'authentication'
    if last in ('category', 'class', 'subcategory', 'cat'): return 'access_control'
    if last == 'subtype': return 'login'
    if last in ('kind',): return 'event'
    if last in ('family', 'group_type'): return 'audit'

    # Severity / status / level
    if last in ('severity', 'priority', 'criticality'): return 'INFO'
    if last == 'level': return 'info'
    if last == 'status' or 'status_code' in n: return 'success'
    if last == 'code': return '200'
    if last in ('result', 'outcome'): return 'success'
    if last in ('state',) and 'usa' not in n: return 'active'
    if last in ('verdict', 'decision'): return 'allow'
    if last in ('disposition',): return 'clean'

    # Action / event
    if last == 'action' or 'action_taken' in n: return 'allow'
    if last == 'event' or 'event_name' in n or last == 'eventname': return 'login'
    if last in ('operation', 'op'): return 'create'
    if last in ('verb',): return 'GET'
    if last in ('eventtype', 'event_type'): return 'authentication'
    if last in ('eventcategory', 'event_category'): return 'audit'
    if last in ('eventsource', 'event_source'): return 'cloudtrail.amazonaws.com'

    # Descriptions / messages
    if last in ('description', 'desc', 'summary'):
        return f'Event recorded by {vendor or "the vendor"}.'
    if last == 'message' or 'msg' in n.split('_')[-1:]:
        return 'Operation completed successfully.'
    if last == 'comment': return 'Auto-generated comment by the system.'
    if last in ('reason', 'cause'): return 'normal_operation'
    if last in ('title', 'subject'): return 'Sample subject line'
    if last in ('label', 'tag'): return 'auto-tagged'
    if last in ('notes', 'note'): return 'Reviewed by SOC analyst.'
    if last in ('info', 'details', 'detail'): return 'see message'

    # Files / paths
    if 'filename' in n or last == 'filename':
        return 'document.pdf'
    if 'filepath' in n or last == 'filepath' or last == 'path':
        return '/var/log/app.log'
    if 'extension' in n or last in ('ext', 'extension'):
        return 'pdf'
    if last in ('hash', 'md5', 'sha1', 'sha256', 'filehash', 'file_hash'):
        return 'd41d8cd98f00b204e9800998ecf8427e'
    if last in ('signature', 'fingerprint'): return 'sha256:e3b0c44298fc1c149...'

    # Process / command
    if last in ('process', 'processname', 'process_name'): return 'explorer.exe'
    if last in ('command', 'cmd', 'commandline', 'command_line', 'cmdline'):
        return '/usr/bin/curl https://example.com/'
    if last in ('arguments', 'args'): return '--config /etc/app.conf'
    if last in ('parent', 'parent_process', 'parentname'): return 'systemd'
    if last in ('image', 'imagepath'): return '/usr/bin/explorer.exe'
    if last in ('service', 'servicename', 'service_name'): return 'sshd'

    # Versions / dates / numeric
    if last == 'version': return '1.0.0'
    if last in ('date', 'day'): return '2024-01-15'
    if last in ('time', 'tm'): return '14:23:01'
    if last in ('timestamp', 'time_stamp'): return '1748263381000'
    if last in ('year',): return '2024'
    if last in ('month',): return '01'
    if last in ('count', 'num', 'total'): return '42'
    if last in ('size',): return '1024'
    if last in ('duration',): return '1000'
    if last in ('age',): return '30'
    if last in ('score', 'risk_score', 'riskscore', 'confidence'): return '85'
    if last in ('number',): return '7'

    # Cloud / infra
    if last == 'region': return 'us-east-1'
    if last in ('zone', 'availabilityzone', 'availability_zone'): return 'us-east-1a'
    if last in ('availability',): return 'available'
    if last in ('cloud', 'provider'): return 'aws'
    if last in ('platform',): return 'linux'
    if last in ('os', 'osname', 'os_name'): return 'Linux'
    if last in ('osversion', 'os_version'): return '5.15.0-101-generic'
    if last in ('namespace', 'tenant', 'tenantid', 'tenant_id'):
        return f'tenant-{stable_id(name, vendor)[:8]}'
    if last in ('org', 'organization', 'orgid', 'org_id'):
        return f'org-{stable_id(name, vendor)[:8]}'
    if last in ('project', 'projectid', 'project_id'):
        return f'proj-{stable_id(name, vendor)[:8]}'
    if last in ('account', 'accountid', 'account_id', 'accountids'):
        return '123456789012'
    if last in ('subscription', 'subscriptionid', 'subscription_id'):
        return '00000000-0000-0000-0000-000000000000'
    if last in ('group', 'groupid', 'group_id'):
        return f'grp-{stable_id(name, vendor)[:8]}'
    if last in ('groupname', 'group_name'): return 'admins'
    if last in ('role', 'rolename', 'role_name'): return 'Admin'
    if last in ('permission', 'permissions'): return 'read'
    if last in ('container', 'containerid', 'container_id'): return 'container-abc123'
    if last in ('cluster', 'clustername', 'cluster_name'): return 'prod-us-east-1'
    if last in ('pod', 'podname'): return 'web-pod-001'
    if last in ('image_id', 'imageid'): return 'ami-0abcdef1234567890'

    # Email / web / domain
    if 'email' in n or last == 'email': return 'user@example.com'
    if last in ('domain',): return 'example.com'
    if last == 'url' or 'url' in n: return 'https://example.com/path?q=1'
    if last in ('uri',): return '/api/v1/path?q=1'
    if last in ('referer', 'referrer'): return 'https://example.com/'
    if last == 'useragent' or 'user_agent' in n or last == 'user-agent':
        return 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    if last in ('query', 'querystring', 'query_string'): return 'q=search&page=1'
    if last in ('cookie', 'cookies'): return 'session=abc123; tracking=xyz'
    if last in ('headers', 'header'): return 'Content-Type: application/json'

    # Country / location
    if last == 'country' or last == 'countryname' or 'country' in last:
        return 'US'
    if last == 'city': return 'San Francisco'
    if last == 'state' or last == 'province': return 'CA'
    if last in ('location',): return 'us-east'
    if last in ('latitude', 'lat'): return '37.7749'
    if last in ('longitude', 'lng', 'lon'): return '-122.4194'
    if last in ('postalcode', 'zip', 'zipcode'): return '94103'

    # CEF custom strings (cs1..cs6, cs1label..cs6label)
    if re.fullmatch(r'cs[1-6]', last):
        return 'custom_value'
    if re.fullmatch(r'cs[1-6]label', last):
        return 'CustomField'
    if re.fullmatch(r'cn[1-3]', last):
        return '42'
    if re.fullmatch(r'cn[1-3]label', last):
        return 'CustomNumber'

    # Threat / malware
    if last in ('threatname', 'threat_name', 'malware', 'malwarename', 'malware_name'):
        return 'Generic.Malware.A'
    if last in ('virus', 'virusname'): return 'EICAR-Test-File'
    if last in ('attack', 'attackname', 'attack_name'): return 'SQL Injection'
    if last in ('iocs', 'ioc'): return 'malicious.example.com'

    # Policy / rule
    if last in ('policy', 'policyname', 'policy_name'): return 'Default-Policy'
    if last in ('rule', 'rulename', 'rule_name'): return 'Allow-Internal'
    if last in ('ruleset', 'rule_set'): return 'baseline-v1'

    # Agent / sensor
    if last in ('agent', 'agentname', 'sensor', 'sensorname'): return 'phantom-agent-01'
    if last in ('agentversion', 'agent_version'): return '7.0.1'

    # Application
    if last in ('app', 'application', 'applicationname', 'app_name'):
        return 'Salesforce'
    if last in ('appname',): return 'Salesforce'
    if last in ('component', 'componentname'): return 'auth-service'
    if last in ('module', 'modulename'): return 'audit'

    # Name (generic) — last so vendor/host/user/file/process patterns above win
    if last == 'name':
        return 'sample_name'
    if last in ('value', 'val'): return 'sample_value'
    if last in ('key', 'keyname'): return 'sample_key'
    if last in ('field', 'fieldname'): return 'sample_field'
    if last in ('target', 'targetname'): return 'target_object'

    # ─── TYPE-DRIVEN FALLBACK ─────────────────────────────────────────
    if ftype == 'json':
        return '{}'
    if ftype == 'string_long':
        return f'Detailed event payload emitted by {vendor or "the vendor"} for this record.'
    if ftype == 'string_short':
        # Short token
        return 'token_value'
    if ftype == 'integer':
        return '42'
    if ftype == 'boolean':
        return 'true'

    # Plain string fallback — name-derived sample WITHOUT vendor prefix.
    # A vendor-prefixed token like `Amazon Web Services-httprequest`
    # would be ugly, so the vendor is not used.
    return f'sample_{last[:16]}'


def _is_stale_example(ex: str, vendor: str) -> bool:
    """Detect the stale fallback shape `<Vendor>-<lowercase-suffix>`.

    That fallback produced strings like 'Amazon Web Services-httprequest'.
    We treat any example that starts with the pack's vendor name + '-'
    followed by a short lowercase token as stale and re-synthesize it.
    """
    if not isinstance(ex, str) or not vendor:
        return False
    prefix = f'{vendor}-'
    if not ex.startswith(prefix):
        return False
    tail = ex[len(prefix):]
    # Tail is the truncated lowercase form of the field name. May
    # contain spaces if the source field had spaces (e.g. Cortex
    # 'ExtendedProperties.AAD User Id' → 'aad user id'). The original
    # truncation was 12 chars; we permit up to 24 to catch a few edge
    # cases where the truncation point fell on a longer suffix.
    if len(tail) > 24:
        return False
    return bool(re.fullmatch(r'[a-z][a-z0-9 _,.-]*', tail))


def polish_pack(yaml_path: Path) -> int:
    """Polish one pack. Returns count of fields updated."""
    try: data = yaml.safe_load(yaml_path.read_text())
    except Exception: return 0
    if not isinstance(data, dict): return 0
    vendor = (data.get('vendor') or '').strip()
    product = (data.get('product') or '').strip()
    fields = data.get('fields') or []
    updated = 0
    for f in fields:
        if not isinstance(f, dict): continue
        cur = f.get('example')
        needs = (cur == 'example_value') or _is_stale_example(cur, vendor)
        if not needs:
            continue
        new = name_example(f.get('name', ''), f.get('type', 'string'), vendor, product)
        if new is None: continue
        f['example'] = new
        updated += 1
    if updated:
        errs = list(V.iter_errors(data))
        if errs:
            return -1
        yaml_path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True))
    return updated


def main():
    total = 0
    packs = 0
    failed = []
    for d in sorted(BASE.iterdir()):
        if not d.is_dir(): continue
        y = d / 'data_source.yaml'
        if not y.exists(): continue
        n = polish_pack(y)
        if n == -1:
            failed.append(d.name)
        elif n > 0:
            total += n
            packs += 1
    print(f'Synthesized {total} examples across {packs} packs')
    if failed:
        print(f'Schema failures: {len(failed)}')
        for f in failed[:5]: print(f'  {f}')


if __name__ == '__main__':
    main()
