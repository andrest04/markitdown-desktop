# Security Policy

## Supported Versions

Only the latest release is supported with security fixes.

| Version | Supported |
| ------- | --------- |
| latest  | ✅        |
| older   | ❌        |

## Reporting a Vulnerability

If you find a security issue (for example, unsafe handling of untrusted
input during file conversion, or something that could execute code from
a malicious file), please **do not open a public issue**.

Instead, report it privately via [GitHub Security Advisories](https://github.com/andrest04/markitdown-desktop/security/advisories/new)
for this repository. Include:

- A description of the vulnerability and its impact
- Steps to reproduce it, or a proof-of-concept file if relevant
- The affected version/commit

You should get an initial response within a few days. Once a fix is
available, a new release will be published and the advisory disclosed.

Note that this app wraps Microsoft's [`markitdown`](https://github.com/microsoft/markitdown)
package for the actual file parsing. If the issue originates in
`markitdown` itself rather than in this GUI's code, please also report it
upstream following their security policy.
