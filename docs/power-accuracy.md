# Écart entre puissance TIC estimée et puissance active

## Constat sur l’installation du 26 octobre 2026

L’utilisateur signale environ **700 W affichés par l’EM24 émulé**, contre
**400 W d’import réseau en direct dans Enphase**, de nuit. La passerelle
expose alors dans le registre de puissance active la différence des puissances
apparentes `SINSTS - SINSTI`, conformément au mode expérimental choisi.
Les VA ne constituent pas une mesure active en W.

Un contrôle a été effectué depuis les métriques locales de la passerelle,
sans lecteur série concurrent. Les métriques étaient activées uniquement sur
le loopback de l’hôte pour cet essai, puis désactivées.

| Grandeur | Résultat |
| --- | ---: |
| Durée d’observation | 120,27 s |
| Échantillons valides | 121 |
| Variation EAST | +10 Wh |
| Variation EAIT | 0 Wh |
| Puissance active moyenne calculée | **299,3 W** |
| Puissance apparente moyenne observée | **666,6 VA** |
| Plage apparente observée | 657 à 673 VA |
| Équivalent d’un pas de 1 Wh sur cette durée | Environ 29,9 W |

Calcul : `P_moyenne = 3600 × (ΔEAST - ΔEAIT) / durée_en_secondes`.
Les index proviennent des Wh TIC originaux, avant la quantification EM24 de
100 Wh. Les 29,9 W indiquent l’effet d’un pas de compteur sur cette fenêtre,
pas une garantie d’incertitude complète ; la cadence des mises à jour et le
choix des bornes temporelles interviennent aussi.

Cette observation établit que l’assimilation numérique des VA à des W est
très imprécise sur cette charge. Elle ne valide pas directement la valeur
Enphase de 400 W, qui n’a pas été échantillonnée simultanément sur la même
fenêtre. Elle ne désigne pas non plus la charge responsable de l’écart.
Les définitions des puissances et des index sont données dans la
[spécification Enedis, §6.2.3.6 et §6.2.3.10](https://www.enedis.fr/media/2035/download).

## Conséquences pour le projet

Depuis ce diagnostic, le mode par défaut est un [estimateur adaptatif inspiré
de F1ATB](power-estimator.md). Les constats ci-dessus décrivent l'ancienne
approximation brute ; ils ne sont pas des résultats de validation du nouvel
estimateur. La valeur Enphase n'a toujours pas été acquise simultanément.

- L’intégration Modbus et la détection GX fonctionnent, mais cela ne qualifie
  pas la justesse de la puissance active représentée.
- L'ancienne source `SINSTS - SINSTI` doit rester identifiée comme estimation
  expérimentale ; elle n’est pas adaptée à une mesure active précise ici.
- Ne pas appliquer un coefficient constant 400/700 : le rapport peut varier
  avec les charges et leur état.
- Les index d’énergie Linky restent utilisables. Leur dérivée donne une
  moyenne active, avec un compromis entre délai et quantification ; elle
  ne constitue pas une mesure instantanée pour ESS.
- Une évolution possible est de garder la TIC pour les index et de prendre
  la puissance active réseau dans l’Envoy local, après validation du point
  de mesure, de l’authentification, de la cadence et de l’expiration. Aucun
  remplacement automatique de source n’a été effectué lors du diagnostic.

L’Envoy a été trouvé par résolution de `envoy.local`. Les lectures locales
testées ont retourné HTTP 401 ; aucune puissance Enphase n’a été lue par
la passerelle. L’usage ESS reste non qualifié pour toutes ces variantes.
