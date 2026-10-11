# Cortex XDR — endpoint index

Generated from `ebarti/cortex-xdr-client` by `scripts/gen_xdr_docs_from_ebarti.py`.
This index lists 26 endpoints covering ~70% of the operator-relevant XDR API.
Audit logs, asset management, distribution lists, alert exclusions and exploits are not covered by this index.

| Category | MCP tool | HTTP endpoint | Purpose | Doc |
|---|---|---|---|---|
| alerts | `xdr_alerts_list` | `POST /public_api/v1/alerts/get_alerts_multi_events/` | Get a list of alerts with multiple events. | [→](alerts/list.md) |
| download | `xdr_download_file` | `POST /public_api/v1/download/download_file/` | Downloads the file at the given URI, previously requested by get_file_retrieval_ | [→](download/file.md) |
| endpoints | `xdr_endpoints_get` | `POST /public_api/v1/endpoints/get_endpoint/` | Gets a list of filtered endpoints. | [→](endpoints/get.md) |
| endpoints | `xdr_endpoints_isolate` | `POST /public_api/v1/endpoints/isolate/` | Isolate one or more endpoints in a single request. Request is limited to 1000 en | [→](endpoints/isolate.md) |
| endpoints | `xdr_endpoints_list_all` | `POST /public_api/v1/endpoints/get_endpoints/` | Gets a list of your endpoints. | [→](endpoints/list_all.md) |
| endpoints | `xdr_endpoints_quarantine_file` | `POST /public_api/v1/endpoints/quarantine/` | Quarantine file on selected endpoints. You can select up to 1000 endpoints. | [→](endpoints/quarantine_file.md) |
| endpoints | `xdr_endpoints_retrieve_file` | `POST /public_api/v1/endpoints/file_retrieval/` | Retrieve files from selected endpoints. You can retrieve up to 20 files, from no | [→](endpoints/retrieve_file.md) |
| endpoints | `xdr_endpoints_scan` | `POST /public_api/v1/endpoints/scan/` | Run a scan on selected endpoints. | [→](endpoints/scan.md) |
| endpoints | `xdr_endpoints_scan_all` | `POST /public_api/v1/endpoints/scan/` | Scans all endpoints. | [→](endpoints/scan_all.md) |
| endpoints | `xdr_endpoints_set_alias` | `POST /public_api/v1/endpoints/update_agent_name/` | Set or modify an Alias field for your endpoints. | [→](endpoints/set_alias.md) |
| endpoints | `xdr_endpoints_unisolate` | `POST /public_api/v1/endpoints/unisolate/` | Unisolate one or more endpoints in a single request. Request is limited to 1000  | [→](endpoints/unisolate.md) |
| incidents | `xdr_incidents_get_extra_data` | `POST /public_api/v1/incidents/get_incident_extra_data/` | Get extra data fields of a specific incident including alerts and key artifacts. | [→](incidents/get_extra_data.md) |
| incidents | `xdr_incidents_list` | `POST /public_api/v1/incidents/get_incidents/` | Get a list of incidents filtered by a list of incident IDs, modification time, o | [→](incidents/list.md) |
| ioc | `xdr_ioc_insert_json` | `POST /public_api/v1/indicators/insert_jsons/` | Upload IOCs as JSON objects that you retrieved from external threat intelligence | [→](ioc/insert_json.md) |
| response | `xdr_response_get_action_status` | `POST /public_api/v1/actions/get_action_status/` | Retrieve the status of the requested actions according to the action ID. | [→](response/get_action_status.md) |
| response | `xdr_response_get_file_retrieval_details` | `POST /public_api/v1/actions/file_retrieval_details/` | Retrieve the status of the requested file retrieval action. | [→](response/get_file_retrieval_details.md) |
| scripts | `xdr_scripts_get_execution_result_files` | `POST /public_api/v1/scripts/get_script_execution_result_files/` | Get the files retrieved from a specific endpoint during a script execution. | [→](scripts/get_execution_result_files.md) |
| scripts | `xdr_scripts_get_execution_results` | `POST /public_api/v1/scripts/get_script_execution_results/` | Retrieve the results of a script execution action. | [→](scripts/get_execution_results.md) |
| scripts | `xdr_scripts_get_execution_status` | `POST /public_api/v1/scripts/get_script_execution_status/` | Retrieve the status of a script execution action. | [→](scripts/get_execution_status.md) |
| scripts | `xdr_scripts_get_metadata` | `POST /public_api/v1/scripts/get_script_metadata/` | Get the full definitions of a specific script in the scripts library. | [→](scripts/get_metadata.md) |
| scripts | `xdr_scripts_list` | `POST /public_api/v1/scripts/get_scripts/` | Get a list of scripts available in the scripts library. | [→](scripts/list.md) |
| scripts | `xdr_scripts_run_script` | `POST /public_api/v1/scripts/run_script/` | Initiate a new endpoint script execution action using a script from the script l | [→](scripts/run_script.md) |
| scripts | `xdr_scripts_run_snippet` | `POST /public_api/v1/scripts/run_snippet_code_script/` | Initiate a new endpoint script execution action using a snippet code. | [→](scripts/run_snippet.md) |
| xql | `xdr_xql_get_results` | `POST /public_api/v1/xql/get_query_results/` | Returns the results of an XQL Query. | [→](xql/get_results.md) |
| xql | `xdr_xql_get_results_stream` | `POST /public_api/v1/xql/get_query_results_stream/` | Returns the results of an XQL Query. | [→](xql/get_results_stream.md) |
| xql | `xdr_xql_start_query` | `POST /public_api/v1/xql/start_xql_query/` | Starts an XQL Query. | [→](xql/start_query.md) |
