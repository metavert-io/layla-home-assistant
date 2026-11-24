# Security

## Reporting a problem

Please don't open a public issue for a security problem. Report it privately instead:
**[Report a vulnerability](https://github.com/metavert-io/layla-home-assistant/security/advisories/new)** (on the
repository's Security tab). Only the maintainers can see it.

Say what the problem is, how to reproduce it, and which version you're using. Leave out your Layla email, password,
tokens and anything that identifies your property or devices: if a log or diagnostics file would help, say so, and
we'll ask for what's needed.

## What's in scope

- This integration's code: how it signs in to Layla, stores the refresh token, talks to Layla's API, and what it
  puts in diagnostics and logs.
- Its GitHub workflows.

Problems in Layla's own service or apps belong with LaylaElectric, and problems in Home Assistant or HACS with
their projects.

## Supported versions

Fixes go into the latest release. Update through HACS to get them.
