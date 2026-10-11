---
id: XQL-235-09488e25
title: Rundll32 running HTML application via script
category: investigation
dataset: xdr_process
tags:
  - preset
  - filter
  - fields
  - xdr_process
  - source:preset
---

# Rundll32 running HTML application via script

**Dataset**: `xdr_process`

```sql
preset = xdr_process // Using the XDR process execution preset
| filter lowercase(action_process_image_name) = "rundll32.exe" and lowercase(action_process_image_command_line) ~= ".*script.*?mshtml.dll\,runhtmlapplication.*" // Filtering for cases where rundll32 is being called to load an html application
| fields action_process_image_command_line as cmd, actor_process_image_path as parent_path, actor_process_command_line as parent_cmd, causality_actor_process_image_path as cgo, causality_actor_process_command_line as cgo_cmd // Selectnig the relevant fields
```

## When to use

Displays cases where Rundll32 is being used to run a script and access an html application or page

## Variations

_(No variations are documented for this entry.)_
