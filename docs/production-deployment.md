# Production deployment

The authoritative deployment, GitHub Settings, bootstrap, release, and rollback procedure is
[Production release runbook](production-release-runbook.md).

Deployment is manual, protected by GitHub Environments, authenticated to the broker with OIDC, and
uses immutable image and snapshot digests. No server address, remote account, or private key is
stored in this repository.
