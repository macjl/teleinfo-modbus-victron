# Contribuer / Contributing

Les issues et pull requests sont bienvenues, en français ou en anglais.
Issues and pull requests are welcome in French or English.

## Développement / Development

Use Python 3.11 or newer on Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[metrics]'
.venv/bin/python -m unittest discover -v
.venv/bin/python tools/check_upstream.py
```

Tests use simulated data and local TCP listeners; no USB adapter or GX is
required. The separate upstream audit fetches pinned official sources and
checks their hashes, or accepts a matching checkout with `--source-dir`.

Keep measurement parsing, estimation and protocol encoding separate. Preserve
the distinction between measured Wh, apparent VA and estimated W. Missing or
expired measurements must remain unavailable. Add focused tests for changes
to wire formats, freshness or estimator behavior.

## Rapports matériels / Hardware reports

Include gateway version, Python/Docker version and architecture, USB adapter
model, standard TIC mode, GX model, Venus OS version and selected meter profile.
Describe discovery, initialization and displayed readings separately. An open
TCP connection alone does not establish successful GX integration.

Remove secrets, LAN addresses, USB serials, Linky `ADSC`/`PRM` identifiers and
personal usage data before posting logs or captures. Never attach `.env` or
unredacted local configuration. Use synthetic TIC fixtures for tests.

## Évolutions envisagées / Possible next steps

- Direct D-Bus publishing on GX, with a Linky identity and native grid paths.
- Extra TIC contract and tariff data for automation, keeping custom paths
  distinct from fields natively displayed by GX and recorded by VRM.
- End-to-end USB/network fault timing and GX reboot validation.
- Synchronized comparisons with reliable active-power measurements.
- More hardware and Venus OS version reports.

These items are not implemented or qualified by the current release. D-Bus
publishing will not remove the underlying TIC active-power limitation.
Historical TIC mode and three-phase support would need separate requirements
and tests; the current parser/model must not be presented as supporting them.

Contributions are licensed under the repository's MIT license. Credit relevant
upstream work; do not add third-party code without checking its license.
