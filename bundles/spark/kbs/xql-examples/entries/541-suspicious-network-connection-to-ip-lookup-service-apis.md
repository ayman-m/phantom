---
id: XQL-541-17970f0f
title: Suspicious Network Connection to IP Lookup Service APIs
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - IOC
  - Process
---

# Suspicious Network Connection to IP Lookup Service APIs

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (dst_agent_hostname IN ("www.ip.cn", "l2.io")) AND (dst_agent_hostname contains "api.2ip.ua" OR  dst_agent_hostname contains "api.bigdatacloud.net" OR  dst_agent_hostname contains "api.ipify.org" OR  dst_agent_hostname contains "bot.whatismyipaddress.com" OR  dst_agent_hostname contains "canireachthe.net" OR  dst_agent_hostname contains "checkip.amazonaws.com" OR  dst_agent_hostname contains "checkip.dyndns.org" OR  dst_agent_hostname contains "curlmyip.com" OR  dst_agent_hostname contains "db-ip.com" OR  dst_agent_hostname contains "edns.ip-api.com" OR  dst_agent_hostname contains "eth0.me" OR  dst_agent_hostname contains "freegeoip.app" OR  dst_agent_hostname contains "geoipy.com" OR  dst_agent_hostname contains "getip.pro" OR  dst_agent_hostname contains "icanhazip.com" OR  dst_agent_hostname contains "ident.me" OR  dst_agent_hostname contains "ifconfig.io" OR  dst_agent_hostname contains "ifconfig.me" OR  dst_agent_hostname contains "ip-api.com" OR  dst_agent_hostname contains "ip.360.cn" OR  dst_agent_hostname contains "ip.anysrc.net" OR  dst_agent_hostname contains "ip.taobao.com" OR  dst_agent_hostname contains "ip.tyk.nu" OR  dst_agent_hostname contains "ipaddressworld.com" OR  dst_agent_hostname contains "ipapi.co" OR  dst_agent_hostname contains "ipconfig.io" OR  dst_agent_hostname contains "ipecho.net" OR  dst_agent_hostname contains "ipinfo.io" OR  dst_agent_hostname contains "ipip.net" OR  dst_agent_hostname contains "ipof.in" OR  dst_agent_hostname contains "ipv4.icanhazip.com" OR  dst_agent_hostname contains "ipv4bot.whatismyipaddress.com" OR  dst_agent_hostname contains "ipv6-test.com" OR  dst_agent_hostname contains "ipwho.is" OR  dst_agent_hostname contains "jsonip.com" OR  dst_agent_hostname contains "myexternalip.com" OR  dst_agent_hostname contains "seeip.org" OR  dst_agent_hostname contains "wgetip.com" OR  dst_agent_hostname contains "whatismyip.akamai.com" OR  dst_agent_hostname contains "whois.pconline.com.cn" OR  dst_agent_hostname contains "wtfismyip.com") and not (((actor_process_image_path ~= ".*\\brave.exe")) OR ((actor_process_image_path IN ("C:\Program Files\Google\Chrome\Application\chrome.exe", "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"))) OR ((actor_process_image_path IN ("C:\Program Files\Mozilla Firefox\firefox.exe", "C:\Program Files (x86)\Mozilla Firefox\firefox.exe"))) OR ((actor_process_image_path IN ("C:\Program Files (x86)\Internet Explorer\iexplore.exe", "C:\Program Files\Internet Explorer\iexplore.exe"))) OR ((actor_process_image_path ~= ".*\\maxthon.exe")) OR ((actor_process_image_path ~= "C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\.*") AND (actor_process_image_path ~= ".*\\WindowsApps\\MicrosoftEdge.exe") AND (actor_process_image_path IN ("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe"))) OR ((actor_process_image_path ~= "C:\\Program Files (x86)\\Microsoft\\EdgeCore\\.*" OR  actor_process_image_path ~= "C:\\Program Files\\Microsoft\\EdgeCore\\.*") AND (actor_process_image_path ~= ".*\\msedge.exe" OR  actor_process_image_path ~= ".*\\msedgewebview2.exe")) OR ((actor_process_image_path ~= ".*\\opera.exe")) OR ((actor_process_image_path ~= ".*\\safari.exe")) OR ((actor_process_image_path ~= ".*\\seamonkey.exe")) OR ((actor_process_image_path ~= ".*\\vivaldi.exe")) OR ((actor_process_image_path ~= ".*\\whale.exe")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects external IP address lookups by non-browser processes.

## Variations

_(No variations are documented for this entry.)_
