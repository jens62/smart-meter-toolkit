# Commit messages

Always use [Conventional Commits](https://www.conventionalcommits.org/) format for commit messages in this repo: `<type>(<optional scope>): <description>`, e.g. `fix(meter_reading2consumption): remove duplicate timezone conversion`. Common types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.

# No real credentials or identifiers in tracked files

Scripts, crontab entries, `.awk` files, and documentation in this repo must stay generic - no hardwired real data. This includes gateway/InfluxDB credentials, tokens, usernames, passwords, and meter/gateway logical names or IDs (e.g. `01005e318002.1emh0011802881.sm`-style identifiers), even in comments, docstrings, `--help` text, or usage examples.

Use obviously-fake placeholders instead: `0100aabbccdd.1abc0012345678.sm` for a meter id (formats to `1 ABC00 1234 5678` via `format_measurement()`), `'...'` for secrets in `.env.example` files, `<user>`/`<password>`/`<meter>` style tokens in usage text. Real values belong only in `~/.config/smgw-pipeline.env` on the deployment host (gitignored, never committed) or under `local-assets/` (gitignored) - never in a script default, an awk `BEGIN` block, a test fixture, or prose.

If a script's own logic needs a real value as a fallback default (e.g. `normalize_meter_csv.awk` used to hardcode a real meter id as "what to use if nothing else is given"), fix the design instead of just swapping in a placeholder there too: require the value as an explicit argument and fail loudly if it's missing, rather than silently defaulting to anything - a hardcoded fallback is both a data-exposure risk and a correctness risk (silently mislabeling real data under whatever happened to be baked in).
