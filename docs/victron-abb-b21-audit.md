# Profil ABB B21 natif Victron

## Objectif et référence

Le 26 octobre 2026, l'utilisateur a choisi de remplacer l'émulation EM24
par une émulation ABB B21, en modifiant uniquement la passerelle Debian.
Le pilote natif ABB renseigne import et injection à la fois au total et sur
L1, ce qui résout le champ absent de l'EM24 Ethernet dans l'interface GX.

Référence : [`abb.py` officiel](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/abb.py),
client 1.83, commit `fe12d8c9c30fab4310e16c10bbec0ced4ca9926f`.
Empreinte Git du fichier : `91314527270b54f87e041f137c4de90760a828e4`.
La recette publique de la branche de maintenance Venus b3.80 référence ce
même client ; le paquet effectivement installé sur le GX n'a pas été lu.
L'audit complet conserve les empreintes dans [upstream.json](upstream.json).

## Découverte et identité

- Transport accepté par le pilote : Modbus TCP ou RTU. Notre passerelle reste
  un serveur TCP ; aucun adaptateur RS485 supplémentaire n'est nécessaire.
- Modèle lu à `0x8960`, 2 registres, UInt32, mot fort d'abord :
  **0x42323120**, soit les caractères ASCII `B21 `.
- Le pilote sonde les Unit IDs 1 et 2 ; notre serveur répond uniquement à **1**.
- `/NrOfPhases = 1` est fixé par la classe ABB B21. Aucun faux registre de
  configuration de phases ou d'application EM24 n'est ajouté.
- Série numérique signée 32 bits à `0x8900` : **10000001** par défaut,
  synthétique, configurable par `abb_serial` et stable après redémarrage.
  Elle doit être unique entre passerelles. Elle n'est pas l'identifiant Linky.
- Firmware texte ASCII à `0x8908`, 8 mots : **TIC-0.3.0**, zéro complété.

## Registres lus

Les mots Modbus et les octets dans chaque mot sont envoyés fort d'abord.
Les échelles ci-dessous multiplient l'unité affichée pour obtenir l'entier brut.

| Adresse | Mots | Format | Échelle | Chemins créés par le pilote GX |
| --- | ---: | --- | ---: | --- |
| `0x8960` | 2 | UInt32 | 1 | Identifiant modèle |
| `0x8900` | 2 | Int32 | 1 | `/Serial`, converti en texte par le pilote |
| `0x8908` | 8 | ASCII | — | `/FirmwareVersion` |
| `0x5000` | 4 | UInt64 | 100 / kWh | `/Ac/Energy/Forward` et `/Ac/L1/Energy/Forward` |
| `0x5004` | 4 | UInt64 | 100 / kWh | `/Ac/Energy/Reverse` et `/Ac/L1/Energy/Reverse` |
| `0x5B00` | 2 | UInt32 | 10 / V | `/Ac/L1/Voltage` |
| `0x5B0C` | 2 | UInt32 | 100 / A | `/Ac/L1/Current` |
| `0x5B14` | 2 | Int32 | 100 / W | `/Ac/Power` et `/Ac/L1/Power` |
| `0x5B2C` | 1 | UInt16 | 100 / Hz | `/Ac/Frequency` |
| `0x5B3A` | 1 | Int16 | 1000 | `/Ac/PowerFactor` et `/Ac/L1/PowerFactor` |

La passerelle ne crée pas elle-même de chemins D-Bus : elle expose un index
par sens, et le pilote GX effectue les deux lectures/affectations du même
registre. Il n'y a ni duplication ni double comptage des kWh sur le fil.

Les index TIC sont convertis par division entière `Wh // 10`, soit une
résolution de **10 Wh**, contre 100 Wh en EM24. Les Wh originaux et
l'estimateur adaptatif sont inchangés. Le marqueur UInt64 tout à 1 est réservé
à l'invalidité ; aucun dépassement ne doit boucler silencieusement.

Le facteur de puissance instantané n'est pas fourni par la TIC. La passerelle
renvoie **0x7FFF**, marqueur invalide explicitement reconnu par le pilote ABB :
les deux champs de facteur de puissance deviennent indisponibles. Le rapport
W/VA appris reste un diagnostic de l'estimateur, pas une nouvelle mesure.

## Blocs, défauts et écritures

Le groupement du pilote officiel produit deux blocs de données :
**`0x5000 / 8 mots`** et **`0x5B00 / 59 mots`**. La série et le firmware sont
lus séparément pendant l'initialisation ; le bloc identité `0x8900 / 16 mots`
est également accepté. Les trous de ces blocs sont complétés avec des zéros
et n'ajoutent aucun chemin de phase L2/L3 au pilote.

Les mesures partagent les mêmes contrôles de fraîcheur que l'EM24. Une lecture
touchant une mesure périmée retourne Modbus 04. Pendant l'apprentissage,
les compteurs Wh restent lisibles si la TIC est fraîche, tandis que les
lectures de puissance et le bloc `0x5B00 / 59` retournent 04. L'identité reste
disponible, même sans TIC. Toutes les écritures sont refusées ; les requêtes
FC23 ne peuvent pas modifier un compteur.

Un seul profil est actif par processus. Le profil ABB refuse la découverte
EM24 à `0x000B`, afin de ne pas annoncer deux compteurs pour le même Linky.

## Vérification et état de validation

Les tests couvrent les vecteurs binaires, bornes, marqueurs invalides,
identité, chaque registre et bloc via TCP, atomicité des deux énergies,
expiration de chaque mot, apprentissage/reprise, signe export et protections
contre les écritures. La source simulée et la source TIC utilisent le même
modèle normalisé. Le profil EM24 reste testé séparément.

`tools/check_upstream.py` vérifie les 13 empreintes de sources, exécute les
définitions auditées du pilote sans dépendre des services D-Bus du GX,
compare les cartes de registres et leurs alias, puis décode des vecteurs connus.
Une vérification en lecture seule d'un serveur réel est disponible :

```sh
.venv/bin/python tools/check_upstream.py --abb-host 192.0.2.20 --port 502
.venv/bin/python -m teleinfo_modbus_victron.probe --host 192.0.2.20 --profile abb_b21
```

`192.0.2.20` est une adresse de documentation : la remplacer par l’adresse LAN
réelle de la passerelle.

Le 26 octobre 2026, l’utilisateur a confirmé sur son Raspberry Pi 4 sous
Venus OS 3.85 : **« ABB visible avec énergie inversée L1 renseignée »**.
Le contrôle TCP avec les décodeurs officiels retrouve des valeurs identiques
pour les chemins Total et L1 de chaque index. Cette validation concerne cette
installation ; voir le [suivi de validation](venus-validation.md).
La migration peut créer une nouvelle identité/service et une nouvelle instance
VRM ; la continuité des historiques VRM n'est pas présumée. Le rôle reste Grid.
**Usage ESS non qualifié**, comme pour l'ancienne émulation.
