# Pilote Linky TIC natif sur Venus OS

Le mode D-Bus lit l’adaptateur USB directement sur le GX. Il publie
`com.victronenergy.grid.linky_tic`, sans émuler un ABB ou un EM24 et sans
serveur Modbus. La passerelle Modbus de la version `v0.3.0a1` reste disponible
pour les installations avec un hôte Linux séparé.

## Données natives et données supplémentaires

| Donnée | Chemin | Traitement par Victron |
| --- | --- | --- |
| Puissance estimée totale / L1 | `/Ac/Power`, `/Ac/L1/Power` | Compteur réseau natif |
| Tension / courant L1 | `/Ac/L1/Voltage`, `/Ac/L1/Current` | Mesures natives |
| Import total / L1 | `/Ac/Energy/Forward`, `/Ac/L1/Energy/Forward` | Index natifs, kWh avec pas TIC de 0,001 kWh |
| Injection totale / L1 | `/Ac/Energy/Reverse`, `/Ac/L1/Energy/Reverse` | Index natifs, même résolution |
| Nom et identité | `/ProductName`, `/CustomName`, `/Serial`, `/DeviceInstance` | Appareil « Linky TIC », identité synthétique stable |
| État de connexion | `/Connected` | 0 si la TIC est absente ou expirée |
| Fréquence et facteur de puissance | `/Ac/Frequency`, `/Ac/PowerFactor` | Indisponibles : non mesurés par la TIC |

Le rendu exact de l’interface et l’arrondi des énergies dépendent de Venus OS.
Le pilote ne déclare pas la puissance active comme mesurée. Il conserve
[l’estimateur adaptatif](power-estimator.md), avec 10 Wh OU 60 s comme cible,
et 15 s ET 2 Wh minimum. Aucun gain de précision active ne découle du transport.

Avec `warmup_fallback: true` (défaut du mode D-Bus), les watts restent
publiés pendant l’apprentissage initial et après une inversion de sens.
Le pilote applique le **dernier coefficient appris dans ce même sens**,
ou **1** si aucun coefficient n’est connu : `P_provisoire = signe × VA × facteur`.
Les coefficients import/export sont distincts et conservés uniquement en mémoire,
pas après redémarrage du processus. Les coefficients provisoires et les bornes
`energy_limited` ne remplacent jamais un coefficient appris dans ce cache.

Dès que l’estimateur dispose de nouvelles données suffisantes, sa valeur reprend
automatiquement la main. Il continue d’apprendre selon les mêmes minimums.
Les diagnostics distinguent disponibilité et calibration :

| Chemin | Pendant le repli | Après apprentissage |
| --- | --- | --- |
| `/Tic/Status/PowerValid` | 1 : une estimation est publiée, sans garantie de précision | 1 |
| `/Tic/Status/PowerProvisional` | 1 | 0 |
| `/Tic/Status/PowerCalibrated` | 0 | 1 si un facteur a été appris |
| `/Tic/Status/State` | `warming_up_cached` ou `warming_up_unity` | `tracking` ou `energy_limited` |
| `/Tic/Estimator/FactorSource` | `cached` ou `unity` | `learned` ou `energy_limited` |

Le zéro apparent est publié directement comme zéro, sans repli provisoire.
Les facteurs précédents ne sont jamais réutilisés pour publier d’anciens watts :
une **nouvelle TIC fraîche et valide** est toujours requise. Une interruption
invalide la puissance et tous les autres champs physiques, même si un coefficient
reste en mémoire. Au retour de trames valides, un coefficient conservé peut
servir provisoirement pendant le nouvel apprentissage.

Le repli peut surestimer la puissance active, notamment avec le facteur 1.
Il ne constitue ni une mesure de cos phi, ni une qualification pour ESS.
Les champs natifs `/Ac/PowerFactor` restent invalides. Régler
`warmup_fallback: false` pour conserver des watts indisponibles pendant l’apprentissage.
Le comportement des profils Modbus reste inchangé.

Les chemins suivants constituent **notre API supplémentaire**, schéma 1,
pas des champs natifs automatiquement affichés ou archivés par GX/VRM :

