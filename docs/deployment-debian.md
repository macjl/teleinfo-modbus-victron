# Déploiement Debian et Docker

## Préparation du matériel

L’adaptateur USB doit être attaché à Linux, y compris au niveau de la VM.
Inventorier les périphériques sans supposer leur nom :

```sh
ls -l /dev/serial/by-id/
id
getent group dialout
```

Choisir le lien correspondant à l’adaptateur. Le lecteur utilise **9600 bauds,
7 bits, parité paire, 1 bit d’arrêt**, sans contrôle de flux ; il ne transmet
aucune commande au compteur. L’ouverture exclusive protège des accès par
les autres applications coopérantes. Fermer les moniteurs série.

## Docker Linux — simulation

Pour une nouvelle installation, copier `.env.example` vers `.env`, puis adapter
les valeurs. Le fichier `.env` est ignoré par Git et exclu de l’image.
Ne pas écraser un `.env` déjà configuré.

```sh
cp .env.example .env
docker compose up -d --build
docker compose logs --tail 30
```

Par défaut, le simulateur est accessible uniquement sur `127.0.0.1:502`.
L’application écoute sur 1502 dans le conteneur ; Docker publie le port 502.
Le conteneur s’exécute avec l’UID 10001, sans privilèges supplémentaires et
avec un système de fichiers en lecture seule.

## Docker Linux — Linky réel

Dans `.env`, régler :

- `MODBUS_BIND` : adresse IPv4 LAN de l’hôte joignable depuis le GX ;
- `TIC_DEVICE` : chemin stable observé dans `/dev/serial/by-id/` ;
- `TIC_DIALOUT_GID` : GID numérique du groupe propriétaire du port série.

Lancer avec les deux fichiers :

```sh
docker compose -f compose.yaml -f compose.tic.yaml up -d --build
docker compose -f compose.yaml -f compose.tic.yaml logs --tail 50
docker compose -f compose.yaml -f compose.tic.yaml exec bridge \
  python -m teleinfo_modbus_victron.probe --host 127.0.0.1 --port 1502
```

Le probe est seulement un client de contrôle. Il échoue si les mesures sont
absentes ou expirées. Le premier instantané peut nécessiter plusieurs secondes.
Le lecteur se reconnecte après erreur, avec une attente de 1 à 10 secondes.
Une absence d’octets au-delà du délai configuré force aussi la réouverture.

Le GX doit pouvoir joindre TCP/502 : même LAN ou route valide, pare-feu adapté.
Dans une VM, vérifier le réseau en pont ou la redirection ; l’adresse privée
du conteneur n’est pas celle à saisir dans le GX. Prévoir une réservation DHCP
pour l’hôte. Seuls le périphérique choisi et son groupe sont accordés au
conteneur ; le mode `privileged` n’est pas utilisé.

**Après un débranchement physique USB**, Docker peut conserver l’ancien numéro
de périphérique malgré le lien stable sur l’hôte. Si la reconnexion échoue
après rebranchement :

```sh
docker compose -f compose.yaml -f compose.tic.yaml up -d --force-recreate
```

Toujours conserver la même liste de fichiers pour les opérations suivantes :

```sh
docker compose -f compose.yaml -f compose.tic.yaml restart bridge
docker compose -f compose.yaml -f compose.tic.yaml stop
docker compose -f compose.yaml -f compose.tic.yaml down
```

`restart: unless-stopped` relance le conteneur après redémarrage de Docker si
l’USB est présent ; l’arrêt volontaire est respecté. Ne pas exécuter une
instance native et Docker simultanément sur le même adaptateur.

## Configuration personnalisée et Prometheus

Copier `config.example.yaml` vers `config.local.yaml`, puis utiliser un fichier
Compose local pour monter cette configuration sur `/app/config.yaml`.
Les variables `TIC_EM24_*` du service restent prioritaires. Les seuils
`max_voltage`, `max_current`, `max_apparent_power` sont configurables.
L'exemple et Docker sélectionnent le profil `abb_b21`. La série ABB est un
entier positif stable (`abb_serial`, 10000001 par défaut). Le paramètre texte
`serial` concerne uniquement le profil EM24. Le préfixe historique des variables
et des métriques reste `TIC_EM24_` / `tic_em24_` pour les deux profils.
Définir `METER_PROFILE=em24` dans le `.env` local permet de conserver le profil
initial avec la même image. Les étapes GX sont dans [le guide de migration](gx-setup.md).

L’image inclut Prometheus ; l’export reste désactivé jusqu’à activation :

```sh
docker compose -f compose.yaml -f compose.tic.yaml -f compose.metrics.yaml up -d
curl http://127.0.0.1:9108/metrics
```

Réutiliser alors les trois fichiers pour les autres opérations. L’export est
publié sur le loopback de l’hôte. Il expose validité, âge, compteurs de trames
et de connexions, ainsi que les mesures normalisées. Aucune identité Linky
n’est un label. La puissance s’appelle `tic_em24_power_estimate_watts`.
Les mesures expirées sont omises, avec `tic_em24_source_valid = 0`.
`tic_em24_power_estimate_valid` peut être nul alors que la TIC est fraîche :
l’estimateur apprend encore. Facteur, état, fenêtre énergétique et âge de
calibration sont détaillés dans [la documentation de l’estimateur](power-estimator.md).
Les mêmes diagnostics figurent dans les logs toutes les 30 s, sans activer
Prometheus. `power_method: apparent` rétablit explicitement l’ancienne méthode.
L'historique adaptatif cible 10 Wh ou 60 s, avec 15 s et 2 Wh minimum.
Le seuil en énergie se règle par `power_window_wh` ou
`TIC_EM24_POWER_WINDOW_WH`. Les diagnostics donnent la durée et les Wh de la
fenêtre réellement retenue, ainsi que la constante de lissage effective.

## Python natif

Debian doit disposer de Python et de venv ; installer `python3-venv` si nécessaire.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[metrics]'
cp config.example.yaml config.local.yaml
```

Dans `config.local.yaml`, sélectionner `source: tic`, définir `device`, l’adresse
`host` et `port`. Un port 1502 convient aux tests ; le scan GX standard cherche
TCP/502. Selon la configuration de Linux, ce port requiert un droit de liaison
à un port réservé. Le fichier [systemd fourni](../deploy/teleinfo-modbus.service)
accorde uniquement `CAP_NET_BIND_SERVICE` à l’utilisateur du service.

```sh
.venv/bin/teleinfo-modbus --config config.local.yaml --check-config
.venv/bin/teleinfo-modbus --config config.local.yaml
```

Pour un service natif permanent, installer le projet et le venv dans
`/opt/teleinfo-modbus-victron`, créer l’utilisateur système `teleinfo` avec accès
au groupe du port série, placer la configuration dans `/etc/teleinfo-modbus.yaml`,
puis installer l’unité dans `/etc/systemd/system/`. Adapter les chemins avant
`systemctl daemon-reload` et `systemctl enable --now teleinfo-modbus`.
Ce mode remplace le conteneur ; il ne constitue pas un second lecteur.

## Sens et provenance des valeurs

Puissance positive = import réseau, négative = export. Les index import/export
sont séparés et viennent d’EAST/EAIT. L’énergie est réellement comptée par
Linky, contrairement à la puissance instantanée estimée. CCASN/CCAIN sont
conservés avec leurs horodatages comme données historiques. La fréquence
configurée n’est pas une mesure du réseau.
