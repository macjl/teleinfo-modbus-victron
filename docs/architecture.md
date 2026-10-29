# Architecture implémentée

`Source simulée ou lecteur TIC → normalisation → estimation adaptative TIC → instantané validé → serveur ABB B21 ou EM24/PyModbus`

Le mode natif ajoute une autre sortie depuis le même modèle :
`lecteur TIC USB sur GX → instantané validé → service D-Bus grid + chemins /Tic/…`.
Le lecteur fonctionne hors de la boucle GLib ; seul le thread principal publie
sur D-Bus, par lots cohérents toutes les 250 ms. `config.py` ne charge PyYAML
que pour le mode Modbus ; le mode GX utilise JSON et les bibliothèques du firmware.
Voir [l’installation D-Bus et son API](gx-dbus.md).

## Composants

- `tic.py` : cadrage incrémental STX/ETX, abandon EOT, limite de 16 Kio,
  groupes standard séparés par tabulations, checksum incluant le dernier
  séparateur, horodatages conservés. Une erreur rejette toute la trame.
- `sources.py` : acquisition pyserial 9600 7E1, lectures hors de la boucle
  asyncio, réouverture après erreur ou silence, délai de reprise borné.
  Source simulée configurable en import/export, avec index et horodatages.
- `model.py` : unités normalisées, instantanés immuables, réception UTC et
  âge monotone, contrôles des limites et du sens, protection des compteurs.
  ADSC/PRM sont exclus ; les autres groupes valides restent dans `extras`.
- `em24.py` : contrat des 15 registres, conversions explicites, limites signées,
  mots faibles d’abord, texte ASCII, versions et énergie Wh vers 0,1 kWh.
- `abb_b21.py` : contrat B21, mots forts d'abord, compteurs UInt64 en 0,01 kWh,
  série numérique Int32, alias Total/L1 du pilote officiel et marqueur PF invalide.
- `registers.py` et `profiles.py` : formats numériques communs et sélection
  explicite d'un profil unique. La validation utilise les limites du profil choisi.
- `power.py` : facteur W/VA appris depuis les Wh, historique borné ciblant
  10 Wh OU 60 s avec 15 s ET 2 Wh minimum, intégration des VA, lissage adapté
  à la durée de fenêtre, apprentissage distinct par sens, limite sans nouveau
  Wh. Implémentation indépendante inspirée de F1ATB ; voir [la méthode](power-estimator.md).
- `server.py` : **serveur** Modbus TCP PyModbus 3.16.1, `SimDevice` et callback
  `action`, Unit ID 1. ABB : FC03 et refus des écritures ; EM24 : FC03/06/16
  pour sa configuration uniquement. Protection des mesures, des unités et FC23.
- `config.py` : paramètres typés, YAML puis variables `TIC_EM24_*` prioritaires,
  refus des clés inconnues et obligation d’accepter le mode d’estimation.
- `dbus_model.py` : rendu des chemins réseau natifs et TIC, repli de puissance
  par sens, limites PowerGuard et invalidation depuis un instantané frais.
- `dbus_app.py` : acquisition dans un thread séparé, publication D-Bus par lots
  sur GLib, identité persistante et supervision du lecteur.
- `metrics.py` : Prometheus facultatif du mode Linux/Modbus, validité et âge de source, compteurs,
  omission des mesures expirées. Les valeurs estimées sont nommées comme telles.
- `app.py` : démarrage, signaux, arrêt coordonné. Une exception fatale de source
  termine le service au lieu de laisser un serveur sans acquisition.
- `probe.py` : client de diagnostic indépendant ; aucun rôle client dans
  l’acquisition ou dans le serveur de la passerelle.

## Validité et cohérence

Seules les trames complètes avec tous les groupes corrects sont normalisées.
L’absence de SINSTI ou EAIT ne signifie pas zéro. Une erreur connue invalide
l’instantané ; la dernière base acceptée reste uniquement pour le contrôle
ultérieur des compteurs. Sans nouveau signal valide, la source expire au
bout de 5 s par défaut. L’identité seule ne prolonge jamais la validité.

Une lecture touchant même un seul mot d’une mesure invalide reçoit l’erreur
Modbus 04. Les requêtes d’identité isolées restent possibles. L’ensemble d’une
réponse est construit à partir d’un seul instantané sans point de suspension
asyncio pendant son encodage. Les adresses intermédiaires des blocs audités
sont acceptées ; les lectures hors de ces blocs sont refusées.

Le pilote GX est responsable de son cache propre : une erreur Modbus ne
supprime pas instantanément son dernier affichage. Le délai d’invalidation
réel doit encore être mesuré. Une déconnexion USB Docker peut nécessiter
une recréation du conteneur si son numéro de périphérique a changé.

## Limites et suite

La puissance TIC utilise désormais un facteur W/VA adaptatif appris depuis les Wh.
Sans apprentissage disponible, le bloc Modbus de lecture GX retourne 04. Le mode
D-Bus peut publier un repli provisoire avec le dernier facteur du même sens ou 1,
uniquement depuis une TIC fraîche, avec des indicateurs de qualité distincts. L’ancienne
approximation reste sélectionnable avec `power_method: apparent`. La simulation
fournit directement sa puissance. La fréquence est nominale/configurée.
Les index d’énergie sont mesurés par le Linky mais
exposés avec une résolution de 10 Wh en ABB, ou 100 Wh en EM24. CCASN/CCAIN ne sont pas utilisés
comme mesure instantanée. Le profil est strictement monophasé.

Les tests couvrent le TCP, le rendu D-Bus, l’estimateur et les défauts simulés.
Le matériel réel et le pilote D-Bus sur plusieurs jours ont été éprouvés ; voir
[le rapport de validation](venus-validation.md). Restent la validation visuelle
VRM, les pertes/reprises réelles de bout en bout et la qualification ESS.
La détection EM24 initiale, puis celle de l’ABB avec l’énergie inversée L1
renseignée, sont confirmées par l’utilisateur sur le Raspberry Pi 4 sous Venus OS 3.85.
L’Enphase Envoy-S reste une source possible de comparaison, à vérifier quant
à son point de mesure, sa précision et sa latence. Aucun MQTT n’est prévu.