| TIC | Chemin supplémentaire | Unité / sens |
| --- | --- | --- |
| `PREF` | `/Tic/Contract/ReferencePowerVA` | kVA TIC convertis en VA |
| `PCOUP` | `/Tic/Contract/CutoffPowerVA` | kVA TIC convertis en VA |
| `NGTF` | `/Tic/Contract/Name` | Nom du calendrier fournisseur |
| `LTARF` | `/Tic/Contract/CurrentTariff` | Libellé de la période active |
| `NTARF` | `/Tic/Contract/TariffIndex` | Numéro de l’index actif |
| `EASF01` à `EASF10` | `/Tic/Energy/Supplier01Wh` à `Supplier10Wh` | Index fournisseur, Wh |
| `EASD01` à `EASD04` | `/Tic/Energy/Distributor01Wh` à `Distributor04Wh` | Index distributeur, Wh |
| `SINSTS`, `SINSTI` | `/Tic/Power/ApparentImportVA`, `ApparentExportVA` | VA mesurés, séparés des W estimés |
| `STGE` | `/Tic/Status/Register` | Registre décodé depuis l’hexadécimal |
| Bits STGE 7, 6, 0 | `/Tic/Status/OverReferencePower`, `Overvoltage`, `DryContactClosed` | États 0/1 ; contact fermé = 1 |
| `RELAIS` | `/Tic/Status/Relays` | Masque des huit relais ; aucune commande envoyée |
| `SMAXSN`, `SMAXIN`, variantes `-1` | `/Tic/Power/MaxImportVA`, `MaxExportVA`, `PreviousMax…` | Maxima apparents avec horodatage |
| `CCASN`, `CCAIN`, variantes `-1` | `/Tic/History/ImportPointW`, `ExportPointW`, `Previous…` | Points historiques, jamais utilisés comme watts instantanés |
| `UMOY1` | `/Tic/Voltage/AverageL1V` | Tension moyenne historique |
| `NJOURF`, `NJOURF+1`, `PJOURF+1`, `PPOINTE` | `/Tic/Contract/CurrentDayProfile`, `NextDayProfile`, `NextDaySchedule`, `NextPeakSchedule` | Calendrier fournisseur |
| `ERQ1` à `ERQ4` | `/Tic/Energy/ReactiveQ1Varh` à `ReactiveQ4Varh` | Énergies réactives |
| `MSG1`, `MSG2` | `/Tic/Message/Short`, `Brief` | Messages reçus |

Chaque champ supplémentaire dispose d’un chemin enfant `/Timestamp`, contenant
son horodate TIC si elle existe. `/Tic/Raw` contient un objet JSON de tous les
groupes de la dernière trame validée, avec `value` et `timestamp`. `ADSC` et
`PRM` sont toujours exclus. Les horodates sont conservées telles que transmises,
y compris le marqueur saisonnier et le mode dégradé éventuel.

Le libellé tarifaire ne donne pas le prix en €/kWh. Les index doivent être
interprétés selon le contrat ; aucune association universelle HP/HC ou Tempo
n’est supposée. Un champ non reçu vaut invalide, même s’il existait auparavant.

Node-RED peut exploiter ces données avec une lecture D-Bus adaptée. Le nœud
Gridmeter standard ne liste pas nécessairement nos chemins supplémentaires.
Le pilote n’active pas Node-RED et ne crée pas de flow. Une publication D-Bus
n’est pas un archivage : un historique et un tableau de bord nécessitent une
configuration explicite. La prise en charge des chemins personnalisés via MQTT
ou VRM n’est pas présumée.

## Installation sur le GX

Installer depuis un checkout ou une archive contenant `tools`, `deploy/gx`,
le paquet Python et `config.dbus.example.json`. Copier ces fichiers sur le GX
et exécuter les commandes par SSH en root. Ne pas lancer de second lecteur USB.

```sh
ls -l /dev/serial/by-id/
python3 tools/install_gx.py \
  --device /dev/serial/by-id/REPLACE_WITH_OBSERVED_ADAPTER_ID \
  --instance 43 --no-start
```

Remplacer le chemin par celui **réellement observé** et choisir une instance
libre parmi les compteurs réseau. L’instance EV peut avoir le même numéro sans
collision de type, mais deux compteurs `grid` ne doivent pas partager l’instance.
L’instance et le nom sont ensuite stockés dans `com.victronenergy.settings`,
sous `/Settings/Devices/linky_tic/`. Une réinstallation conserve la configuration
et les réglages existants. Ne pas utiliser le numéro Linky comme identité publique.

