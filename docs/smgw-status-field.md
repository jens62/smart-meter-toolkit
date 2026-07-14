# The SMGW `status` field: format and meaning

This documents where the raw export files' `status` field comes from,
which standard defines it, and what its bit values mean. Investigated
2026-07-14 while deciding whether `normalize_meter_csv.awk` should keep
discarding this column (see `TODO.md` item 9).

## `.cms` vs. `.xml`: same data, signed not encrypted

`scripts/read_SMGW.py`'s `extract_xml_from_cms()` extracts XML from a
`.cms` file via `openssl cms -verify -inform DER`. Inspecting a raw
`.cms` file directly (`openssl asn1parse -inform DER`, `openssl cms
-cmsout -print -noverify`) confirms it's a plain **PKCS#7/CMS
`SignedData` structure** (RFC 5652, SHA-256 digest) - not encrypted.
The `eContent` inside is the exact same plaintext XML as the `.xml`
sibling file, byte for byte. The `.cms` container only adds a
signature for integrity/authenticity; it carries no extra information
over the `.xml`.

## The namespace identifies the standard

The signed/exported XML declares:

```xml
xmlns:ns1="urn:k461-dke-de:profile_generic-1"
xmlns:ns2="urn:k461-dke-de:extension-1"
```

`k461-dke-de` is the namespace of **DKE (Deutsche Kommission
Elektrotechnik) Working Group K461** - the committee behind Germany's
Smart Meter Gateway ecosystem, standardized in **BSI TR-03109**. This
is the official German SMGW export format, not a vendor-proprietary
one. A per-reading `<ns2:status>` element is encoded as
`<ns2:unsigned>N</ns2:unsigned>` - the COSEM "Data" CHOICE type,
consistent with the DLMS/COSEM `Extended Register`/`Profile Generic`
class model (`class_id="7"`, matching the XML root element).

## Where the bit meanings are defined

- **BSI TR-03109-1, Annex "COSEM/HTTP Webservices"** - defines the
  generic RESTful COSEM API and the `cod:Data` types used in this XML
  profile (`Register` class 3, `Profile Generic` class 7), but does
  *not* itself define `status` bit meanings.
- **BSI TR-03109-1 "Detailspezifikation" v2.0, §9.3.4.2**
  (`TA.SML.CLI.ProcessMeterData`) states: "Das SMGW MUSS in
  SML-Nachrichten empfangene Statusinformationen für die
  Eingangsmesswerte gemäß **Kapitel 15** aus dem Messwert-Attribut
  'status' verarbeiten." - explicitly the same `status` attribute
  found in the exports. Also: "Ist das Status-Attribut nicht
  vorhanden, liegt keine Störung der Messeinrichtung oder des
  Messwertes vor" (absent status = no fault). Attribute indices for
  `Register`(3)/`Advanced Extended Register`(32770) are `value`(02),
  `scaler_unit`(03), `status`(04), `capture_time`(04).
- **Same document, Chapter 15 "Messwertstatus", Table 15.1
  "Kombiniertes Statuswort"** (pp. 87-89) - the actual bit table: a
  32-bit word combining SMGW-origin bits with meter-origin bits, laid
  out differently depending on the meter's communication type (wired
  electricity/FNN, wired gas/DVGW G697, or wireless OMS/wMBus). Bits
  with an unambiguous single meaning regardless of meter type:

  | Bit | Meaning |
  |-----|---------|
  | 1 | `SMGW_ValueNotValidated` - "Messwerte nicht zur Abrechnung" (reading not yet validated for billing) |
  | 8 | `SMGW_Error` - fatal error detected in the SMGW |
  | 9 | `SMGW_TimeNotValid` - SMGW system time invalid |
  | 12 | `SMGW_Warning` - a warning is present in the SMGW |
  | 13 | `SMGW_NoValue` - no reading within the expected receive window |
  | 14 | `MTR_Tamper` - magnetic/mechanical/electrical manipulation detected at the meter |
  | 16 | `SMGW_ValueTriggered` - reading sent due to threshold exceedance |

  The remaining bits (meter-type-specific fault/warning bits, e.g.
  `MTR_Warning`, `MTR_Fatal`, tamper sub-flags) differ by meter
  communication type and weren't extracted cleanly from the PDF's
  multi-column table layout (per-meter-type applicability markers and
  semantic text share the same cells) - re-derive them from the source
  PDF directly (`docs/references/BSI_TR-03109-1_Detailspezifikation_v2_0.pdf`,
  pp. 87-89) rather than trusting a second-hand transcription, if a
  more complete table is ever needed.

Observed raw values in this project's own export files are `0` and `3`
(`3` = bits 0+1 set). Bit 1 (`SMGW_ValueNotValidated`) is a plausible
match: a reading the SMGW hasn't yet confirmed as billing-valid is
exactly what's expected right after an interruption, which is
consistent with (but not proof of) the empirical finding that
`status=3` readings loosely cluster around gap/recovery windows (see
`TODO.md` item 9 for the concrete counts, which are specific to this
project's dataset).

## Ruled out: the generic DLMS Blue Book

The generic **DLMS UA 1000-1:2005 (7th ed.), "COSEM Identification
System and Interface Objects"** ("Blue Book") explicitly leaves the
`Extended Register` `status` attribute's exact bit meanings
"manufacturer defined" at the COSEM level. That's true in general, but
BSI's TR-03109-1 standardizes it specifically for SMGW exports (as
shown above), so the Blue Book's manufacturer-specific caveat doesn't
apply to this data source.

## Sources

Archived in `docs/references/` so this doesn't depend on the URLs
staying up:

- [BSI TR-03109-1, Annex "COSEM/HTTP Webservices"](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Publikationen/TechnischeRichtlinien/TR03109/TR-03109-1_Anlage_COSEM-HTTP_Webservices.pdf?__blob=publicationFile&v=1) -> `BSI_TR-03109-1_Anlage_COSEM-HTTP_Webservices.pdf`
- [BSI TR-03109-1 "Detailspezifikation" v2.0](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Publikationen/TechnischeRichtlinien/TR03109/TR-03109-1_Detailspezifikation_v2_0.pdf?__blob=publicationFile&v=2) -> `BSI_TR-03109-1_Detailspezifikation_v2_0.pdf` (Chapter 15, pp. 87-89, has the bit table)
- [DLMS UA 1000-1:2005, 7th ed. excerpt (COSEM Identification System and Interface Objects)](http://www.cs.ru.nl/~marko/onderwijs/bss/SmartMeter/Excerpt_BB7.pdf) -> `DLMS_UA_1000-1_Excerpt_BB7_COSEM.pdf`
