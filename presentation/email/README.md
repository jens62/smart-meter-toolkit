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

## Optional: temperature columns

With `--temperature-model` and `--temperature-id` every section (hourly, daily, weekly, monthly, quarterly, yearly) gets **two narrow columns just
before "Verbrauch Gesamt"**, under **one shared header "Ø °C"** (`colspan=2`):

| Column | Content |
|---|---|
| value (left) | The time-weighted average temperature of the period (one decimal), from the roll-up tables of `../../persistence/mysql/temperature/`. The "Summe / Durchschnitt" row shows the time-weighted average over all rows of the section. |
| trend (right) | One dot per row, neighbouring dots joined by a thin line, like a Grafana time series turned by 90°: time runs downwards on the left (the newest row is on top, exactly like the table), the temperature runs to the right (warmer = further right). Dots and line are coloured by temperature. |

**The temperature is optional.** Not everybody who collects meter readings also collects
temperature, so the script works without it:

* Without `--temperature-model`/`--temperature-id` the report has no temperature columns (verified:
  all six queries return the same rows as before the temperature was added).
* With the flags, but with the six temperature tables missing, not readable by the report user,
  or the hourly table still empty, the script prints a warning (`Warnung: ... Bericht ohne
  Temperatur`) and builds the report without the temperature columns. It does not fail and does
  not send a "Keine Daten gefunden" mail.
* Nothing in `../../persistence/mysql/temperature/` is needed for the power-meter part of the
  toolkit.

### Flags

```
--temperature-model inFactory-TH     rtl_433 model of the sensor
--temperature-id 168                 rtl_433 id of the sensor (both flags together, or none)
--preview-file /tmp/report.html      write the HTML to this file and stop: nothing is published or emailed
```

The tables are found by name: `rtl_433_<model>_<id>_TEMPERATURE_<period>` (e.g.
`rtl_433_inFactory_TH_168_TEMPERATURE_daily`). The report user needs `SELECT` on them.

In the crontab, add the two flags at the end of the command (see `crontab.example`):

```
... --reading-head-description "$REPORT_READING_HEAD_DESCRIPTION" \
    --temperature-model inFactory-TH --temperature-id 168
```

### How the temperature is matched to a row

| Section | Row of the consumption table | Temperature row |
|---|---|---|
| hourly | `time_utc` (last reading of the hour) | `period_start_utc` = that UTC hour (unambiguous, also in the repeated hour in autumn) |
| daily | `time` (local, last reading of the day) | `period_start_local` = `DATE(time)` |
| weekly / monthly / quarterly / yearly | same | `period_start_local` = Monday / 1st of month / 1st of quarter / 1 Jan of that date |

Periods without a temperature row (everything before the first data in September 2026) show
`--`, no dot, and the line is interrupted there.

### Visualization: options and decision

The report is an HTML email, so what counts is what mail clients render.

| | **A: value column + trend column with SVG (chosen)** | B: dot positioned with CSS, no line | C: one column, value text on a coloured background | D: image per section (PNG) |
|---|---|---|---|---|
| Looks like | The sketch: number, then dots joined by a thin line, rotated Grafana plot. | Number plus a dot at the temperature's position; no connection. | Heat-map style: the cell background goes from blue to red. | One generated chart image for the whole column. |
| Pros | Exactly the requested look. Very narrow (about 100 px for both columns). Crisp at any zoom. Lines join across rows without gaps. Self-contained: nothing to host. | Works in more mail clients (CSS only). | Narrowest, works everywhere, no trend. | Works in every client that loads images. |
| Cons | Inline SVG is not shown by Gmail and Outlook (the `Ø °C` number is still there). Fine in Apple Mail, Thunderbird, and in the browser version ("Diese E-Mail im Browser anzeigen"). | No line, so no trend. Per-row positioning needs fragile `position:absolute`, which the bar column already uses. | No trend line. Colour alone is hard to read as a number. | Needs an image library on the Pi, files on the webserver, and remote images are blocked by default in many clients. Row heights must match the table exactly. |

Why not the alternatives: the report already relies on features Gmail/Outlook handle badly (the
animated bar column), and it has a browser copy for exactly that reason, so the best-looking
option that degrades to "number only" is acceptable. If you need Gmail/Outlook rendering later,
option D is the way and the rest of the script stays as it is.

#### Details of the trend column

* **Colour** follows the temperature on a **fixed scale** (the same temperature has the same colour
  in every section): blue below 5 °C, cyan around 11 °C, green around 17 °C, orange around 23 °C,
  red from 30 °C. Between two dots the line fades from one colour to the other. Edit
  `TEMP_COLOR_STOPS` for another scale. In October the values (10–19 °C) therefore run from cyan to
  green; blue and red appear in winter and summer.
* **Horizontal position** is scaled per section from its lowest to its highest value, so the trend
  is visible in every section.
* **Partial periods:** if less than 90 % of a period was covered by readings
  (`TEMP_PARTIAL_BELOW_PCT`), the value is grey italic and the dot is hollow. The tooltip shows the
  coverage. This hits the first week, month and quarter (the data starts on 27 Sep 2026).
* **Technique:** every row has its own SVG cell of exactly the row height (47 px). It draws its dot
  in the middle and half a line segment towards the neighbours above and below; the horizontal
  borders of this column are hidden, so the halves join into one line.

### Verification (temperature columns)

Run against a copy of the real report tables (MariaDB 10.11 container, `TZ=Europe/Berlin`):

* Without the temperature flags all six queries return the same rows as the report had before the
  temperature was added.
* With the flags: 24 of 24 hourly rows (yesterday) and 14 of 14 daily rows have a temperature;
  weekly 3 of 10, monthly 1, quarterly 1, yearly 0 (no data before 27 Sep 2026).
* Rendered in a browser: each row is 47 px high and the trend cell has exactly that height; the
  line is continuous across rows; the partial week shows a grey value and a hollow dot.
* On the Pi with the real database (`--preview-file`): 7 tables, 6 temperature headers and no
  errors; with a sensor that has no tables the report is byte-for-byte the report without flags.
  The real mail (including the BeautifulSoup re-parsing for the browser link) was sent and checked.

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
