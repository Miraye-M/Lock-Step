# Workflow runtime

The remediation worker uses the retained Spec Kit workflow engine for durable
occurrence checkpointing and replay. Its registered `remediation` step advances
one application stage per tick. Domain evidence is stored separately from the
engine checkpoint. See [architecture](../docs/architecture.md).

Generic feature, bugfix and idea-assessment workflow products are no longer
shipped. The internal engine retains expressions, gates, local composition and
control flow with their regression tests. Remote workflow/step catalogs and
package-install commands have been removed.
