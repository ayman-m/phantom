# Cortex XSIAM — endpoint index

Mirrors the XDR knowledge tree structure.
This index lists 35 endpoints + 5 XSIAM-unique additions (parsers/datamodel/broker).
Common surface (incidents/alerts/endpoints/response/scripts/ioc/download/admin) is the same /public_api/v1/... shape as XDR — copied from cortex-xdr/action/ with xdr_→xsiam_ substitution.

| Category | MCP tool | HTTP endpoint | Purpose | Doc |
|---|---|---|---|---|
| alerts | `xsiam_alerts_list` | `POST /public_api/v1/alerts/get_alerts_multi_events/` | Get a list of alerts with multiple events. | [→](alerts/list.md) |
| alerts | `xsiam_alerts_update` | `POST /public_api/v1/alerts/update_alerts/` | Bulk-update one or more alerts. Common operations: change se | [→](alerts/update.md) |
| broker | `xsiam_broker_get` | `POST /public_api/v1/broker/get_broker/` | Full status + config detail for one broker VM. | [→](broker/get.md) |
| broker | `xsiam_broker_list` | `POST /public_api/v1/broker/list_brokers/` | List XSIAM Broker VMs deployed in this tenant. Brokers are d | [→](broker/list.md) |
| datamodel | `xsiam_datamodel_describe` | `POST /public_api/v1/xql/start_xql_query/` | XSIAM-licensed datamodel introspection. Returns the XDM-type | [→](datamodel/describe.md) |
| download | `xsiam_download_file` | `POST /public_api/v1/download/download_file/` | Downloads the file at the given URI, previously requested by | [→](download/file.md) |
| endpoints | `xsiam_endpoints_get` | `POST /public_api/v1/endpoints/get_endpoint/` | Gets a list of filtered endpoints. | [→](endpoints/get.md) |
| endpoints | `xsiam_endpoints_isolate` | `POST /public_api/v1/endpoints/isolate/` | Isolate one or more endpoints in a single request. Request i | [→](endpoints/isolate.md) |
| endpoints | `xsiam_endpoints_list_all` | `POST /public_api/v1/endpoints/get_endpoints/` | Gets a list of your endpoints. | [→](endpoints/list_all.md) |
| endpoints | `xsiam_endpoints_quarantine_file` | `POST /public_api/v1/endpoints/quarantine/` | Quarantine file on selected endpoints. You can select up to  | [→](endpoints/quarantine_file.md) |
| endpoints | `xsiam_endpoints_retrieve_file` | `POST /public_api/v1/endpoints/file_retrieval/` | Retrieve files from selected endpoints. You can retrieve up  | [→](endpoints/retrieve_file.md) |
| endpoints | `xsiam_endpoints_scan` | `POST /public_api/v1/endpoints/scan/` | Run a scan on selected endpoints. | [→](endpoints/scan.md) |
| endpoints | `xsiam_endpoints_scan_all` | `POST /public_api/v1/endpoints/scan/` | Scans all endpoints. | [→](endpoints/scan_all.md) |
| endpoints | `xsiam_endpoints_set_alias` | `POST /public_api/v1/endpoints/update_agent_name/` | Set or modify an Alias field for your endpoints. | [→](endpoints/set_alias.md) |
| endpoints | `xsiam_endpoints_unisolate` | `POST /public_api/v1/endpoints/unisolate/` | Unisolate one or more endpoints in a single request. Request | [→](endpoints/unisolate.md) |
| incidents | `xsiam_incidents_get_extra_data` | `POST /public_api/v1/incidents/get_incident_extra_data/` | Get extra data fields of a specific incident including alert | [→](incidents/get_extra_data.md) |
| incidents | `xsiam_incidents_list` | `POST /public_api/v1/incidents/get_incidents/` | Get a list of incidents filtered by a list of incident IDs,  | [→](incidents/list.md) |
| incidents | `xsiam_incidents_update` | `POST /public_api/v1/incidents/update_incident/` | Update one XDR incident's mutable metadata fields — status,  | [→](incidents/update.md) |
| ioc | `xsiam_ioc_disable` | `POST /public_api/v1/indicators/disable_iocs/` | Disable one or more IoCs — XDR stops alerting/blocking on th | [→](ioc/disable.md) |
| ioc | `xsiam_ioc_enable` | `POST /public_api/v1/indicators/enable_iocs/` | Re-enable previously disabled IoCs. Mirror of `xsiam_ioc_dis | [→](ioc/enable.md) |
| ioc | `xsiam_ioc_insert_json` | `POST /public_api/v1/indicators/insert_jsons/` | Upload IOCs as JSON objects that you retrieved from external | [→](ioc/insert_json.md) |
| parsers | `xsiam_parsers_get` | `POST /public_api/v1/parser/get_parser/` | Get the full definition of one parser (parsing rules, field  | [→](parsers/get.md) |
| parsers | `xsiam_parsers_list` | `POST /public_api/v1/parser/get_parsers/` | List parsers configured in the XSIAM tenant. Parsers transfo | [→](parsers/list.md) |
| response | `xsiam_response_get_action_status` | `POST /public_api/v1/actions/get_action_status/` | Retrieve the status of the requested actions according to th | [→](response/get_action_status.md) |
| response | `xsiam_response_get_file_retrieval_details` | `POST /public_api/v1/actions/file_retrieval_details/` | Retrieve the status of the requested file retrieval action. | [→](response/get_file_retrieval_details.md) |
| scripts | `xsiam_scripts_get_execution_result_files` | `POST /public_api/v1/scripts/get_script_execution_result_files/` | Get the files retrieved from a specific endpoint during a sc | [→](scripts/get_execution_result_files.md) |
| scripts | `xsiam_scripts_get_execution_results` | `POST /public_api/v1/scripts/get_script_execution_results/` | Retrieve the results of a script execution action. | [→](scripts/get_execution_results.md) |
| scripts | `xsiam_scripts_get_execution_status` | `POST /public_api/v1/scripts/get_script_execution_status/` | Retrieve the status of a script execution action. | [→](scripts/get_execution_status.md) |
| scripts | `xsiam_scripts_get_metadata` | `POST /public_api/v1/scripts/get_script_metadata/` | Get the full definitions of a specific script in the scripts | [→](scripts/get_metadata.md) |
| scripts | `xsiam_scripts_list` | `POST /public_api/v1/scripts/get_scripts/` | Get a list of scripts available in the scripts library. | [→](scripts/list.md) |
| scripts | `xsiam_scripts_run_script` | `POST /public_api/v1/scripts/run_script/` | Initiate a new endpoint script execution action using a scri | [→](scripts/run_script.md) |
| scripts | `xsiam_scripts_run_snippet` | `POST /public_api/v1/scripts/run_snippet_code_script/` | Initiate a new endpoint script execution action using a snip | [→](scripts/run_snippet.md) |
| xql | `xsiam_xql_get_results` | `POST /public_api/v1/xql/get_query_results/` | Returns the results of an XQL Query. | [→](xql/get_results.md) |
| xql | `xsiam_xql_get_results_stream` | `POST /public_api/v1/xql/get_query_results_stream/` | Returns the results of an XQL Query. | [→](xql/get_results_stream.md) |
| xql | `xsiam_xql_start_query` | `POST /public_api/v1/xql/start_xql_query/` | Starts an XQL Query. | [→](xql/start_query.md) |
