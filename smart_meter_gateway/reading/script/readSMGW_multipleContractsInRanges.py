#!/usr/bin/env python3

import os
import sys
import argparse
import subprocess
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
from pathlib import Path
import requests
from requests.auth import HTTPDigestAuth
import urllib3
import http.cookiejar
from bs4 import BeautifulSoup
import pandas as pd
import math

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class SmartMeterExporter:
    def __init__(self):
        self.parse_params()  # First parse parameters
        self.setup_logging()  # Then setup logging with the parsed args
        self.validate_params()
        self.setup_paths()

    def setup_logging(self):
        self.logger = logging.getLogger('SmartMeterExporter')
        
        # Set default log level if args isn't available yet
        log_level = logging.INFO
        if hasattr(self, 'args'):
            log_level = getattr(logging, self.args.log_level.upper(), logging.INFO)
            if self.args.verbose:
                log_level = logging.DEBUG
        
        self.logger.setLevel(log_level)
        
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)-15s %(name)-8s %(lineno)d %(levelname)s: %(message)s'
        ))
        self.logger.addHandler(handler)

    def parse_params(self):
        parser = argparse.ArgumentParser(
            description='Exports data from a Smartmeter Gateway using the han interface with automatic time range splitting.',
            epilog='''Examples:
 %(prog)s --user myUser --password myPassword --meter 01005e318002.1emh0011802881.sm --past 60
 %(prog)s --user myUser --password myPassword --meter 01005e318002.1emh0011802881.sm --from 0 --to now
 %(prog)s --user myUser --password myPassword --meter 01005e318002.1emh0011802881.sm --from 2024-01-01 --to 2024-01-31 --out json

Defaults:
 --max: 1000
 --interval: 15m
 --recording_started: "2023-01-01 00:00:00"
 --log_level: INFO''',
            formatter_class=argparse.RawDescriptionHelpFormatter
        )

        parser.add_argument('-v', '--verbose', action='store_true', help='Print script debug info')
        parser.add_argument('--host', default='192.168.1.200', help='IP address of Smartmeter Gateway (default: %(default)s)')
        parser.add_argument('--port', type=int, default=443, help='Port for Smartmeter Gateway (default: %(default)s)')
        parser.add_argument('--user', required=True, help='Smartmeter Gateway user')
        parser.add_argument('--password', required=True, help='Smartmeter Gateway password')
        parser.add_argument('--meter', required=True, help='Meter to use')
        parser.add_argument('--path', default=os.path.dirname(os.path.abspath(__file__)),
                          help='Path for the scripts output (default: current directory)')
        parser.add_argument('--from', dest='from_date', help='Export data from YYYY-MM-DD[ HH:MM:SS] or "0" for oldest available data')
        parser.add_argument('--to', dest='to_date', help='Export data to YYYY-MM-DD[ HH:MM:SS] or "now" for current time')
        parser.add_argument('--past', type=int, help='Export data in the time range of the past minutes')
        parser.add_argument('--max', type=int, default=1000,
                          help='Maximum number of intervals to retrieve in one request (default: %(default)s)')
        parser.add_argument('--interval', default='15m',
                          help='Time interval (e.g., 15m for 15 minutes). Units: s=seconds, m=minutes, h=hours, d=days, w=weeks, M=months, y=years (default: %(default)s)')
        parser.add_argument('--recording_started', default='2023-01-01 00:00:00',
                          help='Timestamp when recording started (used when --from=0) (default: %(default)s)')
        parser.add_argument('--out', choices=['csv', 'json', 'xml'], default='csv',
                          help='Format to print to stdout (default: %(default)s)')
        parser.add_argument('--log_level', default='INFO',
                          choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                          help='Logging level (default: %(default)s)')

        self.args = parser.parse_args()

        if self.args.verbose:
            self.args.log_level = 'DEBUG'

    def validate_params(self):
        now = datetime.now()
        self.timestamp_now = int(now.timestamp())

        # Handle special 'now' value for --to
        if self.args.to_date and self.args.to_date.lower() == 'now':
            self.to_date = now
        elif self.args.past:
            if self.args.past <= 0:
                self.logger.error("past needs to be positive integer gt 0")
                sys.exit(1)

            self.from_date = datetime.fromtimestamp(self.timestamp_now - (self.args.past * 60))
            self.to_date = now
        else:
            if not self.args.from_date or not self.args.to_date:
                self.logger.error("Either --past or both --from and --to must be specified")
                sys.exit(1)

            try:
                if self.args.to_date.lower() == 'now':
                    self.to_date = now
                else:
                    self.to_date = self.validate_date(self.args.to_date)
            except ValueError as e:
                self.logger.error(f"Invalid to date: {str(e)}")
                sys.exit(1)

        # Handle special '0' value for --from (now at correct indentation level)
        if self.args.from_date == '0':
            try:
                self.from_date = self.validate_date(self.args.recording_started)
            except ValueError as e:
                self.logger.error(f"Invalid recording_started format: {str(e)}")
                sys.exit(1)
        else:
            try:
                self.from_date = self.validate_date(self.args.from_date)
            except ValueError as e:
                self.logger.error(f"Invalid from date: {str(e)}")
                sys.exit(1)

        if self.from_date >= self.to_date:
            self.logger.error("from needs to be before to")
            sys.exit(1)

        if self.from_date > now:
            self.logger.error("from needs to be before now")
            sys.exit(1)

        # Validate interval
        try:
            self.interval_value, self.interval_unit = self.parse_interval(self.args.interval)
        except ValueError as e:
            self.logger.error(str(e))
            sys.exit(1)

        if self.args.max <= 0:
            self.logger.error("max must be greater than 0")
            sys.exit(1)

        # Validate interval
        try:
            self.interval_value, self.interval_unit = self.parse_interval(self.args.interval)
        except ValueError as e:
            self.logger.error(str(e))
            sys.exit(1)

        if self.args.max <= 0:
            self.logger.error("max must be greater than 0")
            sys.exit(1)

    def parse_interval(self, interval_str):
        unit = interval_str[-1]
        try:
            value = int(interval_str[:-1])
        except ValueError:
            raise ValueError(f"Invalid interval value: {interval_str}")
        
        if value <= 0:
            raise ValueError("Interval value must be positive")
        
        units = {
            's': 'seconds',
            'm': 'minutes',
            'h': 'hours',
            'd': 'days',
            'w': 'weeks',
            'M': 'months',
            'y': 'years'
        }
        
        if unit not in units:
            raise ValueError(f"Invalid interval unit: {unit}. Valid units are: s, m, h, d, w, M, y")
        
        return (value, unit)

    def calculate_time_ranges(self, start, end, interval_value, interval_unit, max_count):
        ranges = []
        
        # Calculate the total interval duration in days
        if interval_unit == 's':
            total_days = (interval_value * max_count) / 86400
        elif interval_unit == 'm':
            total_days = (interval_value * max_count) / 1440
        elif interval_unit == 'h':
            total_days = (interval_value * max_count) / 24
        elif interval_unit == 'd':
            total_days = interval_value * max_count
        elif interval_unit == 'w':
            total_days = interval_value * max_count * 7
        elif interval_unit == 'M':
            # Approximate months as 30 days
            total_days = interval_value * max_count * 30
        elif interval_unit == 'y':
            # Approximate years as 365 days
            total_days = interval_value * max_count * 365
        
        chunk_days = total_days
        whole_day_chunk = math.floor(chunk_days)
        if whole_day_chunk < 1:
            whole_day_chunk = 1
        
        current_end = end
        
        # First range - starts at midnight, ends at exact 'to' time
        first_range_start = (current_end - timedelta(days=chunk_days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        first_range_start = max(start, first_range_start)
        ranges.append((first_range_start, current_end))
        
        if first_range_start <= start:
            return ranges
        
        current_end = first_range_start
        
        # Middle ranges - aligned to whole day boundaries
        while current_end > start + timedelta(days=1):
            range_end = current_end.replace(hour=0, minute=0, second=0, microsecond=0)
            if range_end <= start:
                break
            
            range_start = (range_end - timedelta(days=whole_day_chunk)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            range_start = max(start, range_start)
            if range_start >= range_end:
                break
            
            ranges.append((range_start, range_end - timedelta(seconds=1)))
            current_end = range_start
        
        # Last range - starts at exact 'from' time, ends at midnight of next day
        if current_end > start:
            ranges.append((start, current_end - timedelta(seconds=1)))
        
        return ranges

    def validate_date(self, date_str):
        try:
            if len(date_str) == 10:
                return datetime.strptime(date_str, '%Y-%m-%d')
            elif len(date_str) == 19:
                return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
            else:
                raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
        except ValueError as e:
            raise ValueError(f"Invalid date: {date_str}. {str(e)}")

    def setup_paths(self):
        self.path = Path(self.args.path)
        if not self.path.is_dir():
            self.logger.error(f"Path {self.path} does not exist")
            sys.exit(1)

        if not os.access(self.path, os.W_OK):
            self.logger.error(f"Path {self.path} exists but is not writable")
            sys.exit(1)

        self.path = self.path / ''
        self.log_path = self.path / 'log'
        self.data_path = self.path / 'data'

        self.log_path.mkdir(exist_ok=True)
        self.data_path.mkdir(exist_ok=True)

        log_file = self.log_path / f"{Path(__file__).stem}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(file_handler)

    def check_dependencies(self):
        required_cmds = {
            'curl': ['curl', '--version'],
            'xmllint': ['xmllint', '--version'],
            'jq': ['jq', '--version'],
            'openssl': ['openssl', 'version']
        }
        
        missing = []
        
        for cmd, cmd_test in required_cmds.items():
            try:
                subprocess.run(cmd_test, 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE, 
                             check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                missing.append(cmd)
        
        try:
            import pandas as pd
        except ImportError:
            missing.append('pandas (Python package)')
        
        if missing:
            self.logger.error(f"Missing dependencies: {', '.join(missing)}")
            if 'pandas (Python package)' in missing:
                self.logger.error("Install pandas with: pip install pandas")
            sys.exit(1)

    def tcp_port_is_open(self, host, port):
        try:
            response = subprocess.run(
                ['curl', '-t', '', '--connect-timeout', '2', '-s', f'telnet://{host}:{port}'],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True
            )
            return response.returncode
        except subprocess.CalledProcessError as e:
            return e.returncode

    def extract_mid_and_tkn(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')

        meter_form = soup.find('form', {'id': 'form_meterform'})
        if not meter_form:
            raise ValueError("Could not find meter form in HTML")

        tkn_input = meter_form.find('input', {'name': 'tkn'})
        if not tkn_input or 'value' not in tkn_input.attrs:
            raise ValueError("Could not find TKN in form")
        tkn = tkn_input['value']

        meter_select = meter_form.find('select', {'name': 'mid'})
        if not meter_select:
            raise ValueError("Could not find meter select in form")

        meter_option = meter_select.find('option', string=lambda t: self.args.meter in str(t))
        if not meter_option or 'value' not in meter_option.attrs:
            raise ValueError(f"Could not find meter {self.args.meter} in select options")
        mid = meter_option['value']

        return mid, tkn

    def extract_xml_from_cms(self, cms_file, xml_file):
        try:
            result = subprocess.run(
                ['openssl', 'cms', '-verify', '-in', str(cms_file), '-inform', 'DER',
                 '-noverify', '-out', str(xml_file)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                self.logger.error(f"OpenSSL CMS verification failed: {result.stderr}")
                return False

            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to extract XML from CMS: {str(e)}")
            return False

    def get_meter_data_for_range(self, from_dt, to_dt):
        from_str = from_dt.strftime('%Y-%m-%d %H:%M:%S')
        to_str = to_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        self.logger.info(f"Processing range: {from_str} to {to_str}")
        
        # Prepare filenames
        escaped_from = from_str.replace(':', '_').replace(' ', '__')
        escaped_to = to_str.replace(':', '_').replace(' ', '__')
        result_basename = f"export_{escaped_from}---{escaped_to}"
        cms_file = self.data_path / f"{result_basename}.cms"
        xml_file = self.data_path / f"{result_basename}.xml"
        cookie_file = self.path / 'cookie-jar.txt'

        # Setup session with cookie handling
        session = requests.Session()
        session.auth = HTTPDigestAuth(self.args.user, self.args.password)
        session.verify = False
        session.headers.update({'User-Agent': 'curl/7.88.1'})

        # Load cookies if they exist
        if cookie_file.exists():
            try:
                cookie_jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
                cookie_jar.load()
                session.cookies = cookie_jar
            except Exception as e:
                self.logger.warning(f"Could not load cookies from {cookie_file}: {str(e)}")

        # First request to get MID and TKN
        try:
            response = session.post(
                f"https://{self.args.host}/cgi-bin/hanservice.cgi",
                data={'action': 'meterform'},
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            response.raise_for_status()

            # Save cookies
            cookie_jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
            for cookie in session.cookies:
                cookie_jar.set_cookie(cookie)
            cookie_jar.save(ignore_discard=True, ignore_expires=True)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get meter form: {str(e)}")
            return None

        # Parse MID and TKN from HTML using BeautifulSoup
        try:
            mid, tkn = self.extract_mid_and_tkn(response.text)
        except Exception as e:
            self.logger.error(f"Failed to parse MID or TKN from HTML: {str(e)}")
            return None

        # Get meter profile (with cookies)
        try:
            response = session.post(
                f"https://{self.args.host}/cgi-bin/hanservice.cgi",
                data={
                    'action': 'meterprofile',
                    'mid': mid,
                    'tkn': tkn
                }
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get meter profile: {str(e)}")
            return None

        # Get meter values form (with cookies)
        try:
            response = session.post(
                f"https://{self.args.host}/cgi-bin/hanservice.cgi",
                data={
                    'action': 'showMeterValuesForm',
                    'mid': mid,
                    'tkn': tkn
                }
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get meter values form: {str(e)}")
            return None

        # Export meter values (with cookies)
        try:
            response = session.post(
                f"https://{self.args.host}/cgi-bin/hanservice.cgi",
                data={
                    'action': 'exportMeterValues',
                    'mid': mid,
                    'tkn': tkn,
                    'from': from_str,
                    'to': to_str
                },
                stream=True
            )
            response.raise_for_status()

            # Save to file
            with open(cms_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to export meter values: {str(e)}")
            return None

        # Verify and extract XML from CMS file
        if not self.extract_xml_from_cms(cms_file, xml_file):
            self.logger.error("Failed to extract XML from CMS file")
            return None

        # Read the extracted XML
        try:
            with open(xml_file, 'r', encoding='utf-8') as f:
                xml_content = f.read()

            if not xml_content.strip():
                self.logger.error("Extracted XML file is empty")
                return None

        except IOError as e:
            self.logger.error(f"Failed to read XML file: {str(e)}")
            return None

        # Parse XML
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse XML: {str(e)}")
            return None

        # Create a list of dictionaries for all data entries
        data_entries = []

        # Register namespaces to make parsing cleaner
        namespaces = {
            'ns1': 'urn:k461-dke-de:profile_generic-1',
            'ns2': 'urn:k461-dke-de:extension-1'
        }

        logical_name = root.find(".//ns2:logical_name", namespaces=namespaces).text
        for entry in root.findall(".//ns1:entry_gateway_signed", namespaces=namespaces):
            try:
                capture_time = entry.find("ns2:capture_time", namespaces=namespaces).text
                long64_value = entry.find("ns2:value/ns2:long64", namespaces=namespaces).text
                scaler = entry.find("ns2:scaler", namespaces=namespaces).text
                unit = entry.find("ns2:unit", namespaces=namespaces).text
                status = entry.find("ns2:status/ns2:unsigned", namespaces=namespaces).text
                signature = entry.find("ns2:smgw_signature", namespaces=namespaces).text

                data_entries.append({
                    'logical_name': logical_name,
                    'capture_time': capture_time,
                    'long64_value': long64_value,
                    'scaler': scaler,
                    'unit': unit,
                    'status': status,
                    'signature': signature
                })
            except AttributeError as e:
                self.logger.warning(f"Missing expected field in XML entry: {str(e)}")
                continue

        return {
            'data_entries': data_entries,
            'xml_content': xml_content,
            'from_str': from_str,
            'to_str': to_str,
            'result_basename': result_basename
        }

    def get_meter_data(self):
        # Check connection
        conn = self.tcp_port_is_open(self.args.host, self.args.port)
        if conn != 49:
            self.logger.error(f"Could not connect to host {self.args.host} on port {self.args.port}")
            sys.exit(1)

        all_data_entries = []
        all_xml_content = []

        print(f"2. Using recording_started date: {self.from_date}")

        # Calculate time ranges
        time_ranges = self.calculate_time_ranges(
            self.from_date,
            self.to_date,
            self.interval_value,
            self.interval_unit,
            self.args.max
        )
        
        self.logger.info(f"Processing data in {len(time_ranges)} chunks")
        
        for range_start, range_end in time_ranges:
            result = self.get_meter_data_for_range(range_start, range_end)
            if result:
                all_data_entries.extend(result['data_entries'])
                all_xml_content.append(result['xml_content'])

        if not all_data_entries:
            self.logger.error("No data was retrieved")
            sys.exit(1)

        # Create DataFrame from all data
        df = pd.DataFrame(all_data_entries)

        # Generate combined output files
        escaped_from = self.from_date.strftime('%Y-%m-%d %H:%M:%S').replace(':', '_').replace(' ', '__')
        escaped_to = self.to_date.strftime('%Y-%m-%d %H:%M:%S').replace(':', '_').replace(' ', '__')
        result_basename = f"export_{escaped_from}---{escaped_to}"

        # CSV output
        csv_file = self.data_path / f"{result_basename}.csv"
        df.to_csv(csv_file, sep=';', index=False)
        csv_content = df.to_csv(sep=';', index=False)

        # JSON output
        json_data = {
            'id': self.args.meter,
            'count': len(all_data_entries),
            'simple_data': all_data_entries
        }
        json_content = json.dumps(json_data, indent=2)
        json_file = self.data_path / f"{result_basename}.json"
        with open(json_file, 'w') as f:
            f.write(json_content)

        # XML output (just concatenate all XML chunks)
        xml_content = "\n".join(all_xml_content)
        xml_file = self.data_path / f"{result_basename}.xml"
        with open(xml_file, 'w') as f:
            f.write(xml_content)

        # Output requested format
        if self.args.out == 'csv':
            print(csv_content)
        elif self.args.out == 'json':
            print(json_content)
        elif self.args.out == 'xml':
            print(xml_content)

    def run(self):
        self.check_dependencies()
        self.get_meter_data()

if __name__ == '__main__':
    exporter = SmartMeterExporter()
    exporter.run()