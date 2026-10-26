# Validation de la passerelle et de Venus OS

## Limites PowerGuard D-Bus 0.4.0a3

Le 26 octobre 2026, la version 0.4.0a3 a été installée sur le GX de référence
(Venus OS 3.85). La configuration, l’identité et l’instance 43 ont été conservées.
Le service a repris les trames réelles puis l’estimation `tracking`.

Les **74 tests automatisés** passent. Les nouveaux cas couvrent le changement
de tension et de `PCOUP`, l’import/export, l’indépendance vis-à-vis de
l’apprentissage actif, les valeurs absentes/mal formées/hors limite, la tension
nulle, la désactivation configurable et l’expiration/rejet/déconnexion.

Un essai sur un **bus D-Bus isolé** du GX, avec sa bibliothèque réelle,
a vérifié :

- 9 kVA sous 232 V → 38,7931 A, puis sous 225 V → 40 A ;
- changement de contrat à 6 kVA sous 240 V → 25 A et plafond total de 6 000 W ;
- émission des notifications `ItemsChanged` lors du changement de courant ;
- refus des écritures sur les trois chemins dérivés ;
- `PCOUP` absent puis données expirées → limites invalides et `Active=0`.

Sur la TIC réelle, un relevé de **30 s** a compté **72 observations fraîches**,
avec `PCOUP=9 kVA`, `URMS1=232 V`, plafond total **9 000 W** et limite L1
**38,7931 A**, ainsi que `Active=1`. Toutes ces observations respectaient la
formule et disposaient d’une puissance publiée. La puissance réseau native
restait disponible dans `com.victronenergy.system`. La tension n’a pas changé
pendant ce relevé ; sa variation a été testée sur le bus isolé.

Le plafond en watts est une borne `P ≤ S`, pas une conversion exacte des VA
en watts. Le courant RMS par phase exprime la contrainte apparente en monophasé.
**La prise en compte automatique de ces chemins par EVCS, la limitation réelle
de la charge et son comportement à la perte TIC restent non vérifiés.** Aucun
réglage de la borne ni des autres services Victron n’a été changé.

## Repli provisoire D-Bus 0.4.0a2

La version 0.4.0a2 ajoute un repli configurable pendant l’apprentissage :
dernier facteur appris dans le même sens, ou 1 si inconnu, appliqué uniquement
aux VA d’une TIC fraîche. Le cœur de l’estimateur et les profils Modbus restent
inchangés. Les coefficients sont conservés en mémoire du processus, séparément
pour import et export ; les watts précédents ne sont jamais conservés comme
mesure de substitution.

Les **70 tests** couvrent les deux sens de transition, le retour aux facteurs
appris, la réutilisation du bon coefficient et les défauts. Un essai sur un
bus D-Bus isolé du GX, avec sa bibliothèque réelle et des données synthétiques,
a également vérifié ces transitions et l’expiration vers des valeurs invalides.

Le repli a été activé sur la TIC réelle. Un premier relevé de **50 s** a compté
**183 observations fraîches**, toutes avec une puissance publiée. Le statut
`warming_up_unity` et les indicateurs provisoire/calibré ont été lus. La
calibration était encore en attente en fin de ce relevé ; les inversions et
la faible énergie échangée peuvent prolonger ce régime. La disponibilité
continue ne constitue pas une validation de précision des watts provisoires.

Le pilote a ensuite retrouvé l’état `tracking` avec le marqueur provisoire à 0.
Un relevé complémentaire de **45 s**, comprenant **139 observations fraîches**,
a confirmé une puissance toujours disponible après reprise de la calibration.
Ce second relevé ne comportait pas d’inversion réelle ; les deux sens et les
coefficients en cache ont été vérifiés sur le bus isolé et dans les tests.

## Pilote D-Bus natif 0.4.0a1

