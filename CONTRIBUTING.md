# Contributing

Thanks for helping improve **Discord Image Logger**. This project documents and
demonstrates security concepts for **authorized, educational use only** — every
contribution is expected to reinforce transparency, consent, and privacy.

## Ground rules

- Contributions must not add capabilities for covert monitoring, credential
  theft, evasion, stealth, or unauthorized data collection.
- Never submit **secrets** (tokens, webhook URLs, tunnel credentials) or
  **real user data** (real images, real Discord IDs, real IP addresses).
- Test only with synthetic data from private test servers.
- Security-sensitive changes must explain their threat model in the PR.

## Workflow

1. **Fork** the repository and create a feature branch:

   ```bash
   git checkout -b feat/short-description
   ```

2. **Make your changes.** Keep the standard-library-only runtime unless a
   dependency is justified in the PR description.

3. **Run the checks** available in this repository:

   ```bash
   python3 -m py_compile main.py run.py setup.py
   bash -n start.sh
   ```

   > [VERIFY AGAINST IMPLEMENTATION] This repository currently ships no
   > automated test suite. If you add tests, document how to run them here and
   > in `docs/testing.md`.

4. **Format / lint** with the project's chosen tools and keep style
   consistent with the surrounding code:

   ```bash
   # [VERIFY AGAINST IMPLEMENTATION] add the formatter/linter you adopt, e.g.
   # python3 -m black .
   # python3 -m ruff check .
   ```

5. **Review your diff for leaked material** before committing:

   ```bash
   git diff --cached | grep -iE "discord\.com/api/webhooks|BEGIN .* PRIVATE KEY|authtoken" || echo "clean"
   ```

6. **Submit a pull request** with:
   - What changed and why
   - How you tested it (synthetic data only)
   - Security/privacy impact (or "none")
   - Any follow-up work needed

## Security-sensitive changes

Changes to authentication, logging, tunnel behavior, outbound requests, data
retention, or anything touching collected data must include:

- The threat model before and after the change
- What an attacker could previously do that they can no longer do
- Whether any new data is collected, where it is stored, and for how long
- Confirmation that no real data or secrets are embedded in the PR

Report vulnerabilities privately per [SECURITY.md](SECURITY.md) — never in a
public issue or PR.

## Code of Conduct

[VERIFY AGAINST IMPLEMENTATION] Add a `CODE_OF_CONDUCT.md`
(e.g. the Contributor Covenant) and link it here before publishing the
repository.

## License

By contributing, you agree that your contributions are licensed under the
**MIT License** (see [LICENSE](LICENSE)). Do not submit code you are not
licensed to share.
