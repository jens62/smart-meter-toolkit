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

Optional temperature: with --temperature-model and --temperature-id every section gets two extra
columns just before "Verbrauch Gesamt" - the time-weighted average temperature ("Ø °C") and a
narrow trend column (one dot per row, connected by a thin line, newest row on top; blue = cold,
red = warm). The values come from the roll-up tables of persistence/mysql/temperature. Without
these two flags the report has no temperature columns, and if the flags are given but the
temperature tables are missing, unreadable or empty, the script prints a warning and builds the
report without them. See README.md ("Optional: temperature columns").
"""
import argparse
import itertools
import os
import re

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
        /* Temperatur: schmale Wertespalte und Verlaufsspalte (Punkt + dünne Linie) */
        th.temp, td.temp {
            padding-left: 4px;
            padding-right: 4px;
        }
        th.temp {
            text-align: center;
        }
        td.partial {
            color: #888;
            font-style: italic;
        }
        td.spark {
            padding: 0;
            width: 56px;
            min-width: 56px;
        }
        td.spark {
            line-height: 0;
        }
        td.spark svg {
            display: block;
        }
    </style>
    </head>
    <body>
    """

    return html_begin


def generate_html_end():
    return "</body></html>"


# --- Temperatur: Wertespalte + Verlaufsspalte -----------------------------------------------
# Die Abfragen liefern pro Abschnitt die Spalte TEMP_COL (Text, deutsch formatiert) sowie die
# Hilfsspalten _temp (Zahl) und _cov (Abdeckung in %); Spalten, die mit "_" beginnen, werden nicht
# angezeigt. Direkt hinter TEMP_COL kommt die Verlaufsspalte: je Zeile ein Punkt, benachbarte
# Punkte sind durch eine dünne Linie verbunden (wie ein Grafana-Diagramm, gedreht: neueste Zeile
# oben, Temperatur nach rechts).
TEMP_COL = 'Ø °C'
SPARK_W = 56                # Breite der Verlaufsspalte in px
SPARK_ROW_H = 47            # Zeilenhöhe in px: 30px Balken + 2 * 8px Padding + 1px Rahmen
SPARK_PAD = 5               # Abstand der Punkte vom Rand in px
TEMP_DECIMALS = 1
TEMP_PARTIAL_BELOW_PCT = 90  # darunter: grauer Wert, hohler Punkt
# Feste Farbskala in °C (kalt = blau, warm = rot), damit dieselbe Temperatur in allen Abschnitten
# dieselbe Farbe hat. Zwischen den Stützstellen wird linear interpoliert.
TEMP_COLOR_STOPS = [(-5, '#1E40AF'), (5, '#2563EB'), (11, '#06B6D4'), (17, '#22C55E'),
                    (23, '#F59E0B'), (30, '#DC2626')]

_spark_ids = itertools.count(1)


def temperature_table(model, sensor_id, level):
    """Name der Temperaturtabelle, siehe persistence/mysql/temperature/README.md."""
    safe_model = re.sub(r'[^A-Za-z0-9]+', '_', model)
    return f"rtl_433_{safe_model}_{int(sensor_id)}_TEMPERATURE_{level}"


def temperature_available(db_config, model, sensor_id):
    """True if all six roll-up tables of the sensor can be read and the hourly table has data.

    Not everybody who collects meter readings also collects temperature; a missing, unreadable
    (information_schema only lists tables the user may access) or empty temperature table must not
    break the report, so the caller falls back to the report without temperature columns."""
    tables = [temperature_table(model, sensor_id, level) for level in TEMP_JOIN_ON]
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables "
                       f"WHERE table_schema = DATABASE() AND table_name IN ({', '.join(['%s'] * len(tables))})",
                       tables)
        found = cursor.fetchone()[0]
        has_data = False
        if found == len(tables):
            cursor.execute(f"SELECT 1 FROM `{temperature_table(model, sensor_id, 'hourly')}` LIMIT 1")
            has_data = cursor.fetchone() is not None
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"Warnung: Temperaturtabellen nicht prüfbar ({err}) - Bericht ohne Temperatur")
        return False

    if found != len(tables):
        print(f"Warnung: nur {found} von {len(tables)} Temperaturtabellen für {model} {sensor_id} "
              f"vorhanden/lesbar - Bericht ohne Temperatur")
        return False
    if not has_data:
        print(f"Warnung: noch keine Temperaturdaten für {model} {sensor_id} - Bericht ohne Temperatur")
        return False
    return True


