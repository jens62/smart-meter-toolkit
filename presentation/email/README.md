# Presentation: daily/monthly consumption mail report

Reads the `../../persistence/mysql/` rollup tables and builds one HTML
report covering hourly (yesterday), daily (last 14 days), weekly (last 10
weeks), monthly, quarterly, and yearly consumption, with a bar visualization
per row. The same HTML is:

- written to a local directory (`--local-publish-dir`)
- copied via SSH to a public webserver (`--remote-ssh-host`/`--remote-publish-dir`)
- emailed to `--recipient` (optionally cc'd)

A link back to "view this in your browser" (pointing at `--public-base-url`)
gets added to the emailed copy - see `../website/` for the archive page
that link lands on.

## Deployment status

Live on `raspi4-8GB-Jag` since 2026-08-31, replacing the hardcoded
predecessor at the same cron slot (`0 7 * * *`). Config lives in
`~/.config/three-phase-meter-mail.env` on that host - not in this repo, and
not reconstructable from it. The pre-refactor script and crontab are backed
up on the host itself, in `/home/jens/homeautomation/mail/`:

- `send_results_from_DB_as_html_mail_daily_with_bar_3dec (31.08.26, backup-pre-config-refactor).py`
- `crontab.bak_2026-08-31.txt`

Rollback: comment out the new crontab line and uncomment the old one (kept
directly above it in the live crontab), or restore from the backup files
above.

### Original bug report and root-cause analysis

This is what prompted the whole port/config-refactor. Recorded here because
none of it lives in git history otherwise, and per the update below, the fix
that shipped did not fully resolve it.

**Symptom (reported 2026-08-01):** the live report's monthly table had a
spurious row for the month that had barely started:
`<tr><td>01.08.2026 - 01.08.2026</td>...` alongside near-zero consumption
figures, on the very first day of August.

**Root cause:** the monthly rollup table
(`tasmota_DB2090_SENSOR_CONSUMPTION_monthly`, see
`../../persistence/mysql/`) is maintained by the hourly MySQL event
`ev_calculate_consumption` calling `proc_calculate_consumption_all_rates`.
Its monthly branch only fires at `01 00:00:00`. At that instant it takes the
delta between the newest raw meter reading and whatever the last row in the
monthly table was. Because a new raw reading exists within seconds of any
month boundary, this produces two rows in the same run: the correct final
total for the month that just ended, *and* a near-zero "stub" row dated the
first moment of the month that just started:

```
time                     power_consumption_total
2026-07-31 23:59:32      361.45079265   <- July's real total
2026-08-01 00:00:02      0.00094824     <- meaningless stub for August
```

That stub isn't August's consumption - it's the ~30-second gap between the
last July reading and the first August reading. It sat there as the
table's newest row for the entire month (confirmed still present on
2026-08-30), because August's real total wasn't computed until the
following (September) rollover.

**Confirmed the same bug affects weekly, not just monthly** - found
identical stub rows in `tasmota_DB2090_SENSOR_CONSUMPTION_weekly`:

```
2026-08-16 23:59:33   87.44    <- correct week total
2026-08-17 00:00:03    0.0011  <- phantom stub for the new week
2026-08-24 00:00:02    0.0014  <- phantom stub for the following week
```

**Daily is not immune by design, just self-healing.** The same mechanism
applies every midnight, but since the daily branch reprocesses every 24
hours, a phantom created for "today" gets folded into the correct
calculation the very next midnight instead of lingering for a full period -
so it's rarely visible. 34 historical daily phantom rows were still found
in the table (April-May 2025, and one in Dec 2025), confirming the
mechanism isn't actually different for daily, just faster to self-correct.

**The fix that shipped** (in this script's SQL, see the "Notes" section
below) excludes the still-open *current* period from the
monthly/weekly/quarterly/yearly queries - it does not touch
`proc_calculate_consumption_all_rates` itself.

**Update 2026-09-01: this fix did not fully work in practice.** The
current-period exclusion only hides the stub for the period that's
*currently in progress* - it does nothing about stub rows that were already
written for *past*, completed periods and are still sitting in the table.
One was already spotted during the 2026-08-31 deployment test: a leftover
`01.06.2026 - 01.06.2026` stub row was still showing up in the monthly
table, between July and May, unaffected by the current-period filter (see
git history for that finding). If the visible symptom is "there's still a
bogus near-zero row in the table somewhere," that's almost certainly this -
a real, separate defect that needs either a one-off cleanup of existing
near-zero historical rows, or (better) a fix in
`proc_calculate_consumption_all_rates` so it stops writing these stub rows
at all - neither has been done yet.

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
