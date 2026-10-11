"""Minimal Caldera plugin shell for Phantom-shipped content.

Wraps Phantom's curated abilities and adversaries as a proper Caldera
plugin. Content lives at plugins/phantom/data/ and is image-baked
(NOT volume-mounted), so it persists across container recreates.

This plugin has no Python code beyond this shell, no GUI tab, no
executor, no obfuscator. Caldera's plugin loader registers the
plugin metadata and triggers data_svc to scan plugins/phantom/data/
on startup.
"""


name = "Phantom"
description = (
    "Phantom-shipped curated Caldera content: kill-chain abilities, "
    "lab-safe lookalikes, and adversary profiles. Image-baked at "
    "plugins/phantom/data/; survives volume-preserving container "
    "recreates because plugins/ is NOT volume-mounted."
)
# Empty address means no GUI tab. The plugin loader still registers
# the plugin + triggers data_svc to scan plugins/phantom/data/*.
address = ""


async def enable(services):
    """No-op enable hook.

    Caldera's app_svc calls this after loading the plugin. Pure-content
    plugins have nothing to do here — data_svc already scanned our
    abilities + adversaries at startup. No HTTP routes to register,
    no obfuscator to install, no executor to wire.
    """
    return None
