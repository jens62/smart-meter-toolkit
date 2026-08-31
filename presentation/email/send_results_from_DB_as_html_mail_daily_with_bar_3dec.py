#!/usr/bin/env python3
"""Build an HTML consumption report from the persistence/mysql rollup tables
(hourly/daily/weekly/monthly/quarterly/yearly), publish it to a local
directory and a remote webserver (via SSH), and email it.

All deployment-specific values (DB credentials, recipient/sender addresses,
the public report URL, publish paths, the remote SSH host) are passed as
CLI flags - see three-phase-meter-mail.env.example for how crontab.example
supplies them via a sourced env file. Nothing here has a real-looking
default: a missing required value fails immediately at argument-parsing
time instead of silently falling back to something wrong.
"""
import argparse
import os

import mysql.connector
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from bs4 import BeautifulSoup

import plumbum
from datetime import date


def german_to_float(number_str: str) -> float:
    # Entferne Tausendertrennzeichen und ersetze Dezimalkomma
    cleaned = number_str.replace('.', '').replace(',', '.')
    return float(cleaned)


def hex_to_rgb(hex_color):
    # Konvertiert Hex-Farbcode zu RGB-Tuple
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def interpolate_color(color1, color2, fraction):
    # Interpoliert zwischen zwei Farben
    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)
    return (
        int(rgb1[0] + (rgb2[0] - rgb1[0]) * fraction),
        int(rgb1[1] + (rgb2[1] - rgb1[1]) * fraction),
        int(rgb1[2] + (rgb2[2] - rgb1[2]) * fraction)
    )


def rgb_to_hex(rgb):
    # Konvertiert RGB-Tuple zu Hex
    return '#%02x%02x%02x' % rgb


def get_color(percentage: float) -> str:
    # Bestimmt die Endfarbe basierend auf der Balkenlänge (0-100%)
    colors = [
        (0.0, '#4CAF50'),    # Grün
        (0.5, '#FFEB3B'),    # Gelb
        (0.75, '#FF9800'),   # Orange
        (1.0, '#F44336')     # Rot
    ]
    for i in range(len(colors)-1):
        if colors[i][0] <= percentage < colors[i+1][0]:
            break
    else:
        return colors[-1][1]

    # Farbinterpolation zwischen den Stops
    start_percent, start_color = colors[i]
    end_percent, end_color = colors[i+1]
    fraction = (percentage - start_percent) / (end_percent - start_percent)
    return f"color-mix(in srgb, {start_color} {100 - fraction*100}%, {end_color} {fraction*100}%)"


# Funktion, um Datenbankabfrage auszuführen
def query_database(db_config, query, col_idx_for_max=-1):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(query)

        # Fetch column names
        column_names = [desc[0] for desc in cursor.description]

        # Fetch data
        results = cursor.fetchall()
        rowcount = cursor.rowcount
        cursor.close()
        conn.close()

        if col_idx_for_max >= 0 and rowcount > 1:
            # Find maximum consumption for scaling
            max_consumption = max(german_to_float(row[col_idx_for_max]) for row in results[:-1])
        else:
            max_consumption = 0

        return results, column_names, max_consumption

    except mysql.connector.Error as err:
        print(f"Fehler: {err}")
        return [], [], 0


