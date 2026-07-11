# Using the PPC Smart Meter Gateway

This chapter is written in German, as it is a topic that I feel is particularly relevant to the German context. If an English version is required, the usual translation tools may be helpful.

Dieses Kapitel wird in deutscher Sprache verfasst, da es sich um ein Thema handelt, das mir besonders relevant für den deutschen Kontext erscheint. Sollte eine englischsprachige Version benötigt werden, können die gängigen Übersetzungswerkzeuge hilfreich sein.

---
<!-- TOC -->

---

##### Links zur Web-Site von PPC zum Smart Meter Gateway

- [LTE Smart Meter Gateway 2.0](https://www.ppc-ag.de/de/produkte/smart-meter-gateways/lte-smart-meter-gateway/)
- [Services](https://www.ppc-ag.de/de/service/)
  - [Serviceportal](https://www.ppc-ag.de/de/produkte/smart-meter-gateways/serviceportal/)
    - [Für Privatpersonen](https://www.ppc-ag.de/de/produkte/support/)
      - [SMGW-Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf)

## - [Using the PPC Smart Meter Gateway](#using-the-ppc-smart-meter-gateway)
        - [Links zur Web-Site von PPC zum Smart Meter Gateway](#links-zur-web-site-von-ppc-zum-smart-meter-gateway)
- [Using the PPC Smart Meter Gateway](#using-the-ppc-smart-meter-gateway)
        - [Links zur Web-Site von PPC zum Smart Meter Gateway](#links-zur-web-site-von-ppc-zum-smart-meter-gateway)
  - [- Using the PPC Smart Meter Gateway](#--using-the-ppc-smart-meter-gateway)
    - [Verbindungstest](#verbindungstest)
    - [DHCP oder andere IP-Adresse vom Messstellenbetreiber anfordern](#dhcp-oder-andere-ip-adresse-vom-messstellenbetreiber-anfordern)
    - [Zugriff auf das Subnetz 192.168.1.0/24 und/oder die Gateway IP 192.168.1.200 aus einem anderen Subnetz](#zugriff-auf-das-subnetz-1921681024-undoder-die-gateway-ip-1921681200-aus-einem-anderen-subnetz)
      - [Einsatz eines Raspberry Pi](#einsatz-eines-raspberry-pi)
        - [Einbindung per WLAN ins Hausnetz](#einbindung-per-wlan-ins-hausnetz)
        - [Vergabe einer festen IP *192.168.1.14* für das Subnetz des Smart Meter (192.168.1.0/24)](#vergabe-einer-festen-ip-192168114-für-das-subnetz-des-smart-meter-1921681024)
      - [OpenWrt auf einer alten Fritz!Box 7490](#openwrt-auf-einer-alten-fritzbox-7490)
      - [Einsatz eines Routers](#einsatz-eines-routers)
  - [Abruf der Zählerstände](#abruf-der-zählerstände)
    - [Manuelle Verfahren zum Abruf der Zählerstände](#manuelle-verfahren-zum-abruf-der-zählerstände)
      - [Nutzung der Web-Anwendung](#nutzung-der-web-anwendung)
      - [Nutzung der TRuDI Software](#nutzung-der-trudi-software)
    - [Automatisierter Abruf der Zählerstände](#automatisierter-abruf-der-zählerstände)


Als Router für das "Hausnetz" im Subnetz 192.168.0.0/24 verwende ich eine Fritz!Box mit der IP 192.168.0.1. Bisher sind alle Geräte in diesem Subnetz versammelt.

Mein PPC LTE Smart Meter Gateway (*SMGw*)hat eine **feste IP-Adresse**: 192.168.1.200.
Die Adresse wird nicht über DHCP bezogen, es ist **kein Standard-Gateway** im Smart Meter Gateway gesetzt.
Wer sein Hausnetz nicht im Subnetz 192.168.1.0/24 betreibt, wird zunächst Schwierigkeiten haben das Gateway zu erreichen.
Im [Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf) steht dazu:
>Das *Smart Meter Gateway* verwendet als Werkseinstellung die IP-Adresse 192.168.1.200. Falls der Administrator Ihres *Smart Meter Gateways* die Einstellung auf den dynamischen Bezug der IP-Adresse (DHCP) modifiziert hat, vergeben die meisten Router automatisch eine passende IP-Adresse an das *Smart Meter Gateway*, über die es dann erreichbar ist. Sehen Sie im Menü Ihres Routers nach, welche IP-Adresse für das *Smart Meter Gateway* zugeteilt wurde. Genaue Informationen dazu können Sie der Betriebsanleitung Ihres Routers entnehmen.

Zum Test des Zugriffs auf das Smart Meter kann ein Rechner manuell mit einer IP-Adresse aus dem Subnetz 192.168.1.0/24 versorgt werden. Mit einer direkten Verbindung über ein Ethernet-Kabel sollte die Verbindung möglich sein.

### Verbindungstest
Nach der physischen mit einem Rechner im Subnetz 192.168.1.0/24 habe ich zunächst mittels `curl` den Zugriff getestet. Das läuft auf einer niedrigen Ebene, damit sind mindestens einige Fehlerquellen ausgeschlossen. Auf `ping` reagiert das Gateway nicht.

```bash
curl -t '' --connect-timeout 2 -s telnet://"192.168.1.200:443" </dev/null ; echo $?
```
Bei einer intakten Verbindung liefert `curl` **49**  als exit status zurück.

Die für unser Szenario relevanten *exit codes* (siehe auch [everything curl - Exit code - Available exit codes](https://everything.curl.dev/cmdline/exitcode.html)):

 >**6** - Couldn't resolve host.
 **7** - Failed to connect to host. curl managed to get an IP address to themachine and it tried to setup a TCP connection to the host but failed.This can be because you have specified the wrong port number, entered thewrong host name, the wrong protocol or perhaps because there is a firewallor another network equipment in between that blocks the traffic fromgetting through.
**28** - Operation timeout.
**49** - connected to host on port. I.e. OK in this scenario. (Malformed telnet option. The telnet options you provide to curl was not using the correct syntax.)


**Hier noch ein paar Alternativen zum Test der Verbindung (ohne die Verwendung von `ping`):**


```bash
$ nc -u -v -z 192.168.1.200 443
Connection to 192.168.1.200 443 port [udp/https] succeeded!
```

```bash
pi@raspberrypi:~ $ sudo nmap -sP 192.168.1.0/24
Starting Nmap 7.80 ( https://nmap.org ) at 2025-04-25 16:11 CEST
...
Nmap scan report for 192.168.1.200
Host is up (0.00100s latency).
MAC Address: 00:25:18:B5:EF:68 (Power Plus Communications AG)
Nmap scan report for 192.168.1.14
Host is up.
Nmap done: 256 IP addresses (3 hosts up) scanned in 3.45 seconds
```

```bash
pi@raspberrypi:~ $ sudo nmap -sU -p 443 192.168.1.200
Starting Nmap 7.80 ( https://nmap.org ) at 2025-04-25 16:31 CEST
Nmap scan report for 192.168.1.200
Host is up (0.00099s latency).

PORT    STATE         SERVICE
443/udp open|filtered https
MAC Address: 00:25:18:B5:EF:68 (Power Plus Communications AG)

Nmap done: 1 IP address (1 host up) scanned in 7.25 seconds

```

Ist die *low level* Verbindung erfolgreich, steht der Test im Browser mit der IP *https://192.168.1.200/cgi-bin/hanservice.cgi* an.


Im [Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf) heißt es:
>Um sich mit dem Smart Meter Gateway zu verbinden, müssen Sie in Ihrem Browser die Adresse *https://192.168.1.200/cgi-bin/hanservice.cgi* oder die von Ihrem Router an das Smart Meter Gateway vergebene Adresse unter Anhängen des Pfades */cgi-bin/hanservice.cgi* eingeben.


Klappt die Verbindung wird nach einem Zertifikat gefragt. Der Ablauf ist im [Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf) detailliert beschrieben.

Ich habe vom Messstellenbetreiber - auch nach Anfrage - kein Zertifikat, sondern lediglich ein Benutzernamen und ein Kennwort erhalten. Für meine Zwecke reicht das aus.


### DHCP oder andere IP-Adresse vom Messstellenbetreiber anfordern
Nach dem o.g. Zitat aus dem Handbuch kann man den Messtellenbetreiber fragen, ob er das Gateway entweder auf DHCP umstellen oder eine andere IP-Adresse zuweisen kann.

Ich habe dazu von Herrn [Thomas Müller](#contact) die folgende Information bekommen:
>Grundsätzlich können die SMGWs an der HAN-Schnittstelle schon auch DHCP. Wie die Schnittstelle konfiguriert wird, liegt in den Händen des jeweiligen Versorgungsunternehmens – nachträglich wird das aber sicherlich keiner ändern. Man will sich da keine Problem durch das Kunden-Netzwerk einfangen und möglichst alles einheitlich halten.

Sträubt sich der Messtellenbetreiber gegen diese Lösung (das war bei mir der Fall), gilt es den Zugriff mittels Netzwerkgymnastik zu realisieren.

Für diesen Zweck bieten sich sicherlich viele Möglichkeiten an, ich möchte drei Lösungswege beschreiben:

### Zugriff auf das Subnetz 192.168.1.0/24 und/oder die Gateway IP 192.168.1.200 aus einem anderen Subnetz

#### Einsatz eines Raspberry Pi 

Beinahe alle Raspberries können mindestens zwei Netzwerkschnittstellen haben:
- das eingebaute WLAN
- das eingebaute Ethernet oder ein Ethernet per USB-->Ethernet Adapter

Die Idee ist, das Ethernet mit dem Smart Meter und das Hausnetz per WLAN zu verbinden.

Ich habe dazu einen alten Raspberry aus September 2012 mit *bullseye* genutzt:

```bash
pi@raspberrypi:~ $ cat /proc/device-tree/model
Raspberry Pi Model B Rev 2

pi@raspberrypi:~ $ cat /etc/os-release
PRETTY_NAME="Raspbian GNU/Linux 11 (bullseye)"
NAME="Raspbian GNU/Linux"
VERSION_ID="11"
VERSION="11 (bullseye)"
VERSION_CODENAME=bullseye
```

##### Einbindung per WLAN ins Hausnetz

Im Hausnetz vergibt bei mir eine Fritz!Box per DHCP die Adressen.

```bash
pi@raspberrypi:~ $ sudo cat /etc/wpa_supplicant/wpa_supplicant.conf
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
	ssid="Mein_WLAN_im_192_168_0_0/24_Subnetz"
	psk=d27xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx11d7
}
```

##### Vergabe einer festen IP *192.168.1.14* für das Subnetz des Smart Meter (192.168.1.0/24)

Auf *eth0* die feste IP im Subnetz des Smart Meter (192.168.1.0/24) vergeben.
Ich habe als DNS meine Fritz!Box im Hausnetz mit der IP 192.168.0.1 eingetragen.

```bash
pi@raspberrypi:~ $ cat /etc/dhcpcd.conf
...
interface eth0
static ip_address=192.168.1.14/24
static routers=192.168.1.1
static domain_name_servers=192.168.0.1
noipv6
```

Im Ergebnis sieht das dann so aus:


```bash
pi@raspberrypi:~ $ ifconfig
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.1.14  netmask 255.255.255.0  broadcast 192.168.1.255
        inet6 fe80::ba27:ebff:fe9c:42be  prefixlen 64  scopeid 0x20<link>
        ether b8:27:eb:9c:42:be  txqueuelen 1000  (Ethernet)
        RX packets 12  bytes 1159 (1.1 KiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 58  bytes 7005 (6.8 KiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        inet6 ::1  prefixlen 128  scopeid 0x10<host>
        loop  txqueuelen 1000  (Local Loopback)
        RX packets 21  bytes 2367 (2.3 KiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 21  bytes 2367 (2.3 KiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.0.181  netmask 255.255.255.0  broadcast 192.168.0.255
        inet6 2001:16b8:b58e:1c00:cd4a:3105:54b4:25b7  prefixlen 64  scopeid 0x0<global>
        inet6 fe80::5c26:434:ab76:e29  prefixlen 64  scopeid 0x20<link>
        inet6 fd64:2bf6:5a25:0:9ce2:ac14:e0a4:2a4e  prefixlen 64  scopeid 0x0<global>
        ether 00:90:4c:0e:81:23  txqueuelen 1000  (Ethernet)
        RX packets 632  bytes 262788 (256.6 KiB)
        RX errors 0  dropped 42  overruns 0  frame 0
        TX packets 148  bytes 17704 (17.2 KiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

**Die KI (hier DeepSeek) hat mir gesagt, was ich tun muss um die Netze zu verbinden:**

> To configure NAT (Network Address Translation) or masquerading on a Raspberry Pi for the > `192.168.0.0/24` network to its own IP address (`192.168.1.14`) on the `192.168.1.0/24` > network, you need to set up IP forwarding and configure `iptables` rules. Here's a > step-by-step guide:
> 
> ---
> 
> ##### **Step 1: Enable IP Forwarding**
> 1. Edit the sysctl configuration file to enable IP forwarding:
>    ```bash
>    sudo nano /etc/sysctl.conf
>    ```
> 2. Find the line `#net.ipv4.ip_forward=1` and uncomment it (remove the `#`):
>    ```bash
>    net.ipv4.ip_forward=1
>    ```
> 3. Save and exit the file (`Ctrl+O`, `Enter`, `Ctrl+X`).
> 
> 4. Apply the changes immediately:
>    ```bash
>    sudo sysctl -p
>    ```
> 
> ---
> 
> ##### **Step 2: Configure NAT/Masquerading with iptables**
> 1. Add the following `iptables` rules to enable NAT/masquerading:
>    ```bash
>    sudo iptables -t nat -A POSTROUTING -s 192.168.0.0/24 -o eth0 -j MASQUERADE
>    ```
>    - `-s 192.168.0.0/24`: Specifies the source network (`192.168.0.0/24`).
>    - `-o eth0`: Specifies the outgoing interface (replace `eth0` with the correct interface > name, e.g., `wlan0` for Wi-Fi).
>    - `-j MASQUERADE`: Masquerades the traffic, replacing the source IP with the Raspberry > Pi's IP (`192.168.1.14`).
> 
> 2. Allow forwarding between the two networks:
>    ```bash
>    sudo iptables -A FORWARD -i eth1 -o eth0 -j ACCEPT
>    sudo iptables -A FORWARD -i eth0 -o eth1 -m state --state RELATED,ESTABLISHED -j ACCEPT
>    ```
>    - Replace `eth1` with the interface connected to the `192.168.0.0/24` network.
>    - Replace `eth0` with the interface connected to the `192.168.1.0/24` network.
> 
> ---
> 
> ##### **Step 3: Save iptables Rules**
> To make the `iptables` rules persistent across reboots:
> 1. Install the `iptables-persistent` package:
>    ```bash
>    sudo apt update
>    sudo apt install iptables-persistent
>    ```
> 2. Save the current rules:
>    ```bash
>    sudo netfilter-persistent save
>    ```
> 
> ---
> 
> ###### **Step 4: Verify the Configuration**
> 1. Check the NAT rules:
>    ```bash
>    sudo iptables -t nat -L -n -v
>    ```
> 2. Test connectivity from a device in the `192.168.0.0/24` network to a device in the `192.> 168.1.0/24` network.
> 
> ---
> 
> ##### **Optional: Set Up Static Routes**
> If devices in the `192.168.0.0/24` network need to reach the `192.168.1.0/24` network, > ensure they have a route pointing to the Raspberry Pi's IP address (`192.168.0.x`) as the > gateway.
> 
> ---
> 
> This setup will allow devices in the `192.168.0.0/24` network to access the `192.168.1.0/> 24` network through the Raspberry Pi, with the Pi performing NAT/masquerading.

Ich habe dann noch einen Switch mit dem Raspberry und darüber einen WLAN Access Point verbunden. So habe ich auch das Subnetz 912.168.1.0/24 des SMGw im Haus verfügbar.

Wer mag, kann dann noch [Raspberry Pi: DNSMASQ als DHCP-Server einrichten](https://www.elektronik-kompendium.de/sites/raspberry-pi/2202031.htm):


```bash
pi@raspberrypi:~ $ grep -v "^#" /etc/dnsmasq.conf | grep -v "^$"
port=0
interface=eth0
dhcp-range=192.168.1.50,192.168.1.150,255.255.255.0,36h
dhcp-option=option:router,192.168.1.1   # Default gateway
dhcp-option=option:dns-server,192.168.0.1
```

Eine schöne Anleitung dafür gibt es auch bei [Zugriff auf Gerät mit fester IP ohne Default Gateway aus anderem Subnetz](https://administrator.de/forum/zugriff-auf-geraet-mit-fester-ip-ohne-default-gateway-aus-anderem-subnetz-671438.html#comment-1900995) von [aqui](https://administrator.de/user/aqui/).




#### OpenWrt auf einer alten Fritz!Box 7490

Über [OpenWrt](https://openwrt.org/) auf einer ausgedienten Fritz!Box 7490 konnte ich ebenfalls die beiden Subnetze 192.168.0.0/24 vom Hausnetz und 192.168.1.0/24 des SMGw transparent verbinden.
Dazu habe ich die Anleitung für eben dieses Modell verwendet: [AVM FRITZ!Box 7490](https://openwrt.org/toh/avm/fritz.box.7490)

Unter [OpenWrt](https://openwrt.org/) auf der Fritz!Box dann:

```bash
/etc/config/network
```


```bash
...
config interface 'lanHome'  
	option proto 'static'  
	option ipaddr '192.168.0.254'  
        option netmask '255.255.255.0'  

config interface 'lanSMGW'  
	option device 'lan3'  
	option proto 'static'  
	option ipaddr '192.168.1.1'  
        option netmask '255.255.255.0'  
	option proxy_arp '1'  

config route
    option interface 'lanSMGW'  
    option target '192.168.1.200'  
    option netmask '255.255.255.255'  
...
```

```bash
/etc/config/firewall
```

```bash
...
config zone
	option name 'lan2SGMW'  
	option input 'ACCEPT'  
	option output 'ACCEPT'  
	option forward 'ACCEPT'  
	option masq '1'  
	list network 'lanHome'  
	list network 'lanSMGW'  
...
```

LAN2 mit dem Subnetz 192.168.0.0/24 verbinden
LAN3 mit dem SMGw verbinde.
Die **statische Route auf der Fritz!Box** nicht vergessen: Zielnetz: 192.168.1.0, Maske: 255.255.255.0, Gateway: 192.168.0.254 

#### Einsatz eines Routers

Die Lösung, die sich für mich am besten anfühlt, basiert auf dem Einsatz eines Routers.

Nutzen:
- Transparenter Zugriff zwischen allen Geräten der Subnetze 192.168.0.0/24 und 192.168.1.0/24 mit der Möglichkeit der feingranularen Justierung.
- Zugriff auf das Internet über das bestehende Hausnetz (192.168.0.0/24) mit der Fritz!Box 192.168.0.1 als Router.
- Keine Veränderung am bestehenden Hausnetz (192.168.0.0/24) bis auf die ergänzung einer statischen Route.

Ich habe mich für einen [Mikrotik RB5009UPr+S+IN](https://help.mikrotik.com/docs/spaces/UM/pages/141197359/RB5009UPr+S+IN) entschieden.

Hier meine Konfiguration

```bash
/ip pool add name=dhcp_pool_v10 ranges=192.168.1.32-192.168.1.199

/ip dhcp-server
add address-pool=dhcp_pool_v10 interface=vlan10 name=dhcp4vlan10

/interface bridge port
add bridge=bridge comment=defconf interface=ether2
add bridge=bridge-vlan00 comment=defconf interface=ether3
add bridge=bridge-vlan00 comment=defconf interface=ether4
add bridge=bridge-vlan10 comment=defconf interface=ether5 pvid=10
add bridge=bridge-vlan10 comment=defconf interface=ether6 pvid=10
add bridge=bridge-vlan10 comment=defconf interface=ether7 pvid=10
add bridge=bridge-vlan10 comment=defconf interface=ether8 pvid=10


/interface vlan
add name=vlan00 vlan-id=0 interface=bridge-vlan00
add name=vlan10 vlan-id=10 interface=bridge-vlan10


/interface bridge vlan
add bridge=bridge-vlan10 tagged=bridge-vlan10 untagged=ether6 vlan-ids=10
add bridge=*C tagged=*C untagged=ether4 vlan-ids=1
add bridge=bridge-vlan00 untagged=ether4 vlan-ids=1


/ip address
add address=192.168.1.1/24 interface=vlan10 network=192.168.1.0
add address=192.168.0.254/24 interface=vlan00 network=192.168.0.0

/ip dhcp-client
add comment=defconf disabled=yes interface=ether1
/ip dhcp-server network
add address=192.168.1.0/24 dns-server=192.168.0.1 gateway=192.168.1.1


/ip dns
set allow-remote-requests=yes servers=192.168.0.1


/ip firewall filter
add action=accept chain=input comment=\
    "defconf: accept established,related,untracked" connection-state=\
    established,related,untracked
add action=drop chain=input comment="defconf: drop invalid" connection-state=\
    invalid
add action=accept chain=input comment="defconf: accept ICMP" protocol=icmp
add action=accept chain=input comment=\
    "defconf: accept to local loopback (for CAPsMAN)" dst-address=127.0.0.1
add action=drop chain=input comment="defconf: drop all not coming from LAN" \
    disabled=yes in-interface-list=!LAN
add action=accept chain=forward comment="defconf: accept in ipsec policy" \
    ipsec-policy=in,ipsec
add action=accept chain=forward comment="defconf: accept out ipsec policy" \
    ipsec-policy=out,ipsec
add action=fasttrack-connection chain=forward comment="defconf: fasttrack" \
    connection-state=established,related hw-offload=yes
add action=accept chain=forward comment=\
    "defconf: accept established,related, untracked" connection-state=\
    established,related,untracked
add action=drop chain=forward comment="defconf: drop invalid" \
    connection-state=invalid
add action=drop chain=forward comment=\
    "defconf: drop all from WAN not DSTNATed" connection-nat-state=!dstnat \
    connection-state=new in-interface-list=WAN
add action=accept chain=forward in-interface=vlan10 out-interface=vlan10
add action=accept chain=input dst-address=192.168.1.1 in-interface=\
    bridge-vlan10 protocol=icmp src-address=192.168.1.0/24
add action=accept chain=forward comment=\
    "Allow traffic from subnet 0 to subnet 1" dst-address=192.168.1.0/24 \
    src-address=192.168.0.0/24
add action=accept chain=forward comment=\
    "Allow traffic from subnet 1 to subnet 0" dst-address=192.168.0.0/24 \
    src-address=192.168.1.0/24
add action=accept chain=input protocol=icmp
add action=accept chain=forward dst-address=192.168.1.200 src-address=\
    192.168.0.0/24
add action=accept chain=forward in-interface=vlan00 out-interface=vlan10
add action=accept chain=forward connection-state=established,related \
    in-interface=vlan10 out-interface=vlan00
add action=accept chain=forward dst-address=192.168.1.200 dst-port=443 \
    protocol=tcp src-address=192.168.0.0/24

   
/ip firewall nat
add action=masquerade chain=srcnat comment="defconf: masquerade" \
    ipsec-policy=out,none out-interface-list=WAN
add action=accept chain=srcnat dst-address=192.168.0.0/24 src-address=\
    192.168.1.0/24
add action=masquerade chain=srcnat comment=\
    "NAT fuer Zugriff von VLAN00 auf 192.168.1.200" dst-address=192.168.1.200 \
    out-interface=vlan10 src-address=192.168.0.0/24


/ip route
add dst-address=192.168.1.0/24 gateway=192.168.1.1

```

Die **statische Route auf der Fritz!Box** nicht vergessen: Zielnetz: 192.168.1.0, Maske: 255.255.255.0, Gateway: 192.168.0.254 

Das ist ja selbst für einen Laien selbsterklärend ;-). Für Netzwerk-[Honks](https://www.spiegel.de/karriere/buerogezeter-das-kleine-schimpfwort-abc-a-744198.html) ein paar Erläuterungen:


- *dhcp_pool_v**10***: IP-Adressen Pool für *vlan**10***
- *vlan**0**0*: steht für das Subnetz *192.168.**0**.0/24*
- *vlan**1**0*: steht für das Subnetz *192.168.**1**.0/24*

1. Die Ethernet-Interfaces werden in *bridges* für die beiden Subnetze zusammengefasst.

2. Die *bridges* werden den VLANs über die *vlan-id* zugeordnet.

3. Es werden "Router"-Adressen für die VLANs hinzugefügt.

4. Mit `/ip firewall filter` wird der Netzwerkverkehr zwischen den VLANs erlaubt.

5. Die `/ip firewall nat` sind sehr ähnlich denen der [Raspberry Lösung](#einsatz-eines-raspberry-pi).




## Abruf der Zählerstände vom SMGw
### Manuelle Verfahren zum Abruf der Zählerstände
#### Nutzung der Web-Anwendung
Die Nutzung der Web-Anwendung ist im [Handbuch](https://www.ppc-ag.de/wp-content/uploads/2023/04/Handbuch-fuer-Verbraucher-v.4.15.pdf) gut beschrieben.
#### Nutzung der TRuDI - Transparenz- und Display-Software

Die TRuDI-Software und Dookumentation findet man bei der Physikalisch-Technischen Bundesanstalt: [Transparenz- und Displaysoftware TRuDI](https://www.ptb.de/cms/ptb/fachabteilungen/abt2/fb-23/ag-234/info-center-234/trudi.html). Das Handbuch gibt es jeweils beim link zur entsprechenden TRuDI-Version.

Dort findet man auch den link zum TRuDI repository [trudi-public](https://bitbucket.org/dzgtrudi/trudi-public/src/master/) und einen hilfreichen Kontakt:

>Thomas Müller
IVU Softwareentwicklung GmbH
tmueller@ivugmbh.de



### Automatisierter Abruf der Zählerstände

Für den automatisierten Abruf hat mir der o.g. 
<a id="contact"></a>

>Thomas Müller
IVU Softwareentwicklung GmbH
tmueller@ivugmbh.de

auf die Sprünge geholfen. Er hat mir ausgesprochen hilfsbereit, schnell und umfassend auf meine Fragen geantwortet. Vielen Dank dafür!

Herr Müller hat die bedauerliche Nachricht überbracht, dass das *SMGw* über keine REST-Schnittstelle verfügt:

>Das SMGW von PPC hat leider keine REST-Schnittstelle – ein Umstand, den wir selbst seit Jahren beim Hersteller bemängeln. TRuDI holt sich die Daten aus den altbackenen HTML-Seiten des Gateways – echt kein Spaß.

Ich wollte gerne kontinierlich, am liebsten bei jeder Änderungen, unseren Stromverbrauch aufzeichnen und damit die Möglichkeit haben, Energiefresser zu identifizieren.

Herr Müller hat mir die Vorraussetzungen genannt:
 
>ohne einen konfigurierten TAF14 haben Sie maximal auf 15-Minuten-Werte Zugriff.
TAF14 steht für „Tarifanwendungsfall zur hochfrequenten Bereitstellung von Messwerten für Mehrwertdienste“.

OK, also gebenich mich mit Werten vom SMGw alle 15 Minuten zufrieden und übe mich im Web Scraping.



 
>Meine private Lösung für mein Smart-Home sieht übrigens so aus: zwei Hutschienen-Zähler welche mittels RS485-zu-Ethernet-Modul jede Sekunde abgefragt werden. Warum extra Hutschienen-Zähler? Ich hatte zunächst auch auf die IR-Ablesekopf-Methode gesetzt: Allerdings sind bei meinen, vom Netzbetreiber gesetzten Zählern, nacheinander die IR-Sende-Dioden ausgefallen… da wird gern auch mal etwas gespart von den (chinesischen) Zähler-Herstellern.

