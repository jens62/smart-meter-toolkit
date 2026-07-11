# Read from Smart Meter Gateway by script

This folder's original script, `readSMGW_multipleContractsInRanges.py`, has
been superseded by `scripts/read_SMGW.py` (same `SmartMeterExporter` design,
with `--meter` now optional and better handling of gateways serving multiple
meters). The original is kept for reference at
`scripts/archive/readSMGW_multipleContractsInRanges.py`.

Usage example:
```bash
# Read out meter readings from the start of recording until now.
python3 scripts/read_SMGW.py --user myUser --password myPassword --meter 01005e318002.1emh001180xxxx.sm --out-path /home/<user>/smgw --from 0 --to now --log_level DEBUG
```