Le 26 octobre 2026, le pilote a été installé sur le même Raspberry Pi 4 sous
Venus OS 3.85, avec l’USB TIC directement connecté au GX. Le firmware fournit
Python 3.12, pyserial, D-Bus, GLib et sa bibliothèque `velib_python` ; aucun
paquet système supplémentaire n’a été installé.

Les preuves acquises pour cette installation sont :

- service `com.victronenergy.grid.linky_tic` enregistré, instance distincte 43 ;
- trames réelles reçues, 46 groupes conservés hors ADSC/PRM ;
- état `tracking`, tension/courant et W estimés disponibles ;
- index Total/L1 identiques dans chaque sens, sans quantification Modbus ;
- reprise de la puissance réseau dans `com.victronenergy.system` et type générique 0 ;
- champs de contrat, période tarifaire et puissance de référence/coupure lisibles ;
- refus d’une écriture de puissance par un client D-Bus ;
- un seul processus propriétaire du port USB, règle udev ciblée `VE_SERVICE=ignore` ;
- essai avec source absente : `/Connected=0` et mesures natives/supplémentaires invalides ;
- restauration du chemin USB réel et reprise de l’estimation environ 28 s après
  redémarrage du service, avec identité et nom conservés ;
- restauration idempotente des liens du service et de la règle de démarrage.

Un essai supplémentaire sur **un bus D-Bus isolé du bus système**, utilisant
la bibliothèque du GX et notre modèle, a vérifié l’expiration réelle des
valeurs exportées vers le marqueur D-Bus invalide, ainsi que les pas de 1 Wh.
Aucun compteur synthétique n’a été publié sur le bus de production pour cet essai.
Les **66 tests automatisés** passent sur l’environnement de développement.

Le pilote natif est le seul service `grid` actif après migration. L’ancien
conteneur Modbus a été arrêté ; le code et la version `v0.3.0a1` restent disponibles.
La confirmation visuelle de l’interface GX, l’archivage VRM, le redémarrage complet
du GX et un cycle physique de débranchement USB restent à vérifier. Node-RED
n’a pas été activé ni configuré par cette installation. L’ESS reste non qualifié.

## Historique : passerelle Modbus 0.3.0a1

État au **26 octobre 2026**, version **0.3.0a1** : passerelle de monitoring
implémentée et déployée, avec TIC USB réelle et serveur Modbus TCP.
**La découverte native EM24 initiale, puis celle de l’ABB B21 avec
« Énergie inversée L1 » renseignée, ont été confirmées sur le GX de référence.**

Ces résultats concernent un Raspberry Pi 4 sous Venus OS **3.85** et un Linky
monophasé en TIC standard. Ils ne garantissent pas toutes les versions de
Venus OS et ne qualifient pas une utilisation ESS. La révision exacte du
paquet `dbus-modbus-client` installé sur le GX n’a pas été relevée.
L’audit de référence est figé dans [upstream.json](upstream.json).

Ce rapport est anonymisé : aucune adresse du LAN, identité Linky, capture brute
ou valeur absolue des index de l’installation n’est publiée.

## Essais logiciels

Les **58 tests automatisés** passent sous Python **3.11 et 3.13**, ainsi que
dans l’image Docker utilisée pour le déploiement. Ils couvrent :

- les deux profils ABB B21 et EM24, encodages, unités, signes et bornes ;
- l’identité, chaque registre et les blocs de lecture via TCP ;
- les écritures EM24 permises et le refus des écritures ABB ;
- le cadrage TIC, le checksum, les trames corrompues et la configuration ;
- la cohérence des mesures, la décroissance des index, l’expiration et la reprise ;
- l’estimateur adaptatif, ses fenêtres hybrides et son apprentissage ;
- l’export Prometheus facultatif, notamment l’omission des valeurs périmées.

L’outil `tools/check_upstream.py` vérifie **13 empreintes de sources Victron**,
exécute les définitions de registres auditées et compare les cartes, les alias
et les blocs de lecture aux deux profils. Un contrôle TCP en lecture seule
avec les classes de décodage officielles a aussi été effectué sur la passerelle.

## Essais réels acquis

| Preuve | Résultat |
| --- | --- |
| Acquisition USB | Trames TIC standard réelles, contrôles de checksum et cohérence acceptés |
| Accès réseau depuis GX | Connexions TCP établies et lectures du pilote natif observées |
| EM24 initial | Découverte, séquence d’initialisation et mesures visibles confirmées |
| Recréation du service | Reconnexion réelle du GX et reprise des lectures observées |
| ABB B21 | Découverte native et affichage confirmés après migration |
| Injection L1 ABB | Retour utilisateur : « ABB visible avec énergie inversée L1 renseignée » |
| Alias énergétiques ABB | Décodage officiel : import Total = L1 ; injection Total = L1 |
| Indices énergétiques | Import et injection conservés depuis EAST/EAIT, sans remise à zéro |

Le GX a sondé l’identité ABB, lu la série et le firmware, puis les blocs
`0x5000 / 8 mots` et `0x5B00 / 59 mots`. La migration a modifié uniquement
la passerelle Linux ; aucun fichier de Venus OS n’a été modifié.
La confirmation visuelle provient de l’utilisateur ; aucun accès D-Bus direct
n’a été utilisé pour la validation.

Après déploiement ABB, l’estimateur a atteint l’état `tracking` environ **28 s**
après le démarrage dans les conditions de cet essai. Un relevé Modbus de
**120 s**, avec une lecture toutes les 2 s, a obtenu **61 lectures disponibles
sur 61**. L’index d’injection a progressé de 30 Wh et l’index d’import est resté
constant. Les relevés détaillés restent locaux, exclus de Git par `*.local.json`.
Prometheus est resté désactivé ; aucun second lecteur n’a ouvert le port TIC.

## Estimation de puissance

Le diagnostic initial a montré l’écart entre VA et W, documenté dans
[le diagnostic de précision](power-accuracy.md). La méthode par défaut apprend
maintenant un rapport W/VA depuis les index Wh, selon une implémentation
indépendante inspirée de F1ATB.

L’historique cible **10 Wh OU 60 s**, au premier seuil atteint, avec les
minimums obligatoires **15 s ET 2 Wh**. Les essais synthétiques vérifient le
fonctionnement à plusieurs cadences et puissances, y compris à faible charge,
après inversion de sens et après défaut. Les observations réelles ont montré
les états d’apprentissage puis de suivi, ainsi que l’évolution des fenêtres.

Dans un scénario synthétique passant de 3 à 6 kW à VA constants, l’estimation
rejoint durablement une bande de ±5 % après environ 26 s, contre 74 s avec
une cible temporelle seule. Ce résultat ne constitue pas une spécification de
précision ou de latence sur toutes les charges réelles. Voir
[la méthode et ses limites](power-estimator.md).

## Validations restant à mener

| Point | Travail restant |
| --- | --- |
| VRM | Vérifier affichage, historique et continuité après changement d’identité |
| Précision active | Comparer à une référence fiable sur des fenêtres synchronisées, y compris les transitoires |
| Expiration côté GX | Mesurer la rétention de l’ancienne valeur et le retrait après défaut ; la passerelle est testée séparément |
| Déconnexion USB physique | Vérifier débranchement/rebranchement de bout en bout, notamment la recréation Docker si nécessaire |
| Redémarrage GX | Vérifier la redécouverte et la conservation du rôle sans doublon |
| Autres environnements | Tester d’autres versions de Venus OS, architectures et adaptateurs |
| ESS | **Non qualifié** ; campagne distincte nécessaire |

L’EM24 reste sélectionnable dans la même version du logiciel. L’ABB améliore
la résolution exposée des index de 100 à **10 Wh** et fournit l’injection L1
au pilote natif. Il ne change ni la résolution TIC de départ ni la précision
de l’estimateur. Les limites des deux profils sont détaillées dans les audits
[EM24](victron-em24-audit.md) et [ABB](victron-abb-b21-audit.md).
