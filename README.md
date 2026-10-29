# teleinfo-modbus-victron

[English documentation](README.en.md) · [Contribuer](CONTRIBUTING.md) · [Versions](CHANGELOG.md)

Pilote Python open source pour utiliser la **TIC standard d’un Linky monophasé**
comme compteur réseau Victron GX. Deux modes sont disponibles :

| Mode | Branchement USB | Fonctionnement | Guide |
| --- | --- | --- | --- |
| **D-Bus natif** | Directement sur le GX | Pilote local, mesures réseau et données TIC supplémentaires | [Installation GX](docs/gx-dbus.md#installation-sur-le-gx) |
| **Modbus TCP** | Sur un hôte Linux séparé | Serveur ABB B21 ou EM24 émulé ; le GX est client | [Debian / Docker](docs/deployment-debian.md) |

**[Version 0.4.0b1](https://github.com/macjl/teleinfo-modbus-victron/releases/tag/v0.4.0b1)** :
première version bêta du pilote D-Bus natif, destinée au **monitoring**.
Le fonctionnement sur plusieurs jours a été confirmé sur un Raspberry Pi 4
sous Venus OS **3.85**, sans modification des pilotes Victron existants.
Le retour terrain concerne une installation ; voir le
[rapport de validation](docs/venus-validation.md#suivi-sur-plusieurs-jours--publication-040b1).

Le mode D-Bus expose les énergies importées et injectées **au total et sur L1**,
avec un pas de **1 Wh**, les mesures électriques et les données de contrat,
tarif et diagnostic dans des [chemins supplémentaires](docs/gx-dbus.md).
Il publie aussi des [limites PowerGuard dynamiques](docs/gx-dbus.md#limites-powerguard-issues-du-contrat)
depuis `PCOUP` et la tension mesurée. **La puissance active reste estimée ;
l’ESS et la limitation automatique de la borne EV restent non qualifiés.**
Les données supplémentaires ne sont pas automatiquement affichées ou archivées par GX/VRM.

Le mode Modbus, décrit ci-dessous, conserve les profils ABB B21 et EM24 de
la [version 0.3.0a1](https://github.com/macjl/teleinfo-modbus-victron/releases/tag/v0.3.0a1).
Il fonctionne avec les pilotes Victron existants, sans ajout de pilote sur le GX.
Les deux modes fonctionnent sans MQTT. Serveur simulé,
lecteur USB, checksum, cohérence, expiration, reconnexion, YAML/environnement,
Docker et Prometheus facultatif sont implémentés. Les requêtes de découverte,
d’initialisation et de lecture d’un GX réel (Raspberry Pi 4, Venus OS 3.85)
ont été observées avec les profils EM24 puis ABB B21. **L’ABB est visible
sur l’installation de référence avec « Énergie inversée L1 » renseignée.** Le profil ABB
est aussi testé via TCP et audité contre le pilote officiel. La remontée VRM
et les essais de défaut restent suivis dans le
[rapport de validation](docs/venus-validation.md).

L'ABB B21 permet au pilote natif de renseigner les énergies importée et
injectée **au total et sur L1 depuis les mêmes registres**, avec une résolution
de 10 Wh. L'EM24 conserve une résolution de 100 Wh et ne renseigne pas
l'injection L1 dans son pilote Ethernet. Voir [l'audit ABB](docs/victron-abb-b21-audit.md).

**Puissance estimée : facteur W/VA appris depuis les index Wh**, selon une
méthode inspirée du routeur solaire F1ATB. Positive en soutirage, négative en
injection. Le mode TIC attend un apprentissage initial, puis corrige les VA
à chaque trame. L'historique cible **10 Wh ou 60 s**, au premier seuil atteint,
en conservant **15 s et 2 Wh minimum** ; le lissage s'adapte aux fenêtres courtes.
Ce n’est pas une mesure active instantanée. L’activation reste
explicite pour le monitoring expérimental. La fréquence est configurée.
**Usage ESS non qualifié.** Voir [la méthode et ses limites](docs/power-estimator.md).

**Limite constatée sur site :** un essai a relevé environ 667 VA pour 299 W
actifs moyens calculés sur deux minutes depuis les index Wh. L’estimation
VA ≈ W ne permet donc pas un monitoring actif précis sur cette installation ;
c’est l’ancienne méthode, désormais remplacée par l’estimation adaptative.
Voir le [diagnostic de précision](docs/power-accuracy.md).

## Démarrage Modbus avec simulation

Python 3.11 ou ultérieur, sous Linux :

```sh
git clone https://github.com/macjl/teleinfo-modbus-victron.git
cd teleinfo-modbus-victron
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[metrics]'
.venv/bin/teleinfo-modbus --config config.example.yaml --check-config
.venv/bin/teleinfo-modbus --config config.example.yaml
```

L’exemple écoute sur `127.0.0.1:1502`, Unit ID **1**. Dans un autre terminal :

```sh
.venv/bin/python -m teleinfo_modbus_victron.probe --host 127.0.0.1 --port 1502
```

Ce probe est un **client de diagnostic séparé** ; la passerelle reste serveur.
Il détecte le profil et lit les blocs du pilote GX. Utiliser `--profile abb_b21`
ou `--profile em24` pour choisir explicitement.

## Modbus : Linky réel et GX

Voir [le déploiement Debian et Docker](docs/deployment-debian.md) pour
l’identification du périphérique, les droits série et l’exposition sur TCP/502.
Le mode TIC exige `device` explicitement : aucun chemin USB n’est deviné.

Sur GX : **Paramètres → Intégrations → Périphériques Modbus → Rechercher**,
puis activer l’ABB B21 découvert et désactiver l'ancien EM24 lors d'une migration.
Vérifier le rôle **Grid / Réseau**
et le monophasé L1. Le serveur Modbus du GX est une fonction distincte de
son client. Voir [les réglages GX](docs/gx-setup.md).

## Modbus : données et défauts

- Champs requis : `VTIC=02`, `URMS1`, `IRMS1`, `SINSTS`, `SINSTI`, `EAST`, `EAIT`.
  Un champ d’injection absent ne devient pas implicitement zéro.
- Chaque réponse utilise un instantané immuable validé. Un défaut connu
  invalide les mesures ; sans nouvelle trame, elles expirent après
  `stale_after` secondes, **5 s par défaut**. Toute lecture touchant une mesure
  invalide reçoit l’exception Modbus **04**, jamais une ancienne valeur réussie.
- L’identité reste lisible pendant un défaut. Venus peut conserver temporairement
  son propre cache : son délai d’invalidation est une validation distincte.
- Pendant l’apprentissage, la source TIC peut être fraîche sans puissance
  disponible : les lectures de puissance et le bloc complet GX reçoivent 04.
  Le premier Wh partiel est écarté, puis au moins 2 Wh et 15 s sont requis.
  Après défaut ou changement de sens, l’apprentissage recommence.
- Conversion des énergies Wh en centièmes de kWh ABB : résolution de 10 Wh
  (100 Wh pour le profil EM24).
  Un compteur décroissant est rejeté jusqu’à résolution de la cause ou
  redémarrage explicite de la passerelle.
- Les autres groupes et leurs horodatages sont conservés en mémoire dans
  `extras`, sauf ADSC et PRM. Aucun registre constructeur supplémentaire n’est inventé.
  Aucune capture brute n’est enregistrée.
- Prometheus est désactivé par défaut. Les mesures physiques expirées sont
  omises ; la puissance estimée porte un nom explicite.

## Configuration et tests

Le mode D-Bus utilise [config.dbus.example.json](config.dbus.example.json),
avec les bibliothèques Python du firmware et son installateur dédié.
Pour Modbus, partir de [config.example.yaml](config.example.yaml). Les variables
`TIC_EM24_<NOM_DU_PARAMÈTRE>` remplacent les valeurs YAML, par exemple
`TIC_EM24_SOURCE=tic` ou `TIC_EM24_ALLOW_ESTIMATED_POWER=true`.
Un paramètre inconnu ou invalide empêche le démarrage.
L'exemple sélectionne `meter_profile: abb_b21`, série numérique `abb_serial: 10000001`.
`meter_profile: em24` rétablit l'ancien profil et utilise la série texte `serial`.
Le préfixe historique `TIC_EM24_` des variables reste valable pour les deux profils.

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python tools/check_upstream.py
```

Les tests couvrent les formats, trames, contrôles de cohérence, expiration,
reconnexion simulée, estimation adaptative, métriques et tous les registres via TCP. L’audit vérifie
les empreintes des [sources Victron figées](docs/upstream.json), les décodeurs,
l’initialisation et les blocs de lecture. Il accepte également
`--source-dir /chemin/vers/checkout-officiel` pour une exécution hors ligne.

Voir les audits [ABB B21](docs/victron-abb-b21-audit.md) et [EM24](docs/victron-em24-audit.md), l’[architecture](docs/architecture.md)
et l’[inventaire initial](docs/environment.md). La qualification ESS nécessitera
une mesure active fiable de référence et des essais de latence et de défaut.

Le mode D-Bus réutilise le lecteur et l’estimateur sans charger les bibliothèques
Modbus/YAML. Pendant le réapprentissage, il publie des watts provisoires avec
le dernier coefficient du même sens, ou 1 à défaut, depuis une TIC fraîche. Ses champs supplémentaires ne deviennent pas automatiquement
des graphiques VRM. Voir [le guide D-Bus](docs/gx-dbus.md).

Licence MIT. Projet indépendant de Victron Energy, ABB, Carlo Gavazzi et Enedis.
