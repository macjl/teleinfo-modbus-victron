# Audit Victron EM24 Ethernet — jalon 1

## Référence et périmètre

Audit du 25 octobre 2026 sur `victronenergy/dbus-modbus-client`, version 1.83,
commit [`fe12d8c9c30fab4310e16c10bbec0ced4ca9926f`](https://github.com/victronenergy/dbus-modbus-client/tree/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f).
Les empreintes des 12 fichiers consultés figurent dans [upstream.json](upstream.json).
La version effectivement installée sur le GX reste à relever : ce commit
n’implique pas que toutes les versions de Venus OS se comportent ainsi.

Sources principales :

- [carlo_gavazzi.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/carlo_gavazzi.py) : modèle, registres, initialisation.
- [register.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/register.py) : formats et facteurs d’échelle.
- [probe.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/probe.py), [scan.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/scan.py) : détection et scan.
- [device.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/device.py) : regroupement, cycles de lecture, D-Bus et rôle.
- [dbus-modbus-client.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/dbus-modbus-client.py), [utils.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/utils.py), [client.py](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/client.py) : réseau, activation, erreurs et accès Modbus.

Les constats ci-dessous proviennent de la lecture et de l’exécution ciblée de
ces sources. Aucun échange TCP avec un GX n’a été effectué.

## Découverte réseau

1. `NetClient.new_scanner()` lance `NetScanner` sur le port **502**.
   Le scanner essaie TCP et UDP, mais le handler EM24 est limité à **TCP**.
2. `get_networks()` utilise les réseaux IPv4 des interfaces actives ayant une
   adresse de portée globale ; `ap0` est exclue. Le scanner parcourt les hôtes
   des sous-réseaux locaux, en excluant les propres adresses du GX. Il utilise
   huit workers et un timeout de scan de 0,25 s.
3. Pour l’EM24, `ModelRegister` lit le holding register **0x000B**, quantité 1,
   **Unit ID 1**. `BaseDevice.default_access = 'holding'` et `client.py`
   utilisent donc **FC03**, pas FC04. Toutes les adresses sont les offsets PDU,
   sans ajout de 1 ni de préfixe 40001.
4. La valeur **1648** sélectionne `EM24DINAV23XE1X` / `EM24_Meter`.
   Les modèles 1649 à 1653 sont aussi connus du pilote ; notre profil vise 1648.
   Le product ID D-Bus est **0xB017**, distinct du model ID Modbus.
5. La découverte ne suffit pas : le client appelle ensuite `dev.init()`.
   Une erreur pendant l’initialisation empêche l’ajout normal du compteur.

`NetClient` initialise `auto_scan` à faux, avec persistance dans
`/Settings/ModbusClient/tcp/AutoScan`. Le scan initial dépend des paramètres
existants, de la liste de dispositifs et de l’option de scan forcé. Il ne faut
donc pas promettre une découverte automatique immédiate sans vérifier le GX.
La liste persistée est `/Settings/ModbusClient/tcp/Devices` ; le format d’une
cible est `tcp:ADRESSE:PORT:UNIT`, par exemple `tcp:192.0.2.10:502:1`.

Le module EM24 n’enregistre **aucun service mDNS**. Les modules Victron EM et
P1Link enregistrent leurs propres services UDP ; les imiter n’est pas requis
pour le scan EM24. La voie retenue est une adresse LAN joignable sur TCP/502,
puis le scan réseau natif. Un port 1502 convient aux tests locaux mais ne sera
pas trouvé par ce scan standard. En Docker Linux, prévoir une publication
`502:1502` sur l’adresse LAN de l’hôte, ou un réseau hôte avec écoute sur 502.
La topologie réelle de la VM et la joignabilité depuis le GX restent à tester.

## Initialisation et publication

Séquence de `EM24_Meter.device_init()` :

1. Lire `0xA000`. Si différent de 7, écrire **7** (application H), puis relire.
   Le helper émet **FC06** pour une écriture d’un registre. Si la relecture
   n’est pas 7, le pilote journalise un échec et abandonne ce chemin normal.
2. Lire séparément les informations, dans cet ordre : `0x0302` (1 registre),
   `0x0304` (1), `0x1002` (1), `0x5000` (7).
3. Interpréter `PhaseConfig = 3` comme **1P**. La table du pilote est
   `[3, 3, 2, 1, 3]` phases pour les configurations 0 à 4.
4. Créer les registres globaux puis ceux de L1. Aucun registre L2/L3 ni
   `PhaseSequence` n’est requis pour cette configuration.
5. Initialiser les paramètres du dispositif, le rôle et le service D-Bus ;
   ajouter les informations, les mesures et `/NrOfPhases = 1`.

`EnergyMeter` définit le rôle par défaut **grid**, instance par défaut **40**.
Pour un numéro de série stable `TIC00000000001`, le service attendu est
`com.victronenergy.grid.cg_TIC00000000001`, sous réserve du rôle et des
paramètres persistés. `/Connected` est initialisé à 1 lors de la publication.
L’apparition sur GX/VRM reste à constater sur le système réel.

Le numéro de série sert d’identifiant de service et de clé de paramètres :
le garder stable, unique et limité aux caractères portables. Les versions
émulées devront décrire la passerelle et être documentées comme synthétiques.

## Contrat des registres monophasés

Le facteur indique **valeur brute = valeur affichée × facteur**.
`s32l` occupe deux registres signés 32 bits, mot faible d’abord.
R = lecture ; R/W = écriture annoncée ou nécessaire au pilote.

| Adresse | Nombre | Format | Facteur / unité affichée | Valeur ou fonction | Accès |
| --- | ---: | --- | --- | --- | --- |
| `0x000B` | 1 | u16 | 1 | Modèle 1648 | R |
| `0x1002` | 1 | u16 | 1 | PhaseConfig 3 = 1P | R/W |
| `0xA000` | 1 | u16 | 1 | Application 7 = H | R/W |
| `0x0302` | 1 | version | 4/4/8 bits | HardwareVersion | R |
| `0x0304` | 1 | version | 4/4/8 bits | FirmwareVersion | R |
| `0x5000` | 7 | texte ASCII | 14 octets | Serial | R |
| `0x0000` | 2 | s32l | 10 / V | Tension L1 | R |
| `0x000C` | 2 | s32l | 1000 / A | Courant L1 | R |
| `0x0012` | 2 | s32l | 10 / W | Puissance L1 | R |
| `0x0028` | 2 | s32l | 10 / W | Puissance totale | R |
| `0x0033` | 1 | u16 | 10 / Hz | Fréquence | R |
| `0x0034` | 2 | s32l | 10 / kWh | Énergie importée totale | R |
| `0x004E` | 2 | s32l | 10 / kWh | Énergie exportée totale | R |
| `0x0040` | 2 | s32l | 10 / kWh | Énergie importée L1 | R |
| `0xA100` | 1 | u16 | 1 | Sélecteur : 0=kVARh, 1=2, 2=1, 3=Locked | R |

`Reg_ver` décode `major = v >> 12`, `minor = (v >> 8) & 15`,
`patch = v & 255`. Exemple : `0x1222` donne `1.2.34`.
Le texte place le premier caractère dans l’octet fort du premier mot et
retire les octets NUL de fin. Il ne suit pas l’ordre des mots des nombres.

Exemples de représentation :

- 230,1 V → brut 2301 → mots `[0x08FD, 0x0000]`.
- −1234,5 W → brut −12345 → mots `[0xCFC7, 0xFFFF]` ; octets TCP `CF C7 FF FF`.
- EAST 12 345 678 Wh → brut `EAST // 100 = 123456` → mots
  `[0xE240, 0x0001]` → 12 345,6 kWh dans Venus.

Les octets de chaque registre Modbus restent transmis fort d’abord.
Le décodage officiel `('<i', '<2H')` signifie mot faible d’abord, sans inversion
des octets sur le réseau. La quantification des énergies est de 100 Wh ;
tronquer les compteurs positifs évite de créer de l’énergie. Saturation et
débordement doivent devenir des erreurs, jamais un retour à zéro implicite.

Le pilote annonce `PhaseConfig` modifiable entre 0 et 4 et programme une
réinitialisation après une écriture D-Bus. Notre future implémentation 1P
devra accepter 3 et refuser explicitement les autres configurations tant que
les registres correspondants ne sont pas pris en charge. C’est une limite
du profil émulé, à tester dans l’interface GX. Pour l’application, accepter et
relire 7 ; tester le chemin où la valeur initiale est différente de 7.
Le choix prévu du sélecteur est 3 (Locked), purement synthétique et en lecture.

## Regroupement des lectures : exigence pour le serveur

`BaseDevice.pack_regs()` optimise les lectures. Pour TCP, le coût calculé est
61 octets et le trou maximal admis est `(61 + 1) // 2 = 31` registres,
avec au plus 125 registres par requête.
Le jeu 1P est donc lu en deux blocs :

| Départ | Quantité | Fin incluse | Usage |
| --- | ---: | --- | --- |
| `0x0000` | **80** | `0x004F` | Toutes les mesures de L1 et globales |
| `0xA100` | 1 | `0xA100` | Position du sélecteur |

Le serveur devra accepter les adresses intermédiaires dans le premier bloc.
Les zones de remplissage pourront contenir zéro, en préservant le model ID
à `0x000B`. Ne pas étendre cette tolérance à toute la plage d’adressage.
Une réponse doit provenir d’un instantané cohérent : puissance L1 = totale,
énergie importée L1 = totale en 1P, et aucun mélange de trames entre mots.

Les puissances ont une durée de cache pilote de 1 s ; les autres registres
ont 4 s. La lecture groupée est déclenchée dès qu’un registre du bloc expire,
mais chaque valeur est décodée selon sa propre durée de cache. La boucle
principale est appelée toutes les 100 ms : ce n’est pas une garantie de
nouvelle mesure toutes les 100 ms. Le timeout minimal EM24 est 0,5 s après
détection, ajusté selon la latence.

## Expiration et limites de mesure

Les `Reg_s32l` utilisés ici n’ont **aucune sentinelle invalide configurée**.
Ni `0x80000000`, ni zéro, ni une ancienne mesure répétée ne signalent donc
correctement un défaut au pilote. Décision pour le serveur du jalon 2 : refuser
toute lecture de mesures absentes, incohérentes ou expirées avec une exception
Modbus de défaut serveur (04), tout en permettant les lectures d’identité
isolées. Vérifier aussi les lectures partielles de mots de mesure.

Le client Venus conserve ses valeurs en cache et son service peut subsister
pendant les échecs. Dans ce commit, `update_device()` retire le dispositif
après plus de 5 s sans mise à jour réussie ; les reprises des dispositifs
échoués sont tentées avec un intervalle de 10 s. Ces durées s’ajoutent aux
timeouts et à la cadence de boucle. L’exception n’assure pas une invalidation
immédiate de l’affichage GX : mesurer la durée réelle de rétention avant tout
usage de commande. La passerelle ne devra jamais renvoyer de mesure périmée
dans une réponse Modbus réussie.

`SINSTS` et `SINSTI` sont des VA, pas des W. Leur différence ne devient pas
une mesure active du fait de son exposition dans `/Ac/Power`. Il faudra un
mode d’estimation explicitement activé et décrit pour le monitoring.
`URMS1`, `IRMS1`, `EAST` et `EAIT` ont des significations différentes des
puissances et restent des mesures indépendantes ; ne pas reconstruire le
courant à partir de l’estimation de puissance.

La fréquence n’est pas disponible dans les champs TIC retenus. Une fréquence
nominale configurée, par exemple 50 Hz, devra être marquée comme **hypothèse**
dans la configuration, les logs et la documentation. Le profil EM24 ne permet
pas de transmettre cette provenance par le registre lui-même. Une source
active externe fiable sera préférable pour une qualification ESS ultérieure.

## Preuves du jalon

- 8 tests unitaires hors ligne : vecteurs d’encodage des registres, signe,
  ordre des mots et octets, bornes, valeurs non finies, Wh/kWh, versions, série.
- `tools/check_upstream.py` vérifie les 12 empreintes et utilise les vraies
  définitions du pilote pour comparer la découverte, les deux chemins
  d’initialisation de l’application, la table 1P, les blocs de lecture et
  les décodeurs. Les dépendances D-Bus sont remplacées pour cet audit ciblé.
- Aucune preuve de serveur TCP, acquisition TIC, GX, VRM ou ESS à ce stade.
