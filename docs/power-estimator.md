# Estimation active adaptative depuis la TIC

## Référence F1ATB

L'algorithme s'inspire du routeur solaire de **F1ATB (André)**, fichier
[`Source_Linky.ino`, commit b55f0c8b3ef68e051ae02030e88b2dbc9eb8bb74](https://github.com/F1ATB/Solar-Router-F1ATB/blob/b55f0c8b3ef68e051ae02030e88b2dbc9eb8bb74/Source_Linky.ino),
consulté le 26 octobre 2026 ; empreinte Git du fichier
`e84a370f3c4fe91141f95300dfcf14da3be95e9e`.

Son principe est de dériver les index Wh, filtrer la puissance moyenne,
apprendre le rapport W/VA, puis multiplier les VA courants par ce rapport.
Il distingue import et injection et limite la puissance quand l'index reste
inchangé, avec une marge de 1,3 Wh. Il appelle ce rapport `COSphi` ; nous
utilisons « facteur de puissance estimé », car ce rapport n'est pas forcément
le seul cosinus du déphasage pour des charges non sinusoïdales.

Notre code Python est une implémentation indépendante de ces principes,
sans incorporation du code du firmware. Ce n'est pas une reproduction
numérique exacte du filtre F1ATB. Différences : fenêtre glissante hybride Wh/temps,
intégration temporelle des VA, filtre indépendant de la cadence des trames,
apprentissage initial explicite, remise à zéro sur défaut ou changement de
sens. Le cœur de l’estimateur signale explicitement un apprentissage absent.
Le mode D-Bus peut publier une estimation provisoire avec le dernier coefficient
du même sens, ou 1 à défaut, sans modifier cet apprentissage ; les indicateurs
de disponibilité et de calibration sont séparés. Voir [le guide D-Bus](gx-dbus.md).

## Calcul et délai

Pour chaque sens, le premier changement d'index initialise une borne :
la première fraction de Wh, dont la durée est inconnue, est ainsi écartée.
Entre deux bornes, sur une fenêtre glissante cible de **10 Wh OU 60 secondes,
au premier seuil atteint**, en imposant toujours **15 secondes ET 2 Wh minimum** :

```
P_energie_moyenne = 3600 * delta_Wh / duree_secondes
facteur_candidat = borne_0_1(3600 * delta_Wh / integrale_VA_secondes)
P_estimee_courante = signe * facteur_filtre * VA_courants
```

L'intégrale des VA utilise les trapèzes entre trames reçues ; elle ne multiplie
pas les anciennes énergies par les seuls VA de la dernière trame. Les anciennes
bornes sont retirées tant que la fenêtre restante respecte les deux minimums
et atteint au moins une des deux cibles. Les bornes sont des changements d'index
observés, sans interpolation : la fenêtre peut dépasser le seuil d'un intervalle
entre bornes. Au démarrage, une première estimation est permise dès que les
minimums sont réunis ; l'historique grandit ensuite jusqu'à sa cible.

À puissance active constante P, la durée recherchée est approximativement :

```
T_fenetre = max(15, 3600 * 2 / abs(P), min(60, 3600 * 10 / abs(P)))
```

| Puissance active stable | Durée cible approximative |
| --- | ---: |
| 7 000 W | 15 s : le minimum temporel prime |
| 3 000 W | 15 s : le minimum temporel prime |
| 1 000 W | 36 s : la cible de 10 Wh prime |
| 300 W | 60 s : la cible temporelle prime |
| 100 W | 72 s : les 2 Wh minimum priment |
| 50 W | 144 s : les 2 Wh minimum priment |

Ces durées concernent l'historique après la première borne, sans le délai
initial ni celui du lissage. Elles ne sont pas une garantie de convergence.

Le facteur est lissé avec `alpha = 1 - exp(-delta_t / tau_effectif)` :

```
tau_effectif = power_smoothing_seconds * sqrt(min(1, duree_fenetre / power_window_seconds))
```

Avec les défauts, tau passe de 15 s pour une fenêtre d'au moins 60 s à **7,5 s
pour 15 s d'historique**. Ce compromis raccourcit le retard tout en atténuant
les oscillations dues aux pas de 1 Wh. Des fenêtres plus courtes peuvent rester
plus bruitées que l'ancienne fenêtre temporelle seule.

La première estimation demande au moins 15 s et **2 Wh supplémentaires après
la première borne**. À charge stable de 300–400 W, cela prend généralement
quelques dizaines de secondes. La fenêtre peut dépasser 60 s à faible charge
pour réunir les 2 Wh. L'historique est borné en nombre d'entrées.

Après apprentissage, l'estimation suit les nouveaux VA à chaque trame.
Sans changement d'index, elle est limitée par `1,3 * 3600 / secondes_depuis_borne`.
Cette borne est une heuristique sur l'énergie moyenne ; elle ne garantit pas
la puissance instantanée après un changement de charge. Le facteur est borné
entre 0 et 1 et `abs(P_estimee) <= VA_courants`.

Quand les VA sont nuls, l'estimation vaut immédiatement zéro. Un changement
de sens, une trame rejetée, une déconnexion ou un intervalle de réception
atteignant `stale_after` efface l'apprentissage. Les compteurs ne sont jamais
remis à zéro : leur décroissance reste rejetée. Un incrément incompatible
avec le temps et les VA est aussi rejeté, avec une tolérance de 2 Wh pour la
quantification et les mises à jour décalées des groupes.

## Modbus, configuration et diagnostic

`power_method: adaptive` est le défaut pour la source TIC. La simulation fournit
directement la puissance configurée, sans apprentissage. Le choix explicite
`power_method: apparent` rétablit l'ancienne approximation `SINSTS - SINSTI`.
Les cinq réglages sont dans `config.example.yaml` et peuvent être remplacés
par les variables `TIC_EM24_POWER_*` correspondantes : `power_window_seconds`,
`power_window_wh`, `power_min_seconds`, `power_min_wh` et `power_smoothing_seconds`.
Une cible énergétique inférieure au minimum énergétique est refusée.

Le profil ABB expose une puissance que le pilote reprend au total et sur L1 ;
le profil EM24 expose deux registres contenant la même estimation.
Pendant l'apprentissage, une lecture qui touche un mot de puissance reçoit
l'exception Modbus **04**, y compris le bloc de mesures utilisé par GX. L'identité,
la tension, le courant et les énergies restent lisibles séparément si la trame
est fraîche. Si la source expire, toutes les mesures deviennent indisponibles.
Le GX peut conserver temporairement sa dernière valeur dans son cache.

Les index Wh sont inchangés ; la représentation ABB est quantifiée à 10 Wh,
la représentation EM24 à 100 Wh.
Les registres supplémentaires du Linky ne deviennent pas des watts instantanés :
CCASN/CCAIN sont historiques, et les ERQ sont des énergies réactives.

Les logs donnent toutes les 30 s les VA, W estimés, facteur, moyenne énergétique,
durée de fenêtre et âge de dernière calibration. Avec l'export Prometheus
facultatif, les métriques supplémentaires sont :

| Métrique `tic_em24_…` | Sens |
| --- | --- |
| `power_estimate_valid` | Estimation disponible depuis une source fraîche ; pas une garantie de précision |
| `power_estimate_state{state=…}` | `warming_up`, `tracking`, `energy_limited`, `zero_apparent`, ou mode simulé/apparent |
| `power_factor_estimate` | Rapport effectif W/VA de l'estimation |
| `power_energy_mean_watts` | Moyenne active historique utilisée lors du dernier apprentissage |
| `power_window_seconds` | Durée de cette moyenne |
| `power_window_wh` | Nombre de Wh utilisés pour cette moyenne |
| `power_smoothing_seconds` | Constante de temps effective du lissage |
| `power_calibration_age_seconds` | Temps depuis la fin de cette moyenne |

Une estimation indisponible n'exporte pas `power_estimate_watts`. Une source
expirée n'exporte aucun facteur ni moyenne physique. Les moyennes de calibration
sont toujours à interpréter avec leur fenêtre et leur âge.

## Limites et qualification

L'estimation n'est pas une mesure active instantanée. Un facteur qui change
sans variation des VA n'est reconnu qu'au fil des nouveaux Wh ; la correction
peut prendre une à plusieurs fenêtres. À très faible puissance, ou en présence
de VA sans énergie active, l'apprentissage initial peut être très long ou ne
pas aboutir. Des passages import/export répétés peuvent aussi laisser la
puissance temporairement indisponible. La TIC ne permet pas de supprimer ce
compromis par un simple calcul.

Les tests utilisent des puissances actives indépendantes, intégrées puis
quantifiées en Wh : import/export, faible facteur, plusieurs cadences, marches
de charge, changement de facteur à VA constants, faible puissance, index figé,
défauts et reprise. Ils vérifient aussi le résultat encodé par le serveur TCP.
Leur tolérance synthétique n'est pas une spécification de précision sur site.

Sur un scénario synthétique passant de 3 000 W à 6 000 W, à VA constants,
l'estimation hybride entre dans une bande de ±5 % et y reste pendant 10 s à
partir d'environ **26 s après la marche**, contre **74 s** avec la seule cible
temporelle de 60 s. Ce résultat illustre le gain dans ce scénario, sans prédire
la latence ou la précision pour toutes les charges réelles.

Comparer ensuite avec les watts réseau Enphase sur des fenêtres synchronisées,
en conservant les transitoires et les défauts. **Usage ESS et pilotage solaire
natif Victron non qualifiés.** Le présent travail ne modifie pas la borne EV.

Références complémentaires : [spécification Enedis](https://www.enedis.fr/media/2035/download),
[Couraud et al., IEEE ISGT Europe 2023](https://eprints.gla.ac.uk/308866/).
