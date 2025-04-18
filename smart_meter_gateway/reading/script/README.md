# Read from Smart Meter Gateway by script

Usage example:
```bash
# Read out meter readings from the start of recording until now.
python3 readSMGW_multipleContractsInRanges.py --user myUser --password myPassword --meter --meter 01005e318002.1emh001180xxxx.sm --path /home/<useru>/smgw --from 0 --to now --log_level DEBUG
