# Cortex XDR — simulation recipes (placeholder)

This directory is reserved for data-source YAMLs that describe how Phantom's
xlog should generate XDR-shaped records for operator-driven simulation
workflows.

It is currently empty: the Cortex XDR data source bundled in
`bundles/spark/data-sources/` already ships for the marketplace, and the
simulation YAMLs there are sufficient. The directory exists so the layout
matches the broader vendor knowledge tree
(`data/knowledge/external/<vendor>/<product>/{action,simulation}/`).
Custom XDR-flavored simulation scenarios beyond what the marketplace
provides belong here.
