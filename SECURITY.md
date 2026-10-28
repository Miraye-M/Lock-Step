# Security

Lockstep handles vulnerability evidence and can execute configured local
commands and service integrations under the worker's operating-system identity.
Use scoped credentials and an isolated account/container for live repositories.
Do not expose its local stdio servers as unauthenticated network services.

The default demo uses simulated services and a local Git remote. Mock results are
not production security verification. Production connectors must enforce their
idempotency contract and report incomplete or ambiguous results as errors.

Report sensitive issues through your organization's approved private security
channel. Do not post credentials, private source, exploit details or internal Jira
content in public issues. The upstream Spec Kit project does not operate or
support this dedicated deployment.

Security-sensitive changes require regression evidence for relevant path,
symlink, approval, commit-binding and side-effect recovery failures. Dependency
auditing and CodeQL remain enabled in CI.