def get_meter_number(db_config, device_id):
    query = f"""
        WITH meter_number AS (
            SELECT SML_96_1_0
            FROM
                tasmota_{device_id}_SENSOR
            ORDER BY
                TIME DESC
            LIMIT
                1
        )
        SELECT
            -- Erstes Byte: eine Ziffer (Hex to Decimal)
            CONV(SUBSTRING(SML_96_1_0, 3, 2), 16, 10) AS Spartenkennung,

            -- Nächste drei Bytes: alphanumerisch (Hex to ASCII)
            CONVERT(UNHEX(SUBSTRING(SML_96_1_0, 5, 6)) USING utf8) AS Herstellerkennzeichnung,

            -- Dann ein Byte mit einer Ziffer (Hex to Decimal)
            LPAD(CONV(SUBSTRING(SML_96_1_0, 11, 2), 16, 10),2,'0') AS Fabrikationsblock,

            -- Schließlich acht Byte mit einer Zahl (Hex to Decimal)
                CONCAT(
                SUBSTRING(
                    LPAD(
                        CONV(SUBSTRING(SML_96_1_0, 13), 16, 10),
                        8,
                        '0'
                    ),
                1, 4
                ),
                ' ',
                SUBSTRING(
                    LPAD(
                        CONV(SUBSTRING(SML_96_1_0, 13), 16, 10),
                        8,
                        '0'
                    ),
                5, 4
                )
            )  AS Fabrikationsnummer
        FROM
            meter_number;
    """

    data, column_names, max_consumption = query_database(db_config, query=query)
    return data, column_names


def get_html_for_meter_number(db_config, device_id):
    data, column_names = get_meter_number(db_config, device_id)
    if not data:
        return "", "<p>Keine Daten gefunden.</p>"

    # 1 EBZ01 0257 2678
    meter_number = ""

    # Start HTML table
    html = "<table style=\"width: auto;\">"
    # Generate table header dynamically
    html += "<tr>"
    for column in column_names:
        html += f"<th>{column}</th>"
    html += "</tr>"
    # Populate table rows with data
    for row in data:
        html += "<tr>"

        idx = 0
        for cell in row:
            html += f"<td style=\"text-align: right;\">{cell}</td>"
            if idx == 0:
                meter_number += f"{cell}"
            elif idx == 1:
                meter_number += f" {cell}"
            elif idx == 2:
                meter_number += f"{cell}"
            elif idx == 3:
                meter_number += f" {cell}"
            else:
                print("Invalid option")

            idx += 1
        html += "</tr>"
    # Close HTML table
    html += "</table>"

    print(f"meter_number: {meter_number}")
    return meter_number, html


# Funktion, um HTML aus den Daten zu generieren
def generate_html_begin():
    # Start HTML
    html_begin = """
    <!DOCTYPE html>
    <html lang="de">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zählerstände und Stromverbräuche</title>
    <style>
        :root {
            --gradient-colors: #4CAF50 0%, #FFEB3B 50%, #FF9800 75%, #F44336 100%;
        }
        table {
            border-collapse: collapse; /* Ensure borders are unified and don't overlap */
            width: 100%;
            font-family: Arial, sans-serif;
            border: 1px solid #ddd; /* Add a border around the entire table */
        }
        th, td {
            border: 1px solid #ddd; /* Ensure each cell, including the bottom row, has a border */
            padding: 8px;
            text-align: left;
            white-space: nowrap; /* Prevent line breaks in headers */
            position: relative;
            overflow: hidden;  /* Wichtig: Balken wird in der Zelle begrenzt */
        }
        td:not(:first-child) {
            text-align: right; /* Right-align all columns except the first */
        }
        th {
            background-color: #f4f4f4;
            color: #333;
            white-space: nowrap; /* Prevent line breaks in headers */
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        tr:nth-child(odd) {
            background-color: #ffffff;
        }
        tr:hover {
            background-color: #f1f1f1;
        }
        /* Style the footer row */
        .total-row {
            font-weight: bold;
            border-top: 2px solid #000; /* Draws a thick border for visual separation */
        }
        .progress-container {
            width: 100%;
            height: 30px;
            position: relative;
            border-radius: 5px;
            overflow: hidden;
            background: linear-gradient(
                90deg,
                rgba( 76, 175, 80, 0.8)   0%,   /* Grün  , 80% Deckkraft */
                rgba(255, 235, 59, 0.6)  33%,   /* Gelb  , 60% Deckkraft */
                rgba(255, 152,  0, 0.4)  66%,   /* Orange, 40% Deckkraft */
                rgba(244,  67, 54, 0.2) 100%    /* Rot   , 20% Deckkraft */
            );
        }

        .progress-mask {
            position: absolute;
            right: 0;
            top: 0;
            height: 100%;
            width: calc(100% - var(--width));
            animation: growBar 5s linear forwards;
            transform-origin: right;
        }
        /* Style for alternating rows */
        tr:nth-child(odd) .progress-mask {
            background: #ffffff; /* Background for odd rows */
        }
        tr:nth-child(even) .progress-mask {
            background: #f9f9f9; /* Background for even rows */
        }

        @keyframes growBar {
            from { width: 100%; }
            to { width: calc(100% - var(--width)); }
        }

        .value-text {
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            color: black;
            z-index: 2;
        }
    </style>
    </head>
    <body>
    """

    return html_begin


