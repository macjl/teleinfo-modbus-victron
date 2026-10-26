# Validation de la passerelle et de Venus OS

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
