# meter handling

This repository is about 
- reading meters, 
- storing the meter readings and 
- calculating the (monthly) consumption based on the meter readings.

The integration of a smart meter gateway (using PPC as an example) into an existing network and script-based access to the smart meter gateway is also considered.

All of this may be of particular interest to those who do not use home automation software such as openHAB or homeassitant.

The Python scripts in the scripts folder may help. The scripts can be copied, and apart from a few Python modules, no installation is required.

## Quickstart

### reading from Smart Meter
**Usage for the impatient**

To test the process in principle, create an Excel spreadsheet of the monthly consumption based on the meter readings of the last two hours provided by a smart meter gateway:

```bash
python read_SMGW.py \
    --user <user> \
    --password <top secret password> \
    --past 2h \
    --stdout-format csv \
    --out-format none \
| python meter_reading2consumption.py \
    --stdin \
    --time-col capture_time \
    --value-col value \
    --measurement-col logical_name \
    --divisor 10000 \
    --delimiter ";"
```

**Note:** *My smart meter serves several meters. I therefore have to specify the parameter `--meter` when calling `read_SMGW.py` and could not test and only guess for the implementation how the access is to be implemented if the smart meter gateway only serves one meter. I would be grateful if I could get feedback on whether the `read_SMGW.py` script works with just one meter and therefore without the `--meter` parameter.*


The above command consists of two parts:
1. reading from the smart meter gateway with output to stdout in csv format and transfer via pipe to 
2. calculate the monthly consumption with output to an Excel file.

The calculation of monthly consumption is implemented in a second script so that data sources other than the smart meter can be used.

**read all data from Smart Meter**
Generate an Excel sheet of monthly consumption based on all meter readings provided by the smart meter gateway.

Be patient ( ;-) ), this will take a while (in my case 20 minutes for a period of x days), the Smart Meter Gateway is not the fastest device.

```python
python read_SMGW.py \
    --user <user> \
    --password <top secret password> \
    --from 0 \
    --to now \
    --stdout-format csv \
    --out-format none \
| python meter_reading2consumption.py \
    --stdin \
    --time-col capture_time \
    --value-col value \
    --measurement-col logical_name \
    --divisor 10000 \
    --delimiter ";"
```

#### Usage
Use the usual `--help` or `--h` to be overwhelmed by the possibilities.

## Getting Started: The Full Guide

If you have meters for electricity, water, gas, etc., you may want to read them.
Consumption, trends and comparisons are certainly desirable.
If you know the data situation, you can take measures to save resources and measure the effects.

The first step is to gain technical access to the meter data.
The next step is to store the meter readings with a time stamp. The last step is to analyse the data.

As an option for accessing data from a digital electricity meter, I will describe a **PPC Smart Meter Gateway**.

For data storage I use **InfluxDB v2**, **InfluxDB v3** and **MySQL** (in the **MariaDB** variant).

There are some useful Python scripts for processing the data, such as calculating monthly consumption based on meter readings.

There is separate documentation for each of the different topics:
- [Using the PPC Smart Meter Gateway](docs/Using_the_PPC_Smart_Meter_Gateway.md)