def generate_html_end():
    return "</body></html>"


def generate_html_table(data, column_names, max_consumption):
    # Start HTML table
    html = "<table>"

    # Generate table header dynamically
    html += "<tr>"
    for column in column_names:
        html += f"<th>{column}</th>"
    html += "</tr>"

    # Populate table rows with data
    for index, row in enumerate(data):
        last_row = False
        if index == len(data) - 1:  # Last row
            last_row = True
            html += '<tr class="total-row">'
        else:  # Regular row
            html += "<tr>"

        for cell_idx, cell in enumerate(row):
            if cell_idx == 4 and not last_row:
                cell_as_float = german_to_float(cell)

                percentage = (cell_as_float / max_consumption) * 100 if max_consumption > 0 else 0
                html += f"""
                    <td>
                        <div class="progress-container">
                            <div class="progress-mask" style="--width: {percentage}%;"></div>
                            <span class="value-text">{cell}</span>
                        </div>
                    </td>
                """
            else:
                html += f"<td>{cell}</td>"
        html += "</tr>"

    # Close HTML table
    html += "</table>"
    return html


def publish_html_to_webserver(html, local_publish_dir, remote_ssh_host, remote_publish_dir):
    # Generate filename with today's date
    today_str = date.today().strftime("%Y-%m-%d")
    local_file_path = os.path.join(local_publish_dir, f"daily-email_{today_str}.html")

    with open(local_file_path, "w") as f:
        f.write(html)

    # Connect to remote
    r = plumbum.machines.SshMachine(remote_ssh_host)

    # Copy local file to remote
    fro = plumbum.local.path(local_file_path)
    to = r.path(os.path.join(remote_publish_dir, f"daily-email_{today_str}.html"))
    plumbum.path.utils.copy(fro, to)

    return today_str


def add_link_to_view_in_browser(html, today_str, public_base_url):
    # HTML parsen
    soup = BeautifulSoup(html, 'html.parser')

    # Erste <ul> im <body> finden
    first_ul = soup.body.find('ul')

    # Neues <li>-Element erstellen
    new_li = soup.new_tag("li")

    # HTML-Inhalt als echten Tag parsen und einfügen
    link = BeautifulSoup(
        f'<a href="{public_base_url}/data/daily-email_{today_str}.html">Diese E-Mail im Browser anzeigen.</a>',
        "html.parser",
    )
    new_li.append(link)

    # <li> am Ende der <ul> anhängen
    first_ul.append(new_li)

    return soup.prettify()


def send_email(html_content, meter_number, sender_name, sender_email, reply_to_name, reply_to_email,
                recipient, cc_recipient):
    sender = formataddr((sender_name, sender_email))
    reply_to = formataddr((reply_to_name, reply_to_email))
    subject = f"Geräte-Identifikation [{meter_number}]: Zählerstände und Stromverbräuche"

    # Mail-Header erstellen
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['Reply-To'] = reply_to
    msg['To'] = recipient
    if cc_recipient:
        msg['Cc'] = cc_recipient
    msg['Subject'] = subject

    # HTML-Inhalt hinzufügen
    msg.attach(MIMEText(html_content, 'html'))

    # Alle Empfänger (To + CC) extrahieren und in eine Liste packen
    to_addresses = [addr.strip() for addr in msg['To'].split(',')]
    cc_addresses = [addr.strip() for addr in msg['Cc'].split(',')] if cc_recipient else []
    all_recipients = to_addresses + cc_addresses

    # Mail über Postfix senden
    try:
        with smtplib.SMTP('localhost') as server:  # Postfix läuft lokal
            server.sendmail(msg['From'], all_recipients, msg.as_string())
        print("Mail erfolgreich gesendet!")
    except Exception as e:
        print(f"Fehler beim Senden der Mail: {e}")


