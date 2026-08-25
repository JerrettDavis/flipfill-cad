# Security Policy

## Supported versions

FlipFill CAD is pre-1.0. Security fixes are made against the `main` branch and
released in the next tagged version; there is no separate long-term-support branch
yet.

| Version | Supported |
| ------- | --------- |
| 0.x (latest tag) | ✅ |
| older 0.x tags | ❌ |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Instead, use GitHub's private vulnerability reporting for this repository
(Security tab → "Report a vulnerability"). If that is not available, open a draft
security advisory or contact the maintainer directly through their GitHub profile.

Include, if possible:

- A description of the issue and its impact.
- Steps to reproduce, including a minimal `.flipfill.json` project or CAD input file
  if the issue involves geometry import/export.
- The FlipFill CAD version (`flipfill --version`) and OS/Python version.

We aim to acknowledge new reports within 5 business days and to provide a status
update or fix timeline within 14 days.

## Scope notes specific to a CAD tool

FlipFill CAD parses untrusted geometry files (STEP, IGES, BREP, and mesh formats)
through OpenCascade/CadQuery and third-party mesh loaders. Memory-safety or
resource-exhaustion issues triggered by a malformed CAD file are in scope and are
taken seriously, even though the underlying parsing happens in a native dependency
rather than in this repository's own code — please report them here and we will
coordinate with upstream (CadQuery/OCP) as needed.

Issues that only reproduce with a project file the user already trusts and controls
(e.g. a `.flipfill.json` that intentionally references an absolute path) are
generally not security issues, since the CLI and GUI are local, single-user tools
with no network listener, remote execution surface, or multi-tenant trust boundary.
