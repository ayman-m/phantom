---
id: XQL-550-fe99caaa
title: Outbound RDP Connections Over Non-Standard Tools
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - Executable
---

# Outbound RDP Connections Over Non-Standard Tools

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (action_remote_port IN (3389)) and not (((actor_process_image_path IN ("C:\Windows\System32\mstsc.exe", "C:\Windows\SysWOW64\mstsc.exe")))) and not (((actor_process_image_path IN ("C:\Windows\System32\dns.exe")) AND (action_local_port IN (53)) AND (action_network_dpi_fields IN ("udp"))) OR ((actor_process_image_path ~= ".*\\Avast Software\\Avast\\AvastSvc.exe" OR  actor_process_image_path ~= ".*\\Avast\\AvastSvc.exe")) OR ((actor_process_image_path ~= ".*\\RDCMan.exe")) OR ((actor_process_image_path IN ("C:\Program Files\Google\Chrome\Application\chrome.exe"))) OR ((actor_process_image_path ~= ".*\\FSAssessment.exe" OR  actor_process_image_path ~= ".*\\FSDiscovery.exe" OR  actor_process_image_path ~= ".*\\MobaRTE.exe" OR  actor_process_image_path ~= ".*\\mRemote.exe" OR  actor_process_image_path ~= ".*\\mRemoteNG.exe" OR  actor_process_image_path ~= ".*\\Passwordstate.exe" OR  actor_process_image_path ~= ".*\\RemoteDesktopManager.exe" OR  actor_process_image_path ~= ".*\\RemoteDesktopManager64.exe" OR  actor_process_image_path ~= ".*\\RemoteDesktopManagerFree.exe" OR  actor_process_image_path ~= ".*\\RSSensor.exe" OR  actor_process_image_path ~= ".*\\RTS2App.exe" OR  actor_process_image_path ~= ".*\\RTSApp.exe" OR  actor_process_image_path ~= ".*\\spiceworks-finder.exe" OR  actor_process_image_path ~= ".*\\Terminals.exe" OR  actor_process_image_path ~= ".*\\ws_TunnelService.exe")) OR ((actor_process_image_path ~= ".*\\thor.exe" OR  actor_process_image_path ~= ".*\\thor64.exe")) OR ((actor_process_image_path ~= "C:\\Program Files\\SplunkUniversalForwarder\\bin\\.*")) OR ((actor_process_image_path ~= ".*\\Ranger\\SentinelRanger.exe")) OR ((actor_process_image_path IN ("C:\Program Files\Mozilla Firefox\firefox.exe"))) OR ((actor_process_image_path IN ("C:\Program Files\TSplus\Java\bin\HTML5service.exe", "C:\Program Files (x86)\TSplus\Java\bin\HTML5service.exe"))) OR ((actor_process_image_path IN (null))) OR ((actor_process_image_path IN (null))) OR ((actor_process_image_path IN ("<unknown process>"))))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects Non-Standard tools initiating a connection over port 3389 indicating possible lateral movement.

## Variations

_(No variations are documented for this entry.)_
