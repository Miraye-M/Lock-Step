# Dedicated distribution migration

Version 2 is a deliberate breaking conversion from general-purpose Spec Kit to
ACC-to-ACS remediation, now named Lockstep. The executable remains `specify` and
the Python package remains `specify_cli` so existing installs and generated
`.vscode/mcp.json` launchers keep working; this is not a drop-in upgrade for old
feature workflows. A `lockstep` console alias is a candidate follow-up listed in
the [roadmap](roadmap.md).

Removed product surfaces include other assistant adapters, extension/preset/
bundle installation, remote community catalogs, feature-specification and idea-
assessment workflows, generic bootstrap scripts, translated promotional pages,
and upstream publishing/triage automation. Their tests were retired with those
features. The bug assessment/fix/test separation informs the new remediation
stages rather than shipping as a second generic product.

Retained infrastructure includes workflow execution/checkpoint/replay,
expressions, local workflow composition/registries, Copilot dispatch, ownership
manifests, filesystem helpers and security primitives. Their applicable tests
remain. Root CLI/MCP commands now expose remediation and version/stdio hosting.

Use a new control directory for remediation. Initialization never deletes an
existing ACS repository or migrates old `.specify` runs. Generated agent files
are hash tracked; modified files are preserved with an actionable error. VS Code
MCP configuration is merged without claiming ownership of other server entries.

No real Jira, Jenkins, AFT or PR was contacted by the mock demonstration. Company
connectors must be implemented and validated before a live deployment. There is
no automatic merge, production deployment, scheduled discovery, concurrent ticket
execution or reset of an exhausted repair budget.

The final workspace cleanup removes obsolete extension-hook Markdown fixtures,
other-assistant issue lists and upstream catalog/distribution links. Architecture
guides now describe the retained CLI/MCP operations. FileHelper security contracts
and their tests remain, while documentation of deleted init/catalog interfaces is
removed. Generated state and fixture repositories are ignored; maintained agent
profiles, tests and documentation remain reviewable source files.

This checkout's completed demo was separately copied into the root control project,
with original evidence archived and operational paths repaired. It was not rerun
or committed. See [persistent workspace](workspace.md) for the local layout and
integrity record; this was a one-time preservation, not a generic migration command.
