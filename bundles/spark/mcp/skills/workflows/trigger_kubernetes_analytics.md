---
name: trigger_kubernetes_analytics
displayName: Trigger Cortex Kubernetes / cloud analytics alerts from AKS audit logs
category: workflows
description: 'Fire Cortex XSIAM''s Kubernetes analytics detectors (anonymous secrets access, TOR-based API call, privileged pod creation, cluster-role-binding manipulation) from synthetic Azure AKS audit logs, via the proven msft/azure_aks CEF route — category=kube-audit, the audit event as ONE stringified JSON blob in properties.log, and a TOP-LEVEL SourceIps field. Use when the operator asks to trigger, demo or reproduce Kubernetes / container / AKS analytics alerts. Gives the exact worker shape, four attack recipes, the landing check, and the 14-day detector-activation expectation.'
icon: deploy
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger Kubernetes analytics alerts from AKS audit logs

## When this skill applies

The operator wants **Kubernetes / container analytics detectors** to fire, for example:
*"trigger a Kubernetes alert"*, *"demo privileged-pod detection"*, *"simulate someone reading
secrets anonymously"*, *"fire the cluster-role-binding rule"*.

The route is Azure AKS audit logs (`msft_azure_aks_raw`). The full field-level guidance is the
`AzureKubernetesServices` data source's `how_to_use` — this skill is the attack-recipe layer on
top of it.

## The proven event shape (do not deviate)

Every recipe below is the same worker with a different `properties.log` blob:

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  msft
  product: azure_aks
  count:   <events>          # see recipe
  duration_seconds: 120
  max_events: <events>
  destination: logdest:<id from log_destinations_list>
  schema_override:
    - {name: category,       type: string}
    - {name: properties.pod, type: string}
    - {name: properties.log, type: string}
    - {name: SourceIps,      type: ipv4}
  observables_dict:
    category:       ["kube-audit"]
    properties.pod: ["aks-prod-node-3"]
    SourceIps:      ["<client IP — see recipe>"]
    properties.log: ["<ONE stringified JSON audit blob — see recipe>"]
```

Three facts:

1. **`properties.log` is a JSON STRING, not a nested object.** The modeling rule opens with
   `get_properties_log = properties -> log` and `->` returns scalars — a nested object makes every
   downstream read null (9 xdm fields instead of 32).
2. **`xdm.source.ipv4` comes from the `sourceIPs` array INSIDE the blob.** A top-level
   `SourceIps` CEF field lands raw but the audit-branch modeling rule does not map it
   (top-level only leaves `xdm.source.ipv4` null; in-blob `sourceIPs` populates it). Send both — in-blob for XDM, top-level for raw-side filtering — and keep
   them consistent, since several detectors key on the source IP.
3. **`category` must be `kube-audit`** for audit events. The parsing rule's INGEST block is
   `no_hit = drop`, so a wrong category vanishes without a trace.

## The audit blob template

```json
{"kind":"Event","apiVersion":"audit.k8s.io/v1","level":"RequestResponse",
 "auditID":"<uuid>","stage":"ResponseComplete",
 "requestURI":"/api/v1/namespaces/kube-system/secrets",
 "verb":"get",
 "user":{"username":"system:anonymous","groups":["system:unauthenticated"]},
 "sourceIPs":["203.0.113.77"],
 "userAgent":"kubectl/v1.29.2",
 "objectRef":{"resource":"secrets","namespace":"kube-system","name":"cluster-admin-token","apiVersion":"v1"},
 "responseStatus":{"code":200,"status":"Success"},
 "requestReceivedTimestamp":"2026-09-28T07:55:00.123456Z"}
```

Keep `requestReceivedTimestamp` current (the parsing rule derives `_time` from it). Vary `auditID`
per event if the generator doesn't already.

## Attack recipes

| # | Detector targeted | Blob changes | SourceIps | Count |
|---|---|---|---|---|
| 1 | **Anonymous access to secrets** | `user.username: "system:anonymous"`, `groups: ["system:unauthenticated"]`, `verb: "get"`/`"list"`, `objectRef.resource: "secrets"`, several namespaces | one external IP | 10-20 |
| 2 | **TOR-based Kubernetes API call** | ordinary `system:serviceaccount:prod:deployer` user, `verb: "get"`, any resource | a **real Tor exit node** IP (e.g. 171.25.193.25) | 3-5 |
| 3 | **Privileged pod created** | `verb: "create"`, `objectRef.resource: "pods"`, include `requestObject` with `spec.containers[].securityContext.privileged: true` and host namespaces (`hostNetwork: true`, `hostPID: true`) | internal IP | 3-5 |
| 4 | **Cluster-role-binding created/deleted** (`a-kubernetes-cluster-role-binding-was-created-or-deleted`) | `verb: "create"`, `objectRef.resource: "clusterrolebindings"`, `requestObject` binding a serviceaccount to `cluster-admin` | internal IP | 3-5 |

Recipe 4 doubles as **attack feed + anomaly**: keep a slow trickle of ordinary controller
activity (recipe "baseline" below) and the RBAC mutation stands out.

**Baseline (for day-in-the-life jobs):** controller serviceaccounts
(`system:serviceaccount:kube-system:deployment-controller`,
`...:replicaset-controller`, `...:namespace-controller`) doing `get`/`list`/`watch`/`update`
on `deployments`, `replicasets`, `pods` in application namespaces (`charging`, `provisioning`,
`billing`), `responseStatus.code` 200, SourceIps from the cluster's internal range. This is the
noise floor the anomalies are judged against — run it on a schedule (see
`baseline_normal_activity` for the jobs pattern).

## Detector timing expectation

Kubernetes detectors are **Cloud analytics** detectors with a documented **14-day Activation
period** counted from when the dataset first receives data. Expect the family to go live 14
days after `msft_azure_aks_raw` first receives data. All four recipes above land fully
XDM-modeled right away but produce no alerts inside the activation window — that is expected,
not a failure.

**Seed early, check later**: run the baseline + attack recipes on a schedule from day one so
that when activation completes, both the baseline and the anomalies already exist.

## Landing check (run this before any alert check)

```
datamodel dataset = msft_azure_aks_raw
| filter xdm.source.user.username contains "<marker from your blob>"
| fields xdm.source.user.username, xdm.source.ipv4, xdm.target.resource.name,
         xdm.network.http.method, xdm.event.outcome
| limit 10
```

Expect non-null values across all five columns. `xdm.source.ipv4 = null` means the blob's
`sourceIPs` array was missing (the top-level `SourceIps` field does not map); all-null means
`properties.log` was sent as a nested object.

## Alert check

```
dataset = alerts
| filter alert_source in ("MAGNIFIER", "ANALYTICS_BIOC")
| fields alert_name, alert_id, original_tags, _time
| sort desc _time
| limit 20
```

Use the stored enum names `MAGNIFIER` and `ANALYTICS_BIOC`: the displayed names `XDR_ANALYTICS` and `XDR_ANALYTICS_BIOC` match nothing in a filter.

`original_tags` carries `DS:msft/azure_aks` when the alert was driven by this feed.
