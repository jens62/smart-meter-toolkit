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
from glob import glob

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class SmartMeterExporter:
    def __init__(self):
        self.parse_params()
        self.setup_logging()
        self.validate_params()
        self.setup_paths()

    def setup_logging(self):
        self.logger = logging.getLogger('SmartMeterExporter')
        log_level = getattr(logging, self.args.log_level.upper(), logging.INFO)
        if self.args.verbose:
            log_level = logging.DEBUG
        
        self.logger.setLevel(log_level)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            '%(asctime)-15s %(name)-8s %(lineno)d %(levelname)s: %(message)s'
        ))
        self.logger.addHandler(handler)

    def parse_params(self):
        examples = f'''\
Examples:
 %(prog)s --user myUser --password myPassword --meter "1 ABCxx xxxx xxxx" --past 60d
 %(prog)s --user myUser --password myPassword --meter "1 ABCxx xxxx xxxx" --from 0 --to now
 %(prog)s --user myUser --password myPassword --meter "1 ABCxx xxxx xxxx" --from 2024-01-01 --to 2024-01-31 --out json
 %(prog)s --input-format cms --input-file /path/to/file.cms
'''
            
        parser = argparse.ArgumentParser(
            description='Exports data from a Smartmeter Gateway using the han interface with automatic time range splitting.',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=examples,
            add_help=False
        )

        # Input parameters
        input_group = parser.add_argument_group('Input parameters')
        input_group.add_argument('--input-format', choices=['none', 'cms', 'xml', 'csv'], default='none',
                               help='Input format (default: %(default)s)')
        input_group.add_argument('--input-file', help='Single input file to process')
        input_group.add_argument('--input-dir', help='Directory containing input files')

        # Connection parameters
        conn_group = parser.add_argument_group('Connection parameters (required when --input-format=none)')
        conn_group.add_argument('--host', default='192.168.1.200', help='Smartmeter Gateway IP (default: %(default)s)')
        conn_group.add_argument('--port', type=int, default=443, help='Port (default: %(default)s)')
        conn_group.add_argument('--user', help='Gateway user')
        conn_group.add_argument('--password', help='Gateway password')
        conn_group.add_argument('--meter', help='Meter identifier')

        # Time range parameters
        time_group = parser.add_argument_group('Time range parameters')
        time_group.add_argument('--from', dest='from_date', 
                              help='Start time (YYYY-MM-DD[ HH:MM:SS] or "0" for earliest)')
        time_group.add_argument('--to', dest='to_date', 
                              help='End time (YYYY-MM-DD[ HH:MM:SS] or "now")')
        time_group.add_argument('--past', help='Time range (e.g., 1h for 1 hour)')
        time_group.add_argument('--recording_started', default='2023-01-01 00:00:00',
                              help='Earliest recording time (default: %(default)s)')

        # Output parameters
        output_group = parser.add_argument_group('Output parameters')
        output_group.add_argument('--out-path', default=os.getcwd(),
                                help='Output directory (default: current)')
        output_group.add_argument('--out-format', nargs='+', 
                                choices=['none', 'cms', 'xml', 'csv', 'json'], 
                                default=['cms', 'xml', 'csv', 'json'],
                                help='Output file formats (default: %(default)s)')
        output_group.add_argument('--stdout-format', choices=['none', 'cms', 'xml', 'csv', 'json'], 
                                default='none', help='Stdout format (default: %(default)s)')

        # Other parameters
        other_group = parser.add_argument_group('Other parameters')
        other_group.add_argument('--max', type=int, default=1000,
                               help='Max intervals per request (default: %(default)s)')
        other_group.add_argument('--interval', default='15m',
                               help='Interval (e.g., 15m) (default: %(default)s)')
        other_group.add_argument('--persist-intermediate-xml', action='store_true',
                               help='Persist intermediate XML files when processing CMS files (default: False)')
        other_group.add_argument('--log_level', default='INFO',
                               choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                               help='Log level (default: %(default)s)')
        other_group.add_argument('-v', '--verbose', action='store_true',
                               help='Verbose output')
        other_group.add_argument('-h', '--help', action='store_true',
                               help='Show this help message')

        # Parse arguments
        self.args = parser.parse_args()

        # Show help if no arguments or --help specified
        if len(sys.argv) == 1 or self.args.help:
            parser.print_help(sys.stderr)
            sys.exit(1)

    def validate_params(self):
        if self.args.input_format == 'none':
            # Validate required connection parameters
            if not all([self.args.user, self.args.password]):
                self.logger.error("--user, --password, and --meter are required when --input-format is none")
                sys.exit(1)

            now = datetime.now()
            if self.args.past:
                try:
                    past_value, past_unit = self.parse_interval(self.args.past)
                    seconds = self.convert_to_seconds(past_value, past_unit)
                    self.from_date = datetime.fromtimestamp(now.timestamp() - seconds)
                    self.to_date = now
                except ValueError as e:
                    self.logger.error(f"Invalid --past value: {str(e)}")
                    sys.exit(1)
            else:
                if not self.args.from_date or not self.args.to_date:
                    self.logger.error("Either --past or both --from and --to must be specified")
                    sys.exit(1)

                try:
                    self.from_date = self.parse_date(self.args.from_date, is_from=True)
                    self.to_date = self.parse_date(self.args.to_date, is_from=False)
                except ValueError as e:
                    self.logger.error(str(e))
                    sys.exit(1)

                if self.from_date >= self.to_date:
                    self.logger.error("Start time must be before end time")
                    sys.exit(1)

            # Validate interval
            try:
                self.interval_value, self.interval_unit = self.parse_interval(self.args.interval)
            except ValueError as e:
                self.logger.error(str(e))
                sys.exit(1)

            if self.args.max <= 0:
                self.logger.error("--max must be positive")
                sys.exit(1)
        else:
            # Validate input file/directory
            if not self.args.input_file and not self.args.input_dir:
                self.logger.error("Either --input-file or --input-dir must be specified when --input-format is not none")
                sys.exit(1)
            
            if self.args.input_file and self.args.input_dir:
                self.logger.error("Only one of --input-file or --input-dir can be specified")
                sys.exit(1)

            # Validate output formats based on input format
            if 'cms' in self.args.out_format and self.args.input_format != 'none':
                self.logger.error("Cannot output CMS format when input is not from gateway")
                sys.exit(1)
            
            if self.args.stdout_format == 'cms' and self.args.input_format != 'none':
                self.logger.error("Cannot output CMS format to stdout when input is not from gateway")
                sys.exit(1)

    def parse_interval(self, interval_str):
        match = re.match(r'^(\d+)([smhdwMy])$', interval_str)
        if not match:
            raise ValueError(f"Invalid interval format: {interval_str}")
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if value <= 0:
            raise ValueError("Interval value must be positive")
        
        valid_units = ['s', 'm', 'h', 'd', 'w', 'M', 'y']
        if unit not in valid_units:
            raise ValueError(f"Invalid unit. Valid units: {', '.join(valid_units)}")
        
        return (value, unit)

    def convert_to_seconds(self, value, unit):
        conversions = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
            'M': 2592000,  # 30 days
            'y': 31536000  # 365 days
        }
        return value * conversions[unit]

    def parse_date(self, date_str, is_from):
        if is_from and date_str == '0':
            try:
                return datetime.strptime(self.args.recording_started, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise ValueError("Invalid --recording_started format")
        
        if not is_from and date_str.lower() == 'now':
            return datetime.now()

        try:
            if len(date_str) == 10:
                return datetime.strptime(date_str, '%Y-%m-%d')
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError(f"Invalid date format: {date_str}")

    def setup_paths(self):
        self.path = Path(self.args.out_path)
        if not self.path.is_dir():
            self.logger.error(f"Output path does not exist: {self.path}")
            sys.exit(1)

        self.data_path = self.path / 'data'
        self.data_path.mkdir(exist_ok=True)

    def check_dependencies(self):
        required_cmds = {
            'curl': ['curl', '--version'],
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
        
        if missing:
            self.logger.error(f"Missing dependencies: {', '.join(missing)}")
            sys.exit(1)

    def tcp_port_is_open(self, host, port):
        try:
            response = subprocess.run(
                ['curl', '-t', '', '--connect-timeout', '2', '-s', f'telnet://{host}:{port}'],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True
            )
            return response.returncode == 49  # 49 means connection successful
        except subprocess.CalledProcessError:
            return False

    def extract_mid_and_tkn(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')

        meter_form = soup.find('form', {'id': 'form_meterform'})
        if not meter_form:
            raise ValueError("Could not find meter form in HTML")

        tkn_input = meter_form.find('input', {'name': 'tkn'})
        if not tkn_input or 'value' not in tkn_input.attrs:
            raise ValueError("Could not find TKN in form")
        tkn = tkn_input['value']

        # In case the smart meter recorded data for diiferent meters, it is necessary to select a ceratin meter
        # the mid will change depending on the selected meter 
        meter_select = meter_form.find('select', {'name': 'mid'})
        if meter_select:
            options = meter_select.find_all('option')
            # Extract values and text
            # option_data = [(option["value"], option.text) for option in options]
            option_text = [option.text.split(".")[1] for option in options]
            #self.logger.debug("meter option:" + str(option_text) + " checking against: " + str(self.args.meter.replace(" ", "").lower()))

            if not self.args.meter:
                msg = "--meter is required, because the smart meter recorded for multiple meters. Please select one of the following as argument for --meter: \n\t"
                msg += ", ".join(option_text)
                # self.logger.error(msg)
                # sys.exit(1)
                raise ValueError(msg)
            # else:
            #     self.logger.debug("meter option:" + str(option_text) + " checking against: " + str(self.args.meter.replace(" ", "").lower()))

            meter_option = meter_select.find('option', string=lambda t: self.args.meter.replace(" ", "").lower() in str(t))
            if not meter_option or 'value' not in meter_option.attrs:
                self.logger.error("meter option:" + str(option_text) + " checking against: " + str(self.args.meter.replace(" ", "").lower()))
                raise ValueError(f"Could not find meter {self.args.meter} in select options")
            mid = meter_option['value']

        return mid, tkn



    # Your file appears to be a **CMS (Cryptographic Message Syntax) file** that contains **signed XML data**. The binary prologue and postlogue suggest that the XML content is encapsulated within a cryptographic envelope, likely for authentication or integrity verification purposes. This format is commonly used in **smart meter gateways** to ensure secure data transmission.
    #
    # To extract the XML data from the file, you can use **OpenSSL** or **xmlstarlet**, depending on whether you need to **decode** the cryptographic envelope first:
    # 1. **OpenSSL**: If the file is signed or encrypted, you may need to use OpenSSL to extract the XML content:
    #    ```bash
    #    openssl cms -verify -in yourfile.cms -noverify -out extracted.xml
    #    ```
    #    This command attempts to verify and extract the XML content.
    #
    # 2. **xmlstarlet**: If the XML is already accessible within the file, you can use `xmlstarlet` to parse and manipulate it:
    #    ```bash
    #    xmlstarlet sel -t -m "//ns1:object" -v "." extracted.xml
    #    ```
    #    This extracts the relevant XML data.
    #
    # Would you like help verifying whether the file is encrypted or signed?
    #
    # *With openssl I get: Error reading SMIME Content Info
    # 40CC3F0302000000:error:068000D1:asn1 encoding routines:SMIME_read_ASN1_ex:no content type:crypto/asn1/asn_mime.c*
    #
    # It looks like OpenSSL is struggling to recognize the content type of your file, which suggests that it might not be a standard S/MIME or CMS format. This error often occurs when the file is missing expected headers or is encoded in an unexpected way.
    #
    # Here are a few things you can try:
    # 1. **Check the file format**: If the file is in DER format instead of PEM, try specifying `-inform DER`:
    #    ```bash
    #    openssl cms -verify -in yourfile.cms -inform DER -noverify -out extracted.xml
    #    ```
    # 2. **Use a hex editor**: Open the file in a hex editor (`xxd` or `hexdump`) to inspect its structure and confirm whether it contains recognizable CMS or PKCS#7 headers.
    # 3. **Try a different tool**: If OpenSSL isn't working, you might need a specialized tool like `dumpasn1` to analyze the ASN.1 structure.
    #
    # You can also check out [this discussion](https://stackoverflow.com/questions/28518775/trying-to-decrypt-s-mime-file-using-openssl) for similar issues and potential solutions.
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
        
    def get_namespaces(self, root):
        """Extracts all namespaces dynamically from the parsed XML root."""
        namespaces = {}

        # Traverse elements in the parsed tree
        for elem in root.iter():
            if elem.tag.startswith("{"):
                uri, tag = elem.tag[1:].split("}", 1)
                if uri not in namespaces.values():
                    prefix = f"ns{len(namespaces) + 1}"  # Generate dynamic prefixes like ns1, ns2
                    namespaces[prefix] = uri

        return namespaces

    def parse_xml_entry(self, entry, namespaces, logical_name):
        """Parse a single XML entry into a dictionary."""
        try:
            return {
                'logical_name': logical_name,
                'capture_time': entry.find("ns2:capture_time", namespaces=namespaces).text,
                'value': entry.find("ns2:value/ns2:*", namespaces=namespaces).text,
                'scaler': entry.find("ns2:scaler", namespaces=namespaces).text,
                'unit': entry.find("ns2:unit", namespaces=namespaces).text,
                'status': entry.find("ns2:status/ns2:unsigned", namespaces=namespaces).text,
                'signature': entry.find("ns2:smgw_signature", namespaces=namespaces).text
            }
        except AttributeError as e:
            self.logger.warning(f"Missing expected field in XML entry: {str(e)}")
            return None

    def process_xml_content(self, xml_content, source=None):
        """Process XML content and return parsed data entries."""
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            self.logger.error(f"XML parse error{'' if not source else ' in ' + source}: {str(e)}")
            return None

        namespaces = self.get_namespaces(root)
        data_entries = []

        try:
            logical_name = root.find(".//ns2:logical_name", namespaces=namespaces).text
            for entry in root.findall(".//ns1:entry_gateway_signed", namespaces=namespaces):
                parsed_entry = self.parse_xml_entry(entry, namespaces, logical_name)
                if parsed_entry:
                    data_entries.append(parsed_entry)
        except Exception as e:
            self.logger.error(f"XML processing error{'' if not source else ' in ' + source}: {str(e)}")
            return None

        return data_entries

    def get_meter_data_for_range(self, from_dt, to_dt):
        """Fetch meter data for a specific time range from the gateway.
        
        Args:
            from_dt (datetime): Start datetime of the range
            to_dt (datetime): End datetime of the range
            
        Returns:
            dict: Dictionary containing:
                - data_entries: List of parsed data entries
                - xml_content: Raw XML content
                - from_str: Formatted from datetime string
                - to_str: Formatted to datetime string
                - result_basename: Base filename for outputs
                - cms_file: Path to the CMS file
                Or None if failed
        """
        from_str = from_dt.strftime('%Y-%m-%d %H:%M:%S')
        to_str = to_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        self.logger.info(f"Processing range: {from_str} to {to_str}")
        
        # Prepare filenames
        escaped_from = from_str.replace(':', '_').replace(' ', '__')
        escaped_to = to_str.replace(':', '_').replace(' ', '__')
        result_basename = f"export_{escaped_from}---{escaped_to}"
        cms_file = self.data_path / f"{result_basename}.cms"
        
        # Only create XML file if explicitly requested or needed for output
        if self.args.persist_intermediate_xml or 'xml' in self.args.out_format or self.args.stdout_format == 'xml':
            xml_file = self.data_path / f"{result_basename}.xml"
        else:
            xml_file = None

        # Setup session with cookie handling
        session = requests.Session()
        session.auth = HTTPDigestAuth(self.args.user, self.args.password)
        session.verify = False
        session.headers.update({'User-Agent': 'curl/7.88.1'})

        # Load cookies if they exist
        cookie_file = self.path / 'cookie-jar.txt'
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
        if xml_file:  # Only write to file if requested
            if not self.extract_xml_from_cms(cms_file, xml_file):
                self.logger.error("Failed to extract XML from CMS file")
                return None
            
            try:
                with open(xml_file, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
            except IOError as e:
                self.logger.error(f"Failed to read XML file: {str(e)}")
                return None
        else:
            # Extract directly to memory
            result = subprocess.run(
                ['openssl', 'cms', '-verify', '-in', str(cms_file), '-inform', 'DER',
                '-noverify'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                self.logger.error(f"OpenSSL CMS verification failed: {result.stderr}")
                return None
            xml_content = result.stdout

        if not xml_content.strip():
            self.logger.error("Extracted XML content is empty")
            return None

        # Parse XML
        data_entries = self.process_xml_content(xml_content)
        if not data_entries:
            return None

        return {
            'data_entries': data_entries,
            'xml_content': xml_content,
            'from_str': from_str,
            'to_str': to_str,
            'result_basename': result_basename,
            'cms_file': cms_file
        }

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

    def get_meter_data(self):
        # Check connection
        if not self.tcp_port_is_open(self.args.host, self.args.port):
            self.logger.error(f"Could not connect to host {self.args.host} on port {self.args.port}")
            sys.exit(1)

        all_data_entries = []
        all_xml_content = []
        cms_files = []

        print(f"Using recording_started date: {self.from_date}", file=sys.stderr)

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
                cms_files.append(result['cms_file'])

        if not all_data_entries:
            self.logger.error("No data was retrieved")
            sys.exit(1)

        return self.generate_outputs(all_data_entries, all_xml_content, cms_files)

    def find_input_files(self):
        """Find all input files based on input format and input file/directory"""
        if self.args.input_file:
            return [Path(self.args.input_file)]
        
        if self.args.input_dir:
            extension = self.args.input_format
            if extension == 'cms':
                pattern = '**/*.cms'
            elif extension == 'xml':
                pattern = '**/*.xml'
            elif extension == 'csv':
                pattern = '**/*.csv'
            
            input_dir = Path(self.args.input_dir)
            return list(input_dir.glob(pattern))
        
        return []

    def process_cms_file(self, cms_file_path):
        """Process a single CMS file and return the extracted data"""
        if self.args.persist_intermediate_xml:
            xml_file_path = cms_file_path.with_suffix('.xml')
        else:
            xml_file_path = None
        
        try:
            # Extract XML from CMS
            if self.args.persist_intermediate_xml:
                if not self.extract_xml_from_cms(cms_file_path, xml_file_path):
                    self.logger.error(f"Failed to extract XML from CMS file: {cms_file_path}")
                    return None
                
                with open(xml_file_path, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
            else:
                # Extract directly to memory without persisting
                result = subprocess.run(
                    ['openssl', 'cms', '-verify', '-in', str(cms_file_path), '-inform', 'DER',
                     '-noverify'],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    self.logger.error(f"OpenSSL CMS verification failed: {result.stderr}")
                    return None
                xml_content = result.stdout

            if not xml_content.strip():
                self.logger.error("Extracted XML content is empty")
                return None

            data_entries = self.process_xml_content(xml_content, str(cms_file_path))
            if not data_entries:
                return None

            return {
                'data_entries': data_entries,
                'xml_content': xml_content,
                'input_file': cms_file_path
            }

        except Exception as e:
            self.logger.error(f"Failed to process CMS file: {str(e)}")
            return None
        
    def process_xml_file(self, xml_file_path):
        """Process a single XML file and return the extracted data"""
        try:
            with open(xml_file_path, 'r', encoding='utf-8') as f:
                xml_content = f.read()

            if not xml_content.strip():
                self.logger.error("XML file is empty")
                return None

            data_entries = self.process_xml_content(xml_content, str(xml_file_path))
            if not data_entries:
                return None

            return {
                'data_entries': data_entries,
                'xml_content': xml_content,
                'input_file': xml_file_path
            }

        except IOError as e:
            self.logger.error(f"Failed to read XML file: {str(e)}")
            return None

    def process_csv_file(self, csv_file_path):
        """Process a single CSV file and return the data"""
        try:
            df = pd.read_csv(csv_file_path, sep=';')
            return {
                'data_entries': df.to_dict('records'),
                'xml_content': None,
                'input_file': csv_file_path
            }
        except Exception as e:
            self.logger.error(f"Failed to read CSV file: {str(e)}")
            return None

    def process_input_files(self):
        input_files = self.find_input_files()
        if not input_files:
            self.logger.error("No input files found")
            return None

        all_data_entries = []
        all_xml_content = []
        processed_files = []

        for input_file in input_files:
            self.logger.info(f"Processing {input_file}")
            result = None
            
            if self.args.input_format == 'cms':
                result = self.process_cms_file(input_file)
            elif self.args.input_format == 'xml':
                result = self.process_xml_file(input_file)
            elif self.args.input_format == 'csv':
                result = self.process_csv_file(input_file)

            if result:
                all_data_entries.extend(result.get('data_entries', []))
                if 'xml_content' in result and result['xml_content']:
                    all_xml_content.append(result['xml_content'])
                processed_files.append(input_file)

        if not all_data_entries:
            self.logger.error("No valid data found in input files")
            return None

        return self.generate_outputs(all_data_entries, all_xml_content, processed_files)

    def generate_outputs(self, data_entries, xml_contents=None, source_files=None):
        """Generate requested output formats with proper error handling"""
        try:
            if not data_entries:
                self.logger.error("No data entries to output")
                return None

            self.logger.debug(f"Generating outputs for {len(data_entries)} entries")
            
            outputs = {}
            df = pd.DataFrame(data_entries).drop_duplicates()

            # Generate output filename base
            if source_files:
                src_str = '_'.join([f.stem for f in source_files[:3]])
                if len(source_files) > 3:
                    src_str += f"_+{len(source_files)-3}"
                out_base = f"export_from_{self.args.input_format}-files_{src_str}"
            else:
                from_str = self.from_date.strftime('%Y-%m-%d_%H-%M-%S')
                to_str = self.to_date.strftime('%Y-%m-%d_%H-%M-%S')
                out_base = f"export_{from_str}---{to_str}"

            # Generate requested output formats
            if 'csv' in self.args.out_format or self.args.stdout_format == 'csv':
                try:
                    csv_content = df.to_csv(sep=';', index=False)
                    if 'csv' in self.args.out_format:
                        csv_file = self.data_path / f"{out_base}.csv"
                        with open(csv_file, 'w') as f:
                            f.write(csv_content)
                        self.logger.debug(f"Saved CSV to {csv_file}")
                    outputs['csv_content'] = csv_content
                except Exception as e:
                    self.logger.error(f"CSV generation failed: {str(e)}")
                    if self.args.stdout_format == 'csv':
                        return None

            if 'json' in self.args.out_format or self.args.stdout_format == 'json':
                try:
                    json_data = {
                        'id': getattr(self.args, 'meter', None),
                        'count': len(data_entries),
                        'simple_data': data_entries
                    }
                    json_content = json.dumps(json_data, indent=2)
                    if 'json' in self.args.out_format:
                        json_file = self.data_path / f"{out_base}.json"
                        with open(json_file, 'w') as f:
                            f.write(json_content)
                        self.logger.debug(f"Saved JSON to {json_file}")
                    outputs['json_content'] = json_content
                except Exception as e:
                    self.logger.error(f"JSON generation failed: {str(e)}")
                    if self.args.stdout_format == 'json':
                        return None

            if 'xml' in self.args.out_format or self.args.stdout_format == 'xml':
                if not xml_contents:
                    self.logger.error("No XML content available for output")
                    if self.args.stdout_format == 'xml':
                        return None
                else:
                    try:
                        xml_content = "\n".join(xml_contents)
                        if 'xml' in self.args.out_format:
                            xml_file = self.data_path / f"{out_base}.xml"
                            with open(xml_file, 'w') as f:
                                f.write(xml_content)
                            self.logger.debug(f"Saved XML to {xml_file}")
                        outputs['xml_content'] = xml_content
                    except Exception as e:
                        self.logger.error(f"XML generation failed: {str(e)}")
                        if self.args.stdout_format == 'xml':
                            return None

            if 'cms' in self.args.out_format and source_files and all(f.suffix == '.cms' for f in source_files):
                try:
                    # For CMS output, we can copy the original CMS files
                    for cms_file in source_files:
                        dest_file = self.data_path / f"{out_base}_{cms_file.name}"
                        with open(cms_file, 'rb') as src, open(dest_file, 'wb') as dest:
                            dest.write(src.read())
                        self.logger.debug(f"Copied CMS file to {dest_file}")
                except Exception as e:
                    self.logger.error(f"CMS file copy failed: {str(e)}")

            return outputs

        except Exception as e:
            self.logger.error(f"Output generation failed: {str(e)}")
            return None

    def run(self):
        """Main execution method with improved error handling"""
        self.check_dependencies()
        
        try:
            if self.args.input_format == 'none':
                result = self.get_meter_data()
            else:
                result = self.process_input_files()

            if not result:
                self.logger.error("Processing failed - no results generated")
                sys.exit(1)

            # Output to stdout if requested
            if self.args.stdout_format != 'none':
                output_key = f"{self.args.stdout_format}_content"
                if output_key in result and result[output_key]:
                    print(result[output_key])
                else:
                    self.logger.error(f"Requested output format not available: {self.args.stdout_format}")
                    sys.exit(1)

        except Exception as e:
            self.logger.error(f"Unexpected error: {str(e)}")
            sys.exit(1)

if __name__ == '__main__':
    exporter = SmartMeterExporter()
    exporter.run()