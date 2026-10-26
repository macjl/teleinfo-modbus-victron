# Réglages Victron GX

Le GX est **client Modbus TCP** ; la passerelle Linux est **serveur**.
Aucun paquet, script ou pilote personnalisé n’est à installer dans Venus OS.

| Paramètre | Valeur |
| --- | --- |
| Adresse serveur | Adresse LAN de l’hôte Linux |
| Port | **502 TCP** |
| Unit ID / Adresse Modbus | **1** |
| Modèle annoncé | **ABB B21 Energy Meter**, identifiant `0x42323120` |
| Phases | **1P / L1**, fixées par le pilote B21 |
| Numéro de série | **10000001** par défaut (`abb_serial`) |
| Rôle | **Grid / Compteur réseau** |
| Nom conseillé | **Linky TIC — estimation** |

Installation de référence validée : GX Raspberry Pi 4 sous Venus OS **3.85**.
Utiliser les adresses de votre propre LAN ; aucune n’est codée dans Python.
Choisir une série émulée unique et stable pour chaque passerelle.

## Dans la console GX

1. Lors d'une migration, désactiver l'ancien **Carlo Gavazzi EM24** à cette
   adresse dans les périphériques Modbus, afin de conserver un seul compteur
   réseau actif pour le Linky. L'ancien profil n'est plus servi sur cette IP.
2. **Paramètres → Intégrations → Périphériques Modbus**. Dans certaines
   interfaces : **Paramètres → Périphériques Modbus TCP/UDP**.
3. Activer le scan automatique puis lancer **Rechercher des appareils / Scan**.
4. Repérer l'**ABB B21**, série **10000001**, à l’adresse de la passerelle parmi les appareils découverts
   ou enregistrés ; l’activer si une option est proposée.
5. Ouvrir le compteur dans la liste des appareils. Vérifier **Grid / Réseau**
   comme rôle et **monophasé L1**. La TIC mesure l’échange au point réseau ;
   elle ne représente pas la seule production Enphase.
6. Le nommer **Linky TIC — estimation** et vérifier tension, courant, puissance,
   **Énergie L1** et **Énergie inversée L1**. L'injection provient d'EAIT et
   correspond au surplus exporté, pas à la production solaire totale.
   La fréquence affichée est configurée ; le facteur de puissance instantané
   est indisponible, car il n'est pas mesuré par la TIC.

Les champs d’ajout manuel IP/port/Unit ID ne sont pas proposés dans toutes les
interfaces. S’ils le sont, utiliser les valeurs du tableau. L’adresse à saisir
est celle de la passerelle, pas celle du GX.

**« Serveur Modbus TCP » du GX est une autre fonctionnalité**, destinée aux
clients qui lisent le GX. Son activation n’est pas nécessaire pour que son
client lise l'ABB. MQTT n’intervient pas ici.

Références : [menus GX officiels](https://www.victronenergy.com/media/pg/Cerbo_GX/en/configuration.html)
et [pilote ABB officiel](https://github.com/victronenergy/dbus-modbus-client/blob/fe12d8c9c30fab4310e16c10bbec0ced4ca9926f/abb.py).

## Identité, diagnostic et retour à l'EM24

Le B21 utilise une identité numérique différente de l'ancienne série EM24
`TIC00000000001`. Son activation peut créer un nouveau service et une nouvelle
instance de compteur dans VRM ; la continuité de l'ancien historique n'est
pas présumée. Les compteurs d'énergie eux-mêmes restent les index absolus
du Linky, désormais transmis par pas de 10 Wh au lieu de 100 Wh.

Les lectures `0x8960 / 2`, `0x8900 / 2`, `0x8908 / 8`, puis `0x5000 / 8`
et `0x5B00 / 59` correspondent au parcours du pilote B21. Des lectures de
puissance seules `0x5B14 / 2` sont également possibles. L'audit détaille les
[registres et les alias Total/L1](victron-abb-b21-audit.md).

Pour revenir au profil EM24 avec le nouveau logiciel :

```sh
METER_PROFILE=em24 docker compose -f compose.yaml -f compose.tic.yaml up -d
```

Réactiver alors l'ancien EM24 dans GX et désactiver l'ABB. Pour rendre le
choix permanent, définir `METER_PROFILE=em24` dans le `.env` local. En Python
natif, utiliser `meter_profile: em24` et la série texte `serial`.
L'EM24 conserve son modèle 1648, application 7 et PhaseConfig 3 ; son champ
d'injection L1 reste absent du pilote natif Ethernet.

## Contrôle et limites

Une même instance VRM/D-Bus peut être utilisée par des types différents :
`grid:40` pour le Linky et `evcharger:40` pour un chargeur EV ne se confondent
pas. Deux dispositifs du même type doivent avoir des instances distinctes.
Ces instances sont indépendantes de l’Unit ID Modbus **1**.
Voir la [règle officielle des instances VRM](https://www.victronenergy.com/media/pg/Ekrano_GX/en/vrm-portal.html#vrm-device-instances).

Les échanges Modbus ne prouvent pas à eux seuls l'affichage GX ou la remontée VRM.

La puissance active est estimée par apprentissage du rapport W/VA depuis les
index Wh (méthode inspirée de F1ATB). Aucun réglage GX supplémentaire n’est
nécessaire. Au démarrage, après défaut et après changement de sens, la puissance
est temporairement indisponible pendant l’apprentissage. Voir [la méthode](power-estimator.md).
**Usage ESS
non qualifié** : un affichage réussi ne constitue pas une qualification de
régulation. Mesurer aussi le délai pendant lequel Venus conserve son ancienne
valeur lors d’un défaut. Si un autre compteur pilote déjà un ESS, ne pas
modifier sa sélection au profit de cette source expérimentale.
