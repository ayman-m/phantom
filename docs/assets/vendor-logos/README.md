# Vendor-logo library

Standalone SVG/PNG files for every vendor that ships a data source bundled with Phantom.

## What this is

One file per vendor (not per pack). Extracted from the inline base64 logos in
`bundles/spark/data-sources/<pack-id>/data_source.yaml` files via
`scripts/extract_vendor_logos_library.py`.

## What this is NOT

This directory is a **maintainer artifact**. Phantom's runtime (the agent + MCP) does NOT
consume any file in this directory — runtime reads logos from the YAMLs themselves via the
inline-logo route (see `bundles/spark/mcp/src/api/data_sources.py`).

Intended consumers:
- Documentation / marketing material
- Future UI surfaces that want brand marks outside the data-sources page
- Operator-side reference

## How to regenerate

```bash
python3 scripts/extract_vendor_logos_library.py
```

Idempotent: same YAMLs → same files. Re-run whenever a YAML's inline logo is added or
changed.

## Inventory (137 vendors)

| Vendor | File | Format | Bytes | Source |
|---|---|---|---|---|
| 1Password | [`1password.svg`](./1password.svg) | SVG | 959 | `phantom-bundle` |
| Abnormal Security | [`abnormal-security.svg`](./abnormal-security.svg) | SVG | 331 | `phantom-bundle` |
| Absolute Software | [`absolute-software.svg`](./absolute-software.svg) | SVG | 331 | `phantom-bundle` |
| Admin By Request | [`admin-by-request.svg`](./admin-by-request.svg) | SVG | 330 | `phantom-bundle` |
| Akamai | [`akamai.svg`](./akamai.svg) | SVG | 5,790 | `phantom-bundle` |
| Alibaba | [`alibaba.svg`](./alibaba.svg) | SVG | 321 | `phantom-bundle` |
| Amazon | [`amazon.svg`](./amazon.svg) | SVG | 3,156 | `simpleicons:amazonaws` |
| Amazon Web Services | [`amazon-web-services.svg`](./amazon-web-services.svg) | SVG | 8,235 | `phantom-bundle` |
| Apache | [`apache.svg`](./apache.svg) | SVG | 3,153 | `simpleicons:apachetomcat` |
| Apple | [`apple.svg`](./apple.svg) | SVG | 650 | `simpleicons:apple` |
| Arista | [`arista.svg`](./arista.svg) | SVG | 2,250 | `wikipedia:File:Arista-networks-logo.svg` |
| Armis | [`armis.svg`](./armis.svg) | SVG | 319 | `phantom-bundle` |
| Atlassian | [`atlassian.svg`](./atlassian.svg) | SVG | 1,485 | `phantom-bundle` |
| Avaya | [`avaya.svg`](./avaya.svg) | SVG | 1,259 | `wikipedia:File:Avaya_Logo.svg` |
| Barracuda | [`barracuda.svg`](./barracuda.svg) | SVG | 323 | `phantom-bundle` |
| BeyondTrust | [`beyondtrust.png`](./beyondtrust.png) | PNG | 3,705 | `baked/Packs/BeyondTrust_Password_Safe/Integrations/BeyondTrust_Password_Safe/BeyondTrust_Password_Safe_image.png` |
| Bitbucket | [`bitbucket.svg`](./bitbucket.svg) | SVG | 1,696 | `phantom-bundle` |
| Bitsight | [`bitsight.svg`](./bitsight.svg) | SVG | 322 | `phantom-bundle` |
| Bitwarden | [`bitwarden.svg`](./bitwarden.svg) | SVG | 712 | `phantom-bundle` |
| Bluecat | [`bluecat.png`](./bluecat.png) | PNG | 3,975 | `baked/Packs/BluecatAddressManager/Integrations/BluecatAddressManager/BluecatAddressManager_image.png` |
| Box | [`box.svg`](./box.svg) | SVG | 2,282 | `phantom-bundle` |
| Brocade | [`brocade.svg`](./brocade.svg) | SVG | 8,190 | `wikipedia:File:Brocade_Communications_Systems_logo.svg` |
| Carbon Black | [`carbon-black.svg`](./carbon-black.svg) | SVG | 326 | `phantom-bundle` |
| Celonis | [`celonis.svg`](./celonis.svg) | SVG | 321 | `phantom-bundle` |
| Check Point | [`check-point.svg`](./check-point.svg) | SVG | 325 | `phantom-bundle` |
| Cisco | [`cisco.svg`](./cisco.svg) | SVG | 2,596 | `phantom-bundle` |
| Citrix | [`citrix.svg`](./citrix.svg) | SVG | 654 | `simpleicons:citrix` |
| Claroty | [`claroty.svg`](./claroty.svg) | SVG | 321 | `phantom-bundle` |
| Clearswift | [`clearswift.png`](./clearswift.png) | PNG | 11,569 | `wikipedia:File:Clearswift_-_A_HelpSystems_Logo.png` |
| Cloudflare | [`cloudflare.svg`](./cloudflare.svg) | SVG | 6,916 | `phantom-bundle` |
| Code42 | [`code42.svg`](./code42.svg) | SVG | 320 | `phantom-bundle` |
| Cohesity | [`cohesity.svg`](./cohesity.svg) | SVG | 322 | `phantom-bundle` |
| Corelight | [`corelight.svg`](./corelight.svg) | SVG | 323 | `phantom-bundle` |
| CybelAngel | [`cybelangel.svg`](./cybelangel.svg) | SVG | 324 | `phantom-bundle` |
| CyberArk | [`cyberark.svg`](./cyberark.svg) | SVG | 322 | `phantom-bundle` |
| CYFIRMA DeCYFIR | [`cyfirma-decyfir.svg`](./cyfirma-decyfir.svg) | SVG | 329 | `phantom-bundle` |
| Darktrace | [`darktrace.svg`](./darktrace.svg) | SVG | 323 | `phantom-bundle` |
| Delinea | [`delinea.svg`](./delinea.svg) | SVG | 321 | `phantom-bundle` |
| Dell EMC | [`dell-emc.svg`](./dell-emc.svg) | SVG | 1,450 | `simpleicons:dell` |
| Digital Guardian | [`digital-guardian.svg`](./digital-guardian.svg) | SVG | 330 | `phantom-bundle` |
| DocuSign | [`docusign.svg`](./docusign.svg) | SVG | 201 | `phantom-bundle` |
| Dragos | [`dragos.svg`](./dragos.svg) | SVG | 320 | `phantom-bundle` |
| Dropbox | [`dropbox.svg`](./dropbox.svg) | SVG | 752 | `phantom-bundle` |
| Druva | [`druva.svg`](./druva.svg) | SVG | 319 | `phantom-bundle` |
| Duo Security | [`duo-security.svg`](./duo-security.svg) | SVG | 326 | `phantom-bundle` |
| Exabeam | [`exabeam.svg`](./exabeam.svg) | SVG | 321 | `phantom-bundle` |
| ExtraHop | [`extrahop.svg`](./extrahop.svg) | SVG | 322 | `phantom-bundle` |
| F5 | [`f5.svg`](./f5.svg) | SVG | 2,576 | `simpleicons:f5` |
| FireEye | [`fireeye.svg`](./fireeye.svg) | SVG | 321 | `phantom-bundle` |
| Forcepoint | [`forcepoint.svg`](./forcepoint.svg) | SVG | 324 | `phantom-bundle` |
| Forescout | [`forescout.svg`](./forescout.svg) | SVG | 323 | `phantom-bundle` |
| Fortinet | [`fortinet.svg`](./fortinet.svg) | SVG | 474 | `phantom-bundle` |
| Genesys | [`genesys.svg`](./genesys.svg) | SVG | 321 | `phantom-bundle` |
| Genetec | [`genetec.svg`](./genetec.svg) | SVG | 321 | `phantom-bundle` |
| GitGuardian | [`gitguardian.svg`](./gitguardian.svg) | SVG | 325 | `phantom-bundle` |
| GitHub | [`github.svg`](./github.svg) | SVG | 6,111 | `phantom-bundle` |
| GitLab | [`gitlab.svg`](./gitlab.svg) | SVG | 6,799 | `phantom-bundle` |
| Google | [`google.svg`](./google.svg) | SVG | 4,527 | `phantom-bundle` |
| HashiCorp | [`hashicorp.svg`](./hashicorp.svg) | SVG | 6,202 | `phantom-bundle` |
| Hello World (Demo) | [`hello-world-demo.svg`](./hello-world-demo.svg) | SVG | 332 | `phantom-bundle` |
| HPE | [`hpe.svg`](./hpe.svg) | SVG | 317 | `phantom-bundle` |
| Huawei | [`huawei.svg`](./huawei.svg) | SVG | 1,323 | `phantom-bundle` |
| IBM | [`ibm.svg`](./ibm.svg) | SVG | 4,776 | `phantom-bundle` |
| Illusive Networks | [`illusive-networks.svg`](./illusive-networks.svg) | SVG | 331 | `phantom-bundle` |
| Imperva | [`imperva.svg`](./imperva.svg) | SVG | 321 | `phantom-bundle` |
| Infoblox | [`infoblox.svg`](./infoblox.svg) | SVG | 322 | `phantom-bundle` |
| Ironscales | [`ironscales.svg`](./ironscales.svg) | SVG | 324 | `phantom-bundle` |
| Ivanti | [`ivanti.svg`](./ivanti.svg) | SVG | 1,916 | `wikipedia:File:Ivanti_Logo_RGB_red.svg` |
| Jamf | [`jamf.svg`](./jamf.svg) | SVG | 318 | `phantom-bundle` |
| Juniper | [`juniper.svg`](./juniper.svg) | SVG | 3,211 | `simpleicons:junipernetworks` |
| Keeper Security | [`keeper-security.svg`](./keeper-security.svg) | SVG | 329 | `phantom-bundle` |
| Kiteworks | [`kiteworks.svg`](./kiteworks.svg) | SVG | 2,431 | `wikipedia:File:Kiteworks_logo.svg` |
| KnowBe4 | [`knowbe4.svg`](./knowbe4.svg) | SVG | 321 | `phantom-bundle` |
| Kubernetes | [`kubernetes.svg`](./kubernetes.svg) | SVG | 3,565 | `simpleicons:kubernetes` |
| LenelS2 | [`lenels2.svg`](./lenels2.svg) | SVG | 321 | `phantom-bundle` |
| Linux | [`linux.svg`](./linux.svg) | SVG | 5,463 | `simpleicons:linux` |
| Lookout | [`lookout.svg`](./lookout.svg) | SVG | 321 | `phantom-bundle` |
| ManageEngine | [`manageengine.svg`](./manageengine.svg) | SVG | 326 | `phantom-bundle` |
| McAfee | [`mcafee.svg`](./mcafee.svg) | SVG | 238 | `phantom-bundle` |
| Microsoft | [`microsoft.svg`](./microsoft.svg) | SVG | 9,560 | `phantom-bundle` |
| Mimecast | [`mimecast.svg`](./mimecast.svg) | SVG | 322 | `phantom-bundle` |
| monday.com | [`monday-com.svg`](./monday-com.svg) | SVG | 7,973 | `phantom-bundle` |
| MongoDB | [`mongodb.svg`](./mongodb.svg) | SVG | 14,185 | `phantom-bundle` |
| MySQL | [`mysql.svg`](./mysql.svg) | SVG | 3,625 | `simpleicons:mysql` |
| Nasuni | [`nasuni.svg`](./nasuni.svg) | SVG | 320 | `phantom-bundle` |
| NetBox | [`netbox.svg`](./netbox.svg) | SVG | 320 | `phantom-bundle` |
| Netmotion | [`netmotion.svg`](./netmotion.svg) | SVG | 323 | `phantom-bundle` |
| Netskope | [`netskope.svg`](./netskope.svg) | SVG | 322 | `phantom-bundle` |
| NGINX | [`nginx.svg`](./nginx.svg) | SVG | 413 | `simpleicons:nginx` |
| NVIDIA | [`nvidia.svg`](./nvidia.svg) | SVG | 4,031 | `phantom-bundle` |
| Okta | [`okta.svg`](./okta.svg) | SVG | 10,488 | `phantom-bundle` |
| OneLogin | [`onelogin.svg`](./onelogin.svg) | SVG | 322 | `phantom-bundle` |
| Oracle | [`oracle.svg`](./oracle.svg) | SVG | 3,255 | `phantom-bundle` |
| Orca Security | [`orca-security.svg`](./orca-security.svg) | SVG | 327 | `phantom-bundle` |
| Palo Alto Networks | [`palo-alto-networks.svg`](./palo-alto-networks.svg) | SVG | 332 | `phantom-bundle` |
| Portnox | [`portnox.svg`](./portnox.svg) | SVG | 321 | `phantom-bundle` |
| Proofpoint | [`proofpoint.svg`](./proofpoint.svg) | SVG | 324 | `phantom-bundle` |
| Qualys | [`qualys.svg`](./qualys.svg) | SVG | 785 | `phantom-bundle` |
| Radware | [`radware.svg`](./radware.svg) | SVG | 321 | `phantom-bundle` |
| Reblaze | [`reblaze.svg`](./reblaze.svg) | SVG | 321 | `phantom-bundle` |
| Recorded Future | [`recorded-future.svg`](./recorded-future.svg) | SVG | 329 | `phantom-bundle` |
| ReliaQuest | [`reliaquest.svg`](./reliaquest.svg) | SVG | 324 | `phantom-bundle` |
| Retarus | [`retarus.svg`](./retarus.svg) | SVG | 321 | `phantom-bundle` |
| RSA | [`rsa.svg`](./rsa.svg) | SVG | 713 | `direct:https://www.vectorlogo.zone/logos/rsa/rsa-icon.svg` |
| runZero | [`runzero.svg`](./runzero.svg) | SVG | 321 | `phantom-bundle` |
| SailPoint | [`sailpoint.svg`](./sailpoint.svg) | SVG | 323 | `phantom-bundle` |
| Salesforce | [`salesforce.svg`](./salesforce.svg) | SVG | 18,292 | `phantom-bundle` |
| Saviynt | [`saviynt.svg`](./saviynt.svg) | SVG | 321 | `phantom-bundle` |
| SecureAuth | [`secureauth.svg`](./secureauth.svg) | SVG | 5,091 | `secureauth.com/assets/secureauth-logo-white-JQccCguH.svg (recolored white→#1A2238 for visibility on near-white card panel)` |
| Semperis | [`semperis.svg`](./semperis.svg) | SVG | 1,115 | `hand-crafted by phantom-maintainer — wordmark in Semperis brand navy #0F1934` |
| ServiceNow | [`servicenow.svg`](./servicenow.svg) | SVG | 324 | `phantom-bundle` |
| Shodan | [`shodan.svg`](./shodan.svg) | SVG | 320 | `phantom-bundle` |
| Siemens | [`siemens.svg`](./siemens.svg) | SVG | 1,427 | `simpleicons:siemens` |
| Silverfort | [`silverfort.svg`](./silverfort.svg) | SVG | 324 | `phantom-bundle` |
| Slack | [`slack.svg`](./slack.svg) | SVG | 5,269 | `phantom-bundle` |
| SonicWall | [`sonicwall.svg`](./sonicwall.svg) | SVG | 2,524 | `simpleicons:sonicwall` |
| SpecterOps BloodHound | [`specterops-bloodhound.svg`](./specterops-bloodhound.svg) | SVG | 335 | `phantom-bundle` |
| Squid | [`squid.png`](./squid.png) | PNG | 12,716 | `direct-png:https://upload.wikimedia.org/wikipedia/commons/0/0b/Squid_Now.png` |
| Symantec | [`symantec.svg`](./symantec.svg) | SVG | 1,004 | `phantom-bundle` |
| Synopsys | [`synopsys.svg`](./synopsys.svg) | SVG | 322 | `phantom-bundle` |
| Tableau | [`tableau.svg`](./tableau.svg) | SVG | 914 | `simpleicons:tableau` |
| Tanium | [`tanium.svg`](./tanium.svg) | SVG | 2,138 | `wikipedia:Tanium_logo (white→#1A2238 recolored for visibility on near-white panel)` |
| TeamViewer | [`teamviewer.svg`](./teamviewer.svg) | SVG | 481 | `phantom-bundle` |
| Tenable | [`tenable.svg`](./tenable.svg) | SVG | 321 | `phantom-bundle` |
| Thales | [`thales.svg`](./thales.svg) | SVG | 320 | `phantom-bundle` |
| Thinkst | [`thinkst.svg`](./thinkst.svg) | SVG | 5,207 | `wikipedia:Thinkst_logo (white text recolored to #1A2238)` |
| Tigera | [`tigera.svg`](./tigera.svg) | SVG | 2,884 | `direct:https://www.tigera.io/app/uploads/2026/01/Tigera-logo-2026-black-text.svg` |
| Trend Micro | [`trend-micro.svg`](./trend-micro.svg) | SVG | 856 | `phantom-bundle` |
| Ubiquiti | [`ubiquiti.svg`](./ubiquiti.svg) | SVG | 1,321 | `phantom-bundle` |
| Vectra AI | [`vectra-ai.svg`](./vectra-ai.svg) | SVG | 323 | `phantom-bundle` |
| VMware | [`vmware.svg`](./vmware.svg) | SVG | 6,098 | `phantom-bundle` |
| WatchGuard | [`watchguard.svg`](./watchguard.svg) | SVG | 324 | `phantom-bundle` |
| WithSecure | [`withsecure.svg`](./withsecure.svg) | SVG | 324 | `phantom-bundle` |
| Workday | [`workday.svg`](./workday.svg) | SVG | 321 | `phantom-bundle` |
| Zero Networks | [`zero-networks.svg`](./zero-networks.svg) | SVG | 327 | `phantom-bundle` |
| Zoom | [`zoom.svg`](./zoom.svg) | SVG | 2,824 | `phantom-bundle` |
| Zscaler | [`zscaler.svg`](./zscaler.svg) | SVG | 321 | `phantom-bundle` |

## License

Each logo's license is recorded in `manifest.yaml` under its `license:` field. Many are
trademarks of their respective owners; some are CC-licensed (CC BY-SA 3.0 / 4.0,
CC0-1.0). When reusing these files outside Phantom, check the license per vendor.
