# How do I send logs to Cortex XSIAM from Cribl?

To stream logs from **Cribl Stream** into Cortex XSIAM, configure the XSIAM destination, then route each Cribl source through the Palo Alto XSIAM pack. Follow the detailed [Ingest data from Cribl](/cortex-xsiam/configure-cortex-xsiam/cortex-xsiam-data-sources/vendor-specific-data-sources-and-connectors/cribl/ingest-data-from-cribl) page.

1. **Onboard sources in Cribl.** Use a dedicated source collector for each data type.
2. **Create the XSIAM integration credentials.** In Cortex XSIAM, go to **Settings → Data Sources & Integrations → + Add New**, select **Cribl**, then choose **Save & generate token**.
3. **Configure Cribl's XSIAM destination.** Enter the API URL and authorization token.

# Suggested Follow-up Questions:

If you need more information, consider asking one of these follow-up questions by performing an HTTP GET request on the URL:

- [What sources need separate Cribl collectors?](https://cortex-docs.paloaltonetworks.com?ask=What%20sources%20need%20separate%20Cribl%20collectors%3F)
- [How to verify Cribl-XSIAM token validity?](https://cortex-docs.paloaltonetworks.com?ask=How%20to%20verify%20Cribl-XSIAM%20token%20validity%3F)

# Sources:

- [Ingest data from Cribl](https://cortex-docs.paloaltonetworks.com/cortex-xsiam/configure-cortex-xsiam/cortex-xsiam-data-sources/vendor-specific-data-sources-and-connectors/cribl/ingest-data-from-cribl.md)
- [Collect Windows Event Logs for Cortex XSIAM via Cribl](https://cortex-docs.paloaltonetworks.com/cortex-xsiam/configure-cortex-xsiam/cortex-xsiam-data-sources/vendor-specific-data-sources-and-connectors/cribl/ingest-data-from-cribl-windows.md)
- [Ingest data from Cribl](https://cortex-docs.paloaltonetworks.com/cortex-xsiam/configure-cortex-xsiam/cortex-xsiam-data-sources/vendor-specific-data-sources-and-connectors/cribl/ingest-data-from-cribl.md)