def temp_color(value):
    stops = TEMP_COLOR_STOPS
    if value <= stops[0][0]:
        return stops[0][1]
    if value >= stops[-1][0]:
        return stops[-1][1]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t0 <= value <= t1:
            return rgb_to_hex(interpolate_color(c0, c1, (value - t0) / (t1 - t0)))


def _spark_x(value, lo, hi):
    if hi <= lo:
        return SPARK_W / 2
    return SPARK_PAD + (value - lo) / (hi - lo) * (SPARK_W - 2 * SPARK_PAD)


def spark_cell(idx, temps, covs, lo, hi):
    """Zelle der Verlaufsspalte für Datenzeile idx (0 = neueste Zeile, oben).

    Jede Zelle zeichnet ihren Punkt in der Zeilenmitte und die halbe Linie zum Nachbarn oben und
    unten, bis zur Zeilengrenze. Die waagerechten Rahmen sind in dieser Spalte ausgeblendet,
    dadurch setzen sich die Halbstücke benachbarter Zeilen nahtlos zu einer Linie fort."""
    n = len(temps)
    top = '1px solid #ddd' if idx == 0 else 'hidden'
    bottom = '1px solid #ddd' if idx == n - 1 else 'hidden'
    td_open = f'<td class="spark" style="border-top: {top}; border-bottom: {bottom};">'
    value = temps[idx]
    if value is None:
        return td_open + '</td>'

    h = SPARK_ROW_H
    x, y = _spark_x(value, lo, hi), h / 2
    color = temp_color(value)
    defs, lines = '', ''

    def half(x1, y1, x2, y2, color1, color2):
        gid = f"sg{next(_spark_ids)}"
        defs_part = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                     f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}">'
                     f'<stop offset="0" stop-color="{color1}"/><stop offset="1" stop-color="{color2}"/>'
                     f'</linearGradient>')
        line_part = (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="url(#{gid})" stroke-width="1.2"/>')
        return defs_part, line_part

    if idx > 0 and temps[idx - 1] is not None:   # Nachbar oben = neuer
        other = temps[idx - 1]
        d, l = half((_spark_x(other, lo, hi) + x) / 2, 0, x, y,
                    temp_color((other + value) / 2), color)
        defs += d
        lines += l
    if idx < n - 1 and temps[idx + 1] is not None:   # Nachbar unten = älter
        other = temps[idx + 1]
        d, l = half(x, y, (x + _spark_x(other, lo, hi)) / 2, h,
                    color, temp_color((other + value) / 2))
        defs += d
        lines += l

    cov = covs[idx]
    partial = cov is not None and cov < TEMP_PARTIAL_BELOW_PCT
    fill = '#ffffff' if partial else color
    tip = f"{value:.2f} °C".replace('.', ',') + (f" ({cov:.0f} % abgedeckt)" if partial else "")
    dot = (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{fill}" stroke="{color}" '
           f'stroke-width="{1.5 if partial else 0}"><title>{tip}</title></circle>')
    return (f'{td_open}<svg width="{SPARK_W}" height="{h}" viewBox="0 0 {SPARK_W} {h}">'
            f'<defs>{defs}</defs>{lines}{dot}</svg></td>')


def generate_html_table(data, column_names, max_consumption):
    shown = [i for i, name in enumerate(column_names) if not name.startswith('_')]
    bar_idx = column_names.index('Verbrauch Gesamt')
    temp_idx = column_names.index(TEMP_COL) if TEMP_COL in column_names else None

    temps, covs, lo, hi = [], [], 0, 0
    if temp_idx is not None:
        t_col, c_col = column_names.index('_temp'), column_names.index('_cov')
        temps = [row[t_col] for row in data[:-1]]     # ohne die "Summe"-Zeile
        covs = [row[c_col] for row in data[:-1]]
        present = [v for v in temps if v is not None]
        if present:
            lo, hi = min(present), max(present)

    # Start HTML table
    html = "<table>"

    # Generate table header dynamically
    html += "<tr>"
    for i in shown:
        if i == temp_idx:   # one header over the value column and the trend column
            html += f'<th class="temp" colspan="2">{column_names[i]}</th>'
        else:
            html += f"<th>{column_names[i]}</th>"
    html += "</tr>"

    # Populate table rows with data
    for index, row in enumerate(data):
        last_row = False
        if index == len(data) - 1:  # Last row
            last_row = True
            html += '<tr class="total-row">'
        else:  # Regular row
            html += "<tr>"

        for cell_idx in shown:
            cell = row[cell_idx]
            if cell_idx == bar_idx and not last_row:
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
            elif cell_idx == temp_idx:
                cov = None if last_row else covs[index]
                partial = cov is not None and temps[index] is not None and cov < TEMP_PARTIAL_BELOW_PCT
                css = "temp partial" if partial else "temp"
                tip = f' title="nur {cov:.0f} % des Zeitraums mit Messwerten"' if partial else ""
                html += f'<td class="{css}"{tip}>{cell}</td>'
                html += '<td class="spark"></td>' if last_row else spark_cell(index, temps, covs, lo, hi)
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


# Wie die Temperatur-Zeile einer Periode in der Verbrauchstabelle gefunden wird. "time" ist dort die
# lokale Zeit der letzten Ablesung der Periode, "time_utc" dieselbe Zeit in UTC; die
# Temperaturtabellen haben period_start_utc/period_start_local (persistence/mysql/temperature).
# Stunden werden über UTC verbunden (eindeutig auch in der doppelten Stunde im Herbst).
TEMP_JOIN_ON = {
    'hourly': "t.period_start_utc = time_utc - INTERVAL (MINUTE(time_utc) * 60 + SECOND(time_utc)) SECOND",
    'daily': "t.period_start_local = DATE(time)",
    'weekly': "t.period_start_local = DATE(time) - INTERVAL WEEKDAY(time) DAY",
    'monthly': "t.period_start_local = DATE(time) - INTERVAL (DAYOFMONTH(time) - 1) DAY",
    'quarterly': "t.period_start_local = MAKEDATE(YEAR(time), 1) + INTERVAL ((QUARTER(time) - 1) * 3) MONTH",
    'yearly': "t.period_start_local = MAKEDATE(YEAR(time), 1)",
}


def _section_sql(device_id, temperature, level, label_alias, label_expr, detail_where, summary_where,
                 summary_label, summary_total):
    """Abfrage eines Abschnitts. temperature: None oder (model, sensor_id)."""
    table = f"`tasmota_{device_id}_SENSOR_CONSUMPTION_{level}`"

    join = temp_detail = temp_summary = help_detail = help_summary = temp_final = help_final = ""
    if temperature:
        model, sensor_id = temperature
        join = f"LEFT JOIN `{temperature_table(model, sensor_id, level)}` t ON {TEMP_JOIN_ON[level]}"
        # Detailzeilen: Wert der Periode. Summenzeile: zeitgewichteter Mittelwert über alle Zeilen.
        temp_detail = f"IFNULL(FORMAT(t.avg_temp_c, {TEMP_DECIMALS}, 'de_DE'), '--') AS `{TEMP_COL}`,"
        temp_summary = (f"IFNULL(FORMAT(SUM(t.integral_cs) / NULLIF(SUM(t.covered_seconds), 0), "
                        f"{TEMP_DECIMALS}, 'de_DE'), '--') AS `{TEMP_COL}`,")
        help_detail = ", t.avg_temp_c AS _temp, t.coverage_pct AS _cov"
        help_summary = ", NULL AS _temp, NULL AS _cov"
        temp_final = f"`{TEMP_COL}`, "
        help_final = ", _temp, _cov"

    return f"""
                WITH combined as (
                    (SELECT 1 AS sort_order,
                            ROW_NUMBER() OVER (ORDER BY time DESC) AS rn,
                            {label_expr} AS `{label_alias}`,
                            FORMAT(SML_1_8_0__Bezug_Gesamt, 3, 'de_DE') AS `Stand Gesamt`,
                            FORMAT(SML_1_8_1__Bezug_HT, 3, 'de_DE') AS `Stand HT`,
                            FORMAT(SML_1_8_2__Bezug_NT, 3, 'de_DE') AS `Stand NT`,
                            {temp_detail}
                            IFNULL(FORMAT(power_consumption_total, 3, 'de_DE'), '--') AS `Verbrauch Gesamt`,
                            IFNULL(FORMAT(power_consumption_HT, 3, 'de_DE'), '--') AS `Verbrauch HT`,
                            IFNULL(FORMAT(power_consumption_NT, 3, 'de_DE'), '--') AS `Verbrauch NT`
                            {help_detail}
                     FROM {table}
                     {join}
                     WHERE {detail_where}
                    )
                    UNION ALL
                    (SELECT
                        2 AS sort_order,
                        NULL AS rn,
                        '{summary_label}' AS `{label_alias}`,
                        '&nbsp;' AS `Stand Gesamt`,
                        '&nbsp;' AS `Stand HT`,
                        '&nbsp;' AS `Stand NT`,
                        {temp_summary}
                        {summary_total} AS `Verbrauch Gesamt`,
                        FORMAT(SUM(power_consumption_HT), 3, 'de_DE') AS `Verbrauch HT`,
                        FORMAT(SUM(power_consumption_NT), 3, 'de_DE') AS `Verbrauch NT`
                        {help_summary}
                     FROM {table}
                     {join}
                     WHERE {summary_where}
                    )
                    ORDER BY
                    sort_order,
                    rn
                )
                SELECT `{label_alias}`, `Stand Gesamt`, `Stand HT`, `Stand NT`, {temp_final}`Verbrauch Gesamt`, `Verbrauch HT`, `Verbrauch NT`{help_final}
                FROM combined;
          """


def build_query_list(device_id, temperature=None):
    """temperature: None (no temperature columns) or (model, sensor_id), e.g. ('inFactory-TH', 168)."""
    total_and_avg = ("CONCAT(FORMAT(SUM(power_consumption_total), 3, 'de_DE'), ' / ', "
                     "FORMAT(AVG(power_consumption_total), 3, 'de_DE'))")
    total_only = "FORMAT(SUM(power_consumption_total), 3, 'de_DE')"
    avg_label = 'Summe / Durchschnitt'

    sections = [
        ("<h3>stündlich, gestern</h3><br>", dict(
            level='hourly', label_alias='Zeitraum',
            label_expr="DATE_FORMAT(time, '%d.%m.%Y, %H:00 - %H:59')",
            detail_where="DATE(time) = CURDATE() - INTERVAL 1 DAY",
            summary_where="DATE(time) = CURDATE() - INTERVAL 1 DAY",
            summary_label='Summe', summary_total=total_only)),
        ("<h3>täglich (die letzten 14 Tage)</h3><br>", dict(
            level='daily', label_alias='Datum',
            label_expr="DATE_FORMAT(time, '%a, %d.%m.%Y')",
            detail_where="DATE(time) >= (CURDATE() - INTERVAL 14 DAY)",
            summary_where="DATE(time) >= (CURDATE() - INTERVAL 14 DAY)",
            summary_label=avg_label, summary_total=total_and_avg)),
        ("<h3>wöchentlich (die letzten 10 Wochen)</h3><br>", dict(
            level='weekly', label_alias='Woche',
            label_expr="CONCAT(DATE_FORMAT(DATE_SUB(time, INTERVAL 6 DAY), '%d.%m.%Y'), ' - ', DATE_FORMAT(time, '%d.%m.%Y'))",
            detail_where="DATE(time) >= (CURDATE() - INTERVAL 10 WEEK) AND time < DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)",
            summary_where="DATE(time) >= (CURDATE() - INTERVAL 10 WEEK)",
            summary_label=avg_label, summary_total=total_and_avg)),
        ("<h3>monatlich</h3><br>", dict(
            level='monthly', label_alias='Monat',
            label_expr="CONCAT(DATE_FORMAT(DATE_SUB(time, INTERVAL DAY(time)-1 DAY), '%d.%m.%Y'), ' - ', DATE_FORMAT(time, '%d.%m.%Y'))",
            detail_where="time < DATE_FORMAT(CURDATE(), '%Y-%m-01')",
            summary_where="time < DATE_FORMAT(CURDATE(), '%Y-%m-01')",
            summary_label=avg_label, summary_total=total_and_avg)),
        ("<h3>quartalsweise</h3><br>", dict(
            level='quarterly', label_alias='Quartal',
            label_expr=("CONCAT(DATE_FORMAT(MAKEDATE(YEAR(time), 1) + INTERVAL (QUARTER(time)*3 - 3) MONTH, '%d.%m.%Y'), ' - ', "
                        "DATE_FORMAT(LAST_DAY(MAKEDATE(YEAR(time), 1) + INTERVAL (QUARTER(time)*3 - 1) MONTH), '%d.%m.%Y'))"),
            detail_where="time < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL (QUARTER(CURDATE())*3 - 3) MONTH",
            summary_where="time < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL (QUARTER(CURDATE())*3 - 3) MONTH",
            summary_label=avg_label, summary_total=total_and_avg)),
        ("<h3>jährlich</h3><br>", dict(
            level='yearly', label_alias='Jahr',
            label_expr=("CONCAT(DATE_FORMAT(MAKEDATE(YEAR(time), 1), '%d.%m.%Y'), ' - ', "
                        "DATE_FORMAT(LAST_DAY(DATE_ADD(MAKEDATE(YEAR(time), 1), INTERVAL 11 MONTH)), '%d.%m.%Y'))"),
            detail_where="time < MAKEDATE(YEAR(CURDATE()), 1)",
            summary_where="time < MAKEDATE(YEAR(CURDATE()), 1)",
            summary_label=avg_label, summary_total=total_and_avg)),
    ]
    return [[title, _section_sql(device_id, temperature, **kwargs)] for title, kwargs in sections]


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

    parser.add_argument("--temperature-model", default=None,
                         help="rtl_433 model of the temperature sensor, e.g. inFactory-TH. Together with "
                              "--temperature-id this adds the temperature columns (roll-up tables from "
                              "persistence/mysql/temperature)")
    parser.add_argument("--temperature-id", type=int, default=None,
                         help="rtl_433 id of the temperature sensor, e.g. 168")
    parser.add_argument("--preview-file", default=None,
                         help="Write the HTML report to this file and stop: nothing is published "
                              "or emailed")

    args = parser.parse_args()
    if (args.temperature_model is None) != (args.temperature_id is None):
        parser.error("--temperature-model and --temperature-id must be given together")
    return args


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
    temperature = (args.temperature_model, args.temperature_id) if args.temperature_model else None
    if temperature and not temperature_available(db_config, *temperature):
        temperature = None   # warning already printed: carry on with the plain report
    query_list = build_query_list(args.device_id, temperature)
    # "Verbrauch Gesamt" is column 4, or column 5 when the temperature column is in front of it
    consumption_col = 5 if temperature else 4

    html_table_list = []
    for query in query_list:
        data, column_names, max_consumption = query_database(db_config, query=query[1],
                                                             col_idx_for_max=consumption_col)

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

        temperature_li = ""
        if temperature:
            temperature_li = (
                f'<li>„Ø °C“ ist die zeitgewichtete Durchschnittstemperatur des Sensors '
                f'{args.temperature_model} ({args.temperature_id}); die Farbe der Punkte reicht von blau (kalt) '
                f'bis rot (warm). Graue Werte und hohle Punkte: weniger als {TEMP_PARTIAL_BELOW_PCT} % '
                f'des Zeitraums waren durch Messwerte abgedeckt.</li>'
            )

        reading_head_suffix = f", über {args.reading_head_description}" if args.reading_head_description else ""
        html += f"""
        <h2>Daten vom {args.meter_description}, {meter_number}{reading_head_suffix}</h2>
        <ul>
            <li>Alle „Stromwerte“ sind in <tt>[kWh]</tt> angegeben.</li>
            {temperature_li}
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

        if args.preview_file:
            with open(args.preview_file, "w") as f:
                f.write(html)
            print(f"Vorschau geschrieben: {args.preview_file} (nicht veröffentlicht, keine Mail gesendet)")
            return

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
