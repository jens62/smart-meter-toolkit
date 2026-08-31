<?php
setlocale(LC_TIME, 'de_DE.UTF-8');
date_default_timezone_set('Europe/Berlin');

$dataDir = __DIR__ . '/data';

$files = glob($dataDir . '/daily-email_*.html');
$availableDates = [];

foreach ($files as $file) {
    if (preg_match('/daily-email_(\d{4}-\d{2}-\d{2})\.html$/', basename($file), $matches)) {
        $fileDate   = DateTime::createFromFormat('Y-m-d', $matches[1]);
        $reportDate = clone $fileDate;
        $reportDate->modify('-1 day');

        // Pfad für fetch(): Basisverzeichnis plus Dateiname
        $availableDates[
            $reportDate->format('Y-m-d')
        ] = basename($dataDir) . '/' . basename($file);
    }
}

?>

<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>🔌 Stromverbrauchs-Berichte</title>
    <link rel="stylesheet" href="style.css">
    <!--link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css"-->
    <link rel="stylesheet" href="css/flatpickr.min.css">
</head>
<body>
    <div class="container">
        <h1>🔌 Stromverbrauchs-Berichte</h1>
        <label for="calendar">Wähle ein Datum (Daten zeigen den Verbrauch dieses Tages):</label>
        <input type="text" id="calendar" placeholder="Datum auswählen" readonly>

        <div id="reportContainer"></div>
    </div>

    <!--script src="https://cdn.jsdelivr.net/npm/flatpickr"></script-->
    <!--script src="https://cdn.jsdelivr.net/npm/flatpickr/dist/l10n/de.js"></script-->
    <script src="js/flatpickr.min.js"></script>
    <script src="js/de.js"></script>

    <script>
        const dateMap = <?= json_encode($availableDates) ?>;
        const validDates = Object.keys(dateMap);

        flatpickr("#calendar", {
            locale: "de",
            dateFormat: "d.m.Y",
            enable: validDates.map(date => {
                const [year, month, day] = date.split("-");
                return `${day}.${month}.${year}`;
            }),
            onChange: function(selectedDates, dateStr, instance) {
                if (!selectedDates.length) return;

                const selectedDate = selectedDates[0];
                const isoDate = flatpickr.formatDate(selectedDate, "Y-m-d"); // → "2025-09-09"
                const fileName = dateMap[isoDate];

                if (!fileName) {
                    document.getElementById('reportContainer').innerHTML = `<p class="error">Kein Bericht für den ${dateStr} verfügbar.</p>`;
                    return;
                }

                fetch(fileName)
                    .then(response => {
                        if (!response.ok) throw new Error("Datei nicht gefunden");
                        return response.text();
                    })
                    .then(html => {
                        const temp = document.createElement('div');
                        temp.style.visibility = 'hidden';
                        temp.style.position = 'absolute';
                        temp.innerHTML = html;
                        document.body.appendChild(temp);

                        const tables = temp.querySelectorAll('table');
                        let maxWidth = 0;
                        tables.forEach(table => {
                            const width = table.scrollWidth;
                            if (width > maxWidth) maxWidth = width;
                        });

                        document.body.removeChild(temp);

                        const container = document.querySelector('.container');
                        container.style.width = (maxWidth + 40) + 'px';

                        document.getElementById('reportContainer').innerHTML = html;
                    })
                    .catch(err => {
                        document.getElementById('reportContainer').innerHTML = `<p class="error">Bericht für ${dateStr} konnte nicht geladen werden.</p>`;
                    });
            }
        });
    </script>
</body>
</html>