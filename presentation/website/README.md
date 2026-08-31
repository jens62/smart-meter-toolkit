# Presentation: report archive website

`index.php` is the archive page linked from the mail report's "Alle Berichte
sind im Archiv gesammelt" line (`--public-base-url`/index.php in
`../email/`). It scans a `data/` subdirectory for `daily-email_*.html`
files, and renders a date-picker (flatpickr) letting a visitor load and view
any past report inline.

## Deployment

1. Copy `index.php` and `style.css` into the same directory
   `--local-publish-dir` (in `../email/`) writes its `data/` subdirectory
   under - i.e. `index.php`'s own directory must contain a `data/`
   subdirectory that is exactly `--local-publish-dir`.
2. Run `./install-flatpickr.sh` once from that directory to fetch the
   flatpickr date-picker library into `js/`/`css/` (vendored, gitignored -
   not committed to this repo). Re-run `./update-flatpickr.sh` later to pick
   up newer flatpickr releases.
3. No configuration needed - `index.php` only uses relative paths
   (`__DIR__`), so there's nothing to genericize/parameterize here.

## Notes

- `index.php` derives each report's *covered* date by subtracting one day
  from the report filename's date (`daily-email_<published-date>.html`
  covers the *previous* day) - matches `../email/`'s daily publish
  schedule (a report published the morning of day D covers day D-1).
