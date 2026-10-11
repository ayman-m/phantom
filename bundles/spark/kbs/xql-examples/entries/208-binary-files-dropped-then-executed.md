---
id: XQL-208-8442afd0
title: Binary files dropped then executed
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - join
  - dedup
  - xdr_data
  - source:dataset
---

# Binary files dropped then executed

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_WRITE // Looking for file being written to disk
 | fields agent_id, action_file_sha256 as file_hash, agent_hostname, actor_process_image_path as writer_path, actor_process_signature_vendor as writer_signer, action_file_path as written_path, _time as written_time // Getting info about the file such as where it was written to, who wrote it, etc
 | join (dataset=xdr_data | filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
 | fields actor_process_image_path as executed_by, actor_process_signature_vendor as executor_signer, agent_id, action_process_image_sha256, action_process_image_path as executed_path, action_process_signature_vendor as executed_vendor, _time as executed_time) as execution agent_id = execution.agent_id and file_hash=execution.action_process_image_sha256 and written_path=execution.executed_path and writer_path != execution.executed_by // The commands here are joining another query of the xdr dataset, where the query looks for a process start events with its relevant fields, then setting conditions to join by, such as making sure the file written to disk is the same process that was executed on the same agent, and that the process that executed the new file is not the same as the one who wrote it to disk.
 | dedup agent_hostname, writer_path, writer_signer, file_hash, written_path, executed_path, executed_vendor, executed_by, executor_signer by asc executed_time // Dedupping the events to only show the first time it happened
 | fields agent_hostname, writer_path, writer_signer, file_hash, written_path, executed_path, executed_vendor, executed_by, executor_signer // Showing all the relevant fields
```

## When to use

Display cases where a binary file is dropped to disk by one process, and then executed by another process

## Variations

_(No variations are documented for this entry.)_
