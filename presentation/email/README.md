# Presentation: daily/monthly consumption mail report

Reads the `../../persistence/mysql/` rollup tables and builds one HTML
report covering hourly (yesterday), daily (last 14 days), weekly (last 10
weeks), monthly, quarterly, and yearly consumption, with a bar visualization
per row. The same HTML is:

- written to a local directory (`--local-publish-dir`)
- copied via SSH to a public webserver (`--remote-ssh-host`/`--remote-publish-dir`)
- emailed to `--recipient` (optionally cc'd)

There's no separate "website" component today - the published HTML file
*is* the website view, produced by the same script/artifact that gets
emailed. A link back to "view this in your browser" (pointing at
`--public-base-url`) gets added to the emailed copy.

## Setup

1. Finish `../../persistence/mysql/README.md` first - this script only
   reads from those tables.
2. `pip install mysql-connector-python beautifulsoup4 plumbum` (see the
   top-level README's Requirements section).
3. Copy `three-phase-meter-mail.env.example` to `~/.config/three-phase-meter-mail.env`
   and fill in the real values.
4. `--remote-ssh-host` must be a host alias already set up in `~/.ssh/config`
   (key-based auth, no password prompt) - the script shells out to it via
   `plumbum`.
5. Add the job from `crontab.example` to your crontab.

## Notes

- `--device-id` must match whatever you used in `../../persistence/mysql/schema.sql`
  and the telegraf configs.
- The monthly/weekly/quarterly/yearly queries exclude the still-open current
  period (see the "Known quirk" section in `../../persistence/mysql/README.md`)
  - otherwise a near-zero stub row for the period-in-progress would show up
    in every report until the next period boundary resolves it.
- Every value that used to be hardcoded (real email addresses, the public
  report URL, DB credentials, publish paths) is now a required CLI flag -
  the script fails at startup with a clear `argparse` error if one is
  missing, rather than silently falling back to something wrong.
