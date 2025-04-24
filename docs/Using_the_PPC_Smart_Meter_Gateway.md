# Using the PPC Smart Meter Gateway

This chapter is written in German, as it is a topic that I feel is particularly relevant to the German context. If an English version is required, the usual translation tools may be helpful.

Dieses Kapitel wird in deutscher Sprache verfasst, da es sich um ein Thema handelt, das mir besonders relevant für den deutschen Kontext erscheint. Sollte eine englischsprachige Version benötigt werden, können die gängigen Übersetzungswerkzeuge hilfreich sein.


##### Links zur Web-Site von PPC zum Smart Meter Gateway

- [LTE Smart Meter Gateway 2.0](https://www.ppc-ag.de/de/produkte/smart-meter-gateways/lte-smart-meter-gateway/)
- [Services](https://www.ppc-ag.de/de/service/)
  - [Serviceportal](https://www.ppc-ag.de/de/produkte/smart-meter-gateways/serviceportal/)
    - [Für Privatpersonen](https://www.ppc-ag.de/de/produkte/support/)
      - [SMGW-Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf)

## Einbindung ins Netzwerk
Mein PPC LTE Smart Meter Gateway hat eine feste IP-Adresse: 192.168.1.200.
Die Adresse wird nicht über DHCP bezogen, es ist kein Standard-Gateway im Smart Meter Gateway gesetzt.
Wer sein Hausnetz nicht im Subnetz 192.168.1.0/24 betreibt, wird zunächst Schwierigkeiten haben das Gateway zu erreichen.
Im [Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf) steht dazu:
>Das Smart Meter Gateway verwendet als Werkseinstellung die IP-Adresse 192.168.1.200. Falls der Administrator Ihres Smart Meter Gateways die Einstellung auf den dynamischen Bezug der IP-Adresse (DHCP) modifiziert hat, vergeben die meisten Router automatisch eine passende IP-Adresse an das Smart Meter Gateway, über die es dann erreichbar ist. Sehen Sie im Menü Ihres Routers nach, welche IP-Adresse für das Smart Meter Gateway zugeteilt wurde. Genaue Informationen dazu können Sie der Betriebsanleitung Ihres Routers entnehmen.

### DHCP oder andere IP Adresse vergeben lassen
Das bedeutet, man kann den Messtellenbetreiber fragen, ob er das Gateway entweder auf DHCP umstellen oder eine andere IP-Adresse zuweisen kann.

Streubt sich der Messtellenbetreiber gegen diese Lösung, gilt es den Zugriff mittels Netzwerkgymnastik zu realisieren.

Für diesen Zweck bieten sich sicherlich viele Möglichkeiten an, ich möchte drei Lösungswege beschreiben:

### Zugriff auf das Subnetz 192.168.1.0/24 und/opder die Gateway IP 192.168.1.200 aus einem anderen Subnetz

#### Einsatz eines Raspberry Pi 

#### OpenWrt

[OpenWrt](https://openwrt.org/)

#### Einsatz eines Routers