def build_query_list(device_id):
    return [
          ["<h3>stündlich, gestern</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order, ROW_NUMBER() OVER (ORDER BY time DESC) AS rn, DATE_FORMAT(time, '%d.%m.%Y, %H:00 - %H:59') AS `Zeitraum`, FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`, FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`, FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`, IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`, IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`, IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                    FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_hourly` WHERE DATE(time) = CURDATE() - INTERVAL 1 DAY)
                    UNION ALL
                    (SELECT 2 AS sort_order, NULL AS rn, 'Summe' AS `Zeitraum`, '&nbsp;'   AS `Stand Gesamt`, '&nbsp;'  AS `Stand HT`, '&nbsp;'  AS `Stand NT`, FORMAT(SUM(power_consumption_total), 3, 'de_DE') AS `Verbrauch Gesamt`, FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`, FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                    FROM tasmota_{device_id}_SENSOR_CONSUMPTION_hourly
                    WHERE DATE(time) = CURDATE() - INTERVAL 1 DAY)
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Zeitraum`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        , ["<h3>täglich (die letzten 14 Tage)</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order, ROW_NUMBER() OVER (ORDER BY time DESC) AS rn, DATE_FORMAT(time, '%a, %d.%m.%Y') AS `Datum`, FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`, FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`, FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`, IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`, IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`, IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                     FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_daily` WHERE DATE(time) >= (CURDATE() - INTERVAL 14 DAY)
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        'Summe / Durchschnitt' AS `Datum`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        CONCAT (
                            FORMAT(SUM(power_consumption_total), 3, 'de_DE'),
                            ' / ',
                            FORMAT(AVG(power_consumption_total), 3, 'de_DE')
                        ) AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                     FROM
                         `tasmota_{device_id}_SENSOR_CONSUMPTION_daily`
                     WHERE
                         DATE(time) >= (CURDATE() - INTERVAL 14 DAY)
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Datum`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        , ["<h3>wöchentlich (die letzten 10 Wochen)</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order, ROW_NUMBER() OVER (ORDER BY time DESC) AS rn, CONCAT (DATE_FORMAT(DATE_SUB(time, INTERVAL 6 DAY), '%d.%m.%Y'), ' - ', DATE_FORMAT(time, '%d.%m.%Y')) AS `Woche`, FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`, FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`, FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`, IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`, IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`, IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                     FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_weekly` WHERE DATE(time) >= (CURDATE() - INTERVAL 10 WEEK) AND time < DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        'Summe / Durchschnitt' AS `Woche`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        CONCAT(
                            FORMAT(SUM(power_consumption_total), 3, 'de_DE'),
                            ' / ',
                            FORMAT(AVG(power_consumption_total), 3, 'de_DE')
                        ) AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                     FROM
                        `tasmota_{device_id}_SENSOR_CONSUMPTION_weekly`
                     WHERE
                         DATE(time) >= (CURDATE() - INTERVAL 10 WEEK)
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Woche`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        , ["<h3>monatlich</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order, ROW_NUMBER() OVER (ORDER BY time DESC) AS rn, CONCAT( DATE_FORMAT(DATE_SUB(time, INTERVAL DAY(time)-1 DAY), '%d.%m.%Y'), ' - ', DATE_FORMAT(time, '%d.%m.%Y') ) AS `Monat`, FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`, FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`, FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`, IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`, IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`, IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                     FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_monthly` WHERE time < DATE_FORMAT(CURDATE(), '%Y-%m-01')
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        'Summe / Durchschnitt' AS `Monat`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        CONCAT(
                            FORMAT(SUM(power_consumption_total), 3, 'de_DE'),
                            ' / ',
                            FORMAT(AVG(power_consumption_total), 3, 'de_DE')
                        ) AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                     FROM
                        `tasmota_{device_id}_SENSOR_CONSUMPTION_monthly`
                     WHERE time < DATE_FORMAT(CURDATE(), '%Y-%m-01')
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Monat`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        , ["<h3>quartalsweise</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order,
                            ROW_NUMBER() OVER (ORDER BY time DESC) AS rn,
                            CONCAT(
                                DATE_FORMAT(MAKEDATE(YEAR(time), 1) + INTERVAL (QUARTER(time)*3 - 3) MONTH, '%d.%m.%Y'),
                                ' - ',
                                DATE_FORMAT(LAST_DAY(MAKEDATE(YEAR(time), 1) + INTERVAL (QUARTER(time)*3 - 1) MONTH), '%d.%m.%Y')
                            ) AS `Quartal`,
                            FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`,
                            FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`,
                            FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`,
                            IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`,
                            IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`,
                            IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                     FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_quarterly` WHERE time < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL (QUARTER(CURDATE())*3 - 3) MONTH
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        'Summe / Durchschnitt' AS `Quartal`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        CONCAT(
                            FORMAT(SUM(power_consumption_total), 3, 'de_DE'),
                            ' / ',
                            FORMAT(AVG(power_consumption_total), 3, 'de_DE')
                        ) AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                     FROM
                        `tasmota_{device_id}_SENSOR_CONSUMPTION_quarterly`
                     WHERE time < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL (QUARTER(CURDATE())*3 - 3) MONTH
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Quartal`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        , ["<h3>jährlich</h3><br>",
           f"""
                WITH combined as (
                    (SELECT 1 AS sort_order,
                            ROW_NUMBER() OVER (ORDER BY time DESC) AS rn,
                              CONCAT(
                                DATE_FORMAT(MAKEDATE(YEAR(time), 1), '%d.%m.%Y'),
                                ' - ',
                                DATE_FORMAT(
                                LAST_DAY(DATE_ADD(MAKEDATE(YEAR(time), 1), INTERVAL 11 MONTH)),
                                '%d.%m.%Y'
                                )
                            ) AS `Jahr`,
                            FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`,
                            FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`,
                            FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`,
                            IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`,
                            IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`,
                            IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                     FROM `tasmota_{device_id}_SENSOR_CONSUMPTION_yearly` WHERE time < MAKEDATE(YEAR(CURDATE()), 1)
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        'Summe / Durchschnitt' AS `Jahr`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        CONCAT(
                            FORMAT(SUM(power_consumption_total), 3, 'de_DE'),
                            ' / ',
                            FORMAT(AVG(power_consumption_total), 3, 'de_DE')
                        ) AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                     FROM
                        `tasmota_{device_id}_SENSOR_CONSUMPTION_yearly`
                     WHERE time < MAKEDATE(YEAR(CURDATE()), 1)
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `Jahr`, `Stand Gesamt`, `Stand HT`, `Stand NT`, `Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`
                FROM combined;
          """]
        ]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--db-host", default=os.environ.get("METER_DB_HOST", "localhost"),
                         help="MySQL/MariaDB host (default: $METER_DB_HOST or localhost)")
    parser.add_argument("--db-port", type=int, default=int(os.environ.get("METER_DB_PORT", "3306")),
                         help="MySQL/MariaDB port (default: $METER_DB_PORT or 3306)")
    parser.add_argument("--db-user", required=True, help="MySQL/MariaDB user")
    parser.add_argument("--db-password", default=os.environ.get("METER_DB_PASSWORD"),
                         help="MySQL/MariaDB password (default: $METER_DB_PASSWORD)")
    parser.add_argument("--db-name", required=True, help="MySQL/MariaDB database name")
    parser.add_argument("--device-id", required=True,
                         help="Device id used in table names, e.g. tasmota_<device-id>_SENSOR - "
                              "must match persistence/mysql/schema.sql and the telegraf configs")

    parser.add_argument("--sender-name", required=True, help="Email 'From' display name")
    parser.add_argument("--sender-email", required=True, help="Email 'From' address")
    parser.add_argument("--reply-to-name", required=True, help="Email 'Reply-To' display name")
    parser.add_argument("--reply-to-email", required=True, help="Email 'Reply-To' address")
    parser.add_argument("--recipient", required=True, help="Email 'To' address")
    parser.add_argument("--cc-recipient", default=None, help="Optional email 'Cc' address")

    parser.add_argument("--public-base-url", required=True,
                         help="Public base URL the report is published under, e.g. "
                              "https://example.org/three-phase-meter - no trailing slash")
    parser.add_argument("--local-publish-dir", required=True,
                         help="Local directory to write the day's HTML report into")
    parser.add_argument("--remote-ssh-host", required=True,
                         help="SSH host alias (see ~/.ssh/config) to copy the report to")
    parser.add_argument("--remote-publish-dir", required=True,
                         help="Directory on --remote-ssh-host to copy the report into")

    parser.add_argument("--grafana-url", default=None,
                         help="Optional link to a Grafana dashboard, included in the report if set")
    parser.add_argument("--meter-description", default="Stromzähler",
                         help="Short description of the meter for the report heading, used as "
                              "'Daten vom <meter-description>, <meter number>' (default: 'Stromzähler')")
    parser.add_argument("--reading-head-description", default=None,
                         help="Optional description of the reading head/gateway hardware, appended as "
                              "'..., über <reading-head-description>' after the meter number if set")

    return parser.parse_args()


def main():
    args = parse_args()

    db_config = {
        'user': args.db_user,
        'password': args.db_password,
        'host': args.db_host,
        'port': args.db_port,
        'database': args.db_name,
        'raise_on_warnings': True,
    }

    meter_number, html_for_meter_number = get_html_for_meter_number(db_config, args.device_id)
    query_list = build_query_list(args.device_id)

    html_table_list = []
    for query in query_list:
        data, column_names, max_consumption = query_database(db_config, query=query[1], col_idx_for_max=4)

        if data:
            table_html = generate_html_table(data, column_names, max_consumption)
            html_table_list.append(query[0] + table_html)

    if len(html_table_list) > 0:
        html = generate_html_begin()

        grafana_li = ""
        if args.grafana_url:
            grafana_li = (
                f'<li>Eine <a href="{args.grafana_url}">graphische Darstellung</a> gibt es ebenfalls. '
                f'(Nur im privaten/lokalen Hausnetz verfügbar.)</li>'
            )

        reading_head_suffix = f", über {args.reading_head_description}" if args.reading_head_description else ""
        html += f"""
        <h2>Daten vom {args.meter_description}, {meter_number}{reading_head_suffix}</h2>
        <ul>
            <li>Alle „Stromwerte“ sind in <tt>[kWh]</tt> angegeben.</li>
            {grafana_li}
            <li>Alle Berichte sind im <a href="{args.public_base_url}/index.php">Archiv</a> gesammelt.</li>
        </ul>
        <br />

        <h3>Zählernummer</h3>
        {html_for_meter_number}
        <br/>
        <h2>Zählerstände und Stromverbräuche</h2>
        """

        for table_html in html_table_list:
            html += table_html
            html += "<br><br>"
        html += generate_html_end()

        today_str = publish_html_to_webserver(html, args.local_publish_dir, args.remote_ssh_host,
                                               args.remote_publish_dir)
        html = add_link_to_view_in_browser(html, today_str, args.public_base_url)
        send_email(html, meter_number, args.sender_name, args.sender_email, args.reply_to_name,
                   args.reply_to_email, args.recipient, args.cc_recipient)
    else:
        print("Keine Daten gefunden oder Fehler bei der Abfrage.")
        html = "<html><body><h2>Keine Daten gefunden</h2><p>Es wurden keine passenden Ergebnisse in der Datenbank gefunden.</p></body></html>"
        send_email(html, "", args.sender_name, args.sender_email, args.reply_to_name,
                   args.reply_to_email, args.recipient, args.cc_recipient)


if __name__ == "__main__":
    main()