L’installateur vérifie les bibliothèques fournies par le firmware (`serial`,
`dbus`, `gi` et `velib_python`). Aucun `pip install`, paquet système, Docker
ou remontage de la racine n’est nécessaire. La configuration JSON utilise les
modules présents même sur le Python allégé de Venus OS.

Il installe :

- `/data/dbus-linky-tic/releases/…` et le lien `app` vers un runtime complet ;
- `/data/dbus-linky-tic/config.json`, lisible uniquement par root ;
- un service daemontools et des logs tournants bornés dans `/var/log/dbus-linky-tic` ;
- une règle udev ciblée sur **le numéro de série USB de cet adaptateur**, pour
  empêcher les sondes GPS/VE.Direct de lire le même port ;
- un appel identifié dans `/data/rc.local`, préservant les autres commandes,
  pour restaurer les liens du service et la règle volatile après redémarrage.

La règle est restaurée dans `/run/udev/rules.d/`. Les fichiers des pilotes
Victron existants ne sont pas modifiés. L’installateur sauvegarde les anciens
réglages locaux dans `/data/dbus-linky-tic/backups/` lors des mises à jour.

Valider puis démarrer :

```sh
cd /data/dbus-linky-tic/app
python3 -m teleinfo_modbus_victron.dbus_app \
  --config /data/dbus-linky-tic/config.json --check-config
rm /data/dbus-linky-tic/service/down
svc -u /service/dbus-linky-tic
svstat /service/dbus-linky-tic
tail -n 30 /var/log/dbus-linky-tic/current | tai64nlocal
```

Le premier apprentissage peut prendre plusieurs dizaines de secondes, davantage
à faible puissance. `/Connected=1` signifie TIC fraîche ;
`/Tic/Status/PowerValid=1` indique séparément la disponibilité de l’estimation.

## Diagnostic et défauts

```sh
dbus -y com.victronenergy.grid.linky_tic /Connected GetValue
dbus -y com.victronenergy.grid.linky_tic /Ac/L1/Power GetValue
dbus -y com.victronenergy.grid.linky_tic /Tic/Contract/CurrentTariff GetValue
dbus -y com.victronenergy.grid.linky_tic /Tic/Status/State GetValue
```

Les mesures sont invalidées après `stale_after` (5 s par défaut), avec un
rafraîchissement D-Bus toutes les 250 ms. Les index, tarifs et données brutes
périmés deviennent aussi invalides ; l’identité reste visible, déconnectée.
Une trame rejetée ou une erreur série invalide immédiatement le magasin de
mesures, puis D-Bus le reflète au prochain rafraîchissement. L’absence d’octets
force la reconnexion série. Un échec inattendu du lecteur ou de la publication
termine le processus, relancé par daemontools. `/Tic/Status/SourceAgeSeconds`
reste un diagnostic d’âge, pas une mesure physique valide.

Le pilote n’écrit pas de données vers le Linky et n’ajuste ni le chargeur EV
ni les réglages ESS. `/Tic/Estimator/…` expose le facteur appris, la moyenne,
la fenêtre et son âge ; le facteur appris n’est pas un cos phi instantané.

## Migration et retour arrière

Après vérification des mesures natives, retirer **uniquement l’ancienne
passerelle** des périphériques Modbus configurés et arrêter son conteneur.
Conserver les autres appareils Modbus et les réglages historiques. L’instance
D-Bus peut différer de celle de l’ancien ABB ; la continuité VRM n’est pas acquise.

Pour arrêter durablement le pilote :

```sh
touch /data/dbus-linky-tic/service/down
svc -d /service/dbus-linky-tic
```

Pour rétablir les sondes série, retirer le lien
`/run/udev/rules.d/99-linky-tic.rules`, retirer l’appel de `boot.sh` dans
`/data/rc.local`, recharger les règles udev, puis rebrancher l’adaptateur.
Pour revenir à la passerelle Linux, déplacer l’USB, réactiver son conteneur
et son entrée Modbus. Conserver `/data/dbus-linky-tic` permet une reprise ultérieure.

## Références

- [API D-Bus Victron](https://github.com/victronenergy/venus/wiki/dbus-api)
- [Chemins des compteurs réseau](https://github.com/victronenergy/venus/wiki/dbus#grid-and-genset-and-acload-and-heatpump-meter)
- [Installation des pilotes et serial-starter](https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus)
- [Spécification TIC Enedis, §6.2](https://www.enedis.fr/media/2035/download)
