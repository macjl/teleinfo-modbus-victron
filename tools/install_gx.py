#!/usr/bin/env python3
"""Run on Venus OS as root, from an unpacked checkout; no pip or rootfs remount."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
BASE = Path('/data/dbus-linky-tic')
MARKER = '# teleinfo-modbus-victron: native D-Bus service'


def boot_hook(text):
    block = MARKER + '\n/data/dbus-linky-tic/boot.sh\n# end teleinfo-modbus-victron\n'
    if MARKER in text:
        return re.sub(re.escape(MARKER) + r'\n.*?# end teleinfo-modbus-victron\n?', block, text, flags=re.S)
    if text.startswith('#!'):
        first, _, rest = text.partition('\n')
        return first + '\n' + block + rest
    return '#!/bin/sh\n' + block + text


def adapter_rule(properties):
    key = 'ID_SERIAL_SHORT' if properties.get('ID_SERIAL_SHORT') else 'ID_SERIAL'
    required = ('ID_VENDOR_ID', 'ID_MODEL_ID', key)
    if not all(properties.get(k) and re.fullmatch(r'[A-Za-z0-9_.:+-]+', properties[k]) for k in required):
        raise ValueError('adapter needs stable udev vendor, product and serial properties')
    return ('# Match only the observed TIC adapter, not every FTDI converter.\n'
            'ACTION=="add|change", SUBSYSTEM=="tty", '
            + ', '.join('ENV{' + k + '}=="' + properties[k] + '"' for k in required)
            + ', ENV{VE_SERVICE}="ignore"\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, help='observed stable /dev/serial/by-id/... path')
    parser.add_argument('--instance', type=int, default=43)
    parser.add_argument('--no-start', action='store_true', help='install with service down until explicitly activated')
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path('/opt/victronenergy/version').is_file():
        parser.error('run this installer on Venus OS as root')
    sys.path.insert(0, str(SOURCE))
    from teleinfo_modbus_victron.dbus_app import locate_velib
    from teleinfo_modbus_victron.dbus_model import DBusConfig, VERSION, load_dbus_config
    import serial
    import dbus
    from gi.repository import GLib
    locate_velib()
    device = Path(args.device)
    if not str(device).startswith('/dev/serial/by-id/') or not device.resolve(strict=True).is_char_device():
        parser.error('choose the actual character device through its /dev/serial/by-id/ link')
    cfg = DBusConfig(device=str(device), instance=args.instance)
    if (BASE / 'config.json').exists():
        previous = load_dbus_config(BASE / 'config.json')
        if previous.device != cfg.device:
            parser.error('existing device differs; edit and validate the local config explicitly')
    props = dict(line.split('=', 1) for line in subprocess.check_output(
        ['udevadm', 'info', '--query=property', '--name', str(device.resolve())], text=True).splitlines() if '=' in line)
    rule = adapter_rule(props)
    rc = Path('/data/rc.local')
    old_rc = rc.read_text() if rc.exists() else ''
    if Path('/data/rc.local.disabled').exists():
        parser.error('modifications appear disabled; enable modifications in GX before installing')
    for link in (Path('/service/dbus-linky-tic'), Path('/opt/victronenergy/service/dbus-linky-tic')):
        if link.exists() and (not link.is_symlink() or link.resolve() != BASE / 'service'):
            parser.error(f'conflicting service path: {link}')
    # Prepare a complete immutable runtime before changing the active app link.
    package = SOURCE / 'teleinfo_modbus_victron'
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(package.glob('*.py')))).hexdigest()[:12]
    release = BASE / 'releases' / (VERSION + '-' + digest)
    (release / 'teleinfo_modbus_victron').mkdir(parents=True, exist_ok=True)
    for src in package.glob('*.py'):
        target = release / 'teleinfo_modbus_victron' / src.name
        shutil.copyfile(src, target)
        py_compile.compile(str(target), doraise=True)
    (BASE / 'backups').mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if rc.exists():
        shutil.copyfile(rc, BASE / 'backups' / ('rc.local-' + stamp))
    if (BASE / 'config.json').exists():
        shutil.copyfile(BASE / 'config.json', BASE / 'backups' / ('config-' + stamp + '.json'))
    else:
        data = json.loads((SOURCE / 'config.dbus.example.json').read_text())
        data.update(device=str(device), instance=cfg.instance)
        (BASE / 'config.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    (BASE / 'config.json').chmod(0o600)
    if Path('/service/dbus-linky-tic').exists():
        subprocess.run(['svc', '-d', '/service/dbus-linky-tic'], check=True)
    shutil.copytree(SOURCE / 'deploy/gx/service', BASE / 'service', dirs_exist_ok=True)
    shutil.copyfile(SOURCE / 'deploy/gx/boot.sh', BASE / 'boot.sh')
    for path in ('boot.sh', 'service/run', 'service/log/run'):
        (BASE / path).chmod(0o755)
    (BASE / '99-linky-tic.rules').write_text(rule)
    temporary = BASE / 'app.new'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release)
    temporary.replace(BASE / 'app')
    down = BASE / 'service/down'
    if args.no_start:
        down.touch()
    else:
        down.unlink(missing_ok=True)
    rc.write_text(boot_hook(old_rc))
    rc.chmod(0o755)
    subprocess.run([str(BASE / 'boot.sh')], check=True)
    subprocess.run(['udevadm', 'trigger', '--action=change', '--sysname-match=' + device.resolve().name], check=True)
    subprocess.run(['/opt/victronenergy/serial-starter/stop-tty.sh', str(device.resolve())], check=True, timeout=15)
    if not args.no_start:
        subprocess.run(['svc', '-u', '/service/dbus-linky-tic'], check=True)
    print(f'Installed {VERSION} under {BASE}; service ' + ('down (activate explicitly)' if args.no_start else 'enabled'))
    print('Configuration and adapter identity remain local. Logs: /var/log/dbus-linky-tic/current')


if __name__ == '__main__':
    main()
