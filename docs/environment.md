# Environnement de référence

Le développement et les premiers essais matériels ont été réalisés les
25 et 26 octobre 2026 dans une VM Linux. Ce document décrit le matériel testé,
sans publier les adresses du réseau, les chemins privés ou les identifiants
du compteur et de l’adaptateur.

| Élément | Environnement testé |
| --- | --- |
| Système de développement | Debian GNU/Linux 13, ARM64 |
| Python natif | 3.13 ; suite également vérifiée avec Python 3.11 |
| Docker | 26.1.5, image Python 3.13 slim Bookworm |
| Compteur | Linky monophasé, TIC standard |
| Adaptateur | Cartelectronic USB 1 TIC, USB `0403:6015`, pilote Linux `ftdi_sio` |
| Liaison série | 9600 bauds, 7 bits, parité paire, 1 bit d’arrêt |
| GX | Raspberry Pi 4, Venus OS 3.85 |

Une première lecture de 20,05 s a reçu **15 trames complètes valides**,
soit 720 groupes avec checksum valide, sans rejet. La période moyenne entre
fins de trame était d’environ **1,253 s**. Les champs `VTIC`, `URMS1`, `IRMS1`,
`SINSTS`, `SINSTI`, `EAST` et `EAIT` ont été observés.

Le lecteur de production utilise un seul accès série. Le chemin du périphérique
doit être relevé sur chaque machine dans `/dev/serial/by-id/` ; aucun nom
`ttyUSB0` ni numéro de série d’adaptateur n’est présumé.

Les réglages concordent avec la
[notice du fabricant](https://www.cartelectronic.fr/documentation/Notice%20Module%20USBTICLC%20V2.pdf)
et le checksum avec la
[description Enedis du mode de contrôle n°2, §1.5.2](https://www.enedis.fr/media/2027/download).

La liste des essais acquis et restant à mener figure dans
[le rapport de validation](venus-validation.md). Les autres adaptateurs,
le mode historique et le triphasé ne sont pas validés par ces essais.
