"""Native Venus OS entry point using firmware-provided D-Bus/GLib bindings."""
import argparse
import asyncio
from contextlib import suppress
import logging
from pathlib import Path
import signal
import subprocess
import sys
import threading

from .dbus_model import VERSION, PowerFallback, load_dbus_config, render
from .model import MeasurementStore
from .sources import open_serial, tic_source

LOG = logging.getLogger(__name__)


def locate_velib(configured=''):
    candidates = [configured] if configured else [
        '/opt/victronenergy/dbus-modbus-client',
        '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python',
        '/opt/victronenergy/velib_python']
    for candidate in candidates:
        path = Path(candidate)
        if all((path / name).is_file() for name in ('vedbus.py', 'settingsdevice.py', 've_utils.py')):
            return path
    raise RuntimeError('firmware velib_python not found; set velib_path explicitly')


def claimed_opener(config, claim=True):
    if claim:
        device = Path(config.device).resolve(strict=True)
        if not device.is_char_device():
            raise OSError('configured TIC device is not a character device')
        subprocess.run(['/opt/victronenergy/serial-starter/stop-tty.sh', str(device)],
                       check=True, timeout=10, stdout=subprocess.DEVNULL)
    return open_serial(config)


class SourceWorker:
    """Async serial acquisition off the GLib thread; failure is checked every tick."""
    def __init__(self, config, store, opener):
        self.config, self.store, self.opener = config, store, opener
        self.loop = None
        self.task = None
        self.failure = None
        self.thread = threading.Thread(target=self._run, name='linky-tic-reader', daemon=True)

    def _run(self):
        async def source():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.create_task(tic_source(self.config, self.store, self.opener))
            await self.task
        try:
            asyncio.run(source())
        except asyncio.CancelledError:
            pass
        except BaseException as exc:
            self.store.invalidate('reader failed')
            self.failure = exc

    def start(self):
        self.thread.start()

    def stop(self):
        if self.loop and self.task and not self.loop.is_closed():
            with suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.task.cancel)
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('serial reader did not stop before timeout')


def run(config):
    sys.path.insert(0, str(locate_velib(config.velib_path)))
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    from settingsdevice import SettingsDevice
    from vedbus import VeDbusService

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
    source_config = config.source_config()
    store = MeasurementStore(source_config)
    power_fallback = PowerFallback(enabled=config.warmup_fallback)
    service = None
    failure = None
    settings_root = '/Settings/Devices/' + config.identity

    def setting_changed(name, old, new):
        if service is not None and name == 'name':
            service['/CustomName'] = new
        elif service is not None and name == 'instance' and old != new:
            LOG.info('Device instance changed; restarting D-Bus registration')
            loop.quit()

    settings = SettingsDevice(bus, {
        'instance': [settings_root + '/ClassAndVrmInstance', f'grid:{config.instance}', 0, 0],
        'name': [settings_root + '/CustomName', config.custom_name, 0, 0],
    }, setting_changed, timeout=10)
    role, instance_text = str(settings['instance']).split(':')
    instance = int(instance_text)
    if role != 'grid' or not 0 <= instance <= 999:
        raise ValueError('persisted ClassAndVrmInstance must be grid:0..999')
    for name in bus.list_names():
        if str(name).startswith('com.victronenergy.grid.'):
            if str(name) == config.service_name:
                raise RuntimeError('this Linky D-Bus service is already running')
            other = bus.get_object(name, '/DeviceInstance').GetValue(
                dbus_interface='com.victronenergy.BusItem', timeout=3)
            if int(other) == instance:
                raise RuntimeError(f'grid instance {instance} already in use; choose another instance')

    def rename(path, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 80:
            return False
        settings['name'] = str(value)
        return True

    def change_instance(path, value):
        if isinstance(value, (int, dbus.Int32, dbus.UInt32)) and not isinstance(value, bool) and 0 <= value <= 999:
            settings['instance'] = f'grid:{int(value)}'
            return True
        return False

    service = VeDbusService(config.service_name, bus=bus, register=False)
    identity = {
        '/Mgmt/ProcessName': __file__, '/Mgmt/ProcessVersion': VERSION,
        '/Mgmt/Connection': 'Linky standard TIC USB',
        '/DeviceInstance': instance, '/ProductId': 0xFFFF,
        '/ProductName': 'Linky TIC Energy Meter', '/CustomName': str(settings['name']),
        '/FirmwareVersion': VERSION, '/Serial': config.serial,
        '/Role': 'grid', '/DeviceType': 0, '/NrOfPhases': 1,
        '/IsGenericEnergyMeter': 1, '/UpdateIndex': 0,
        '/Tic/SchemaVersion': 1,
    }
    for path, value in identity.items():
        callback = rename if path == '/CustomName' else change_instance if path == '/DeviceInstance' else None
        service.add_path(path, value, writeable=callback is not None, onchangecallback=callback)
    for path, value in render(store, power_fallback).items():
        service.add_path(path, value)
    service.register()  # Identity and all data paths exist before publishing the name.
    worker = SourceWorker(source_config, store,
                          lambda cfg: claimed_opener(cfg, config.claim_serial))
    last_key = None
    last_state = None

    def update():
        nonlocal failure, last_key, last_state
        try:
            if worker.failure:
                raise RuntimeError('serial worker failed') from worker.failure
            if not worker.thread.is_alive():
                raise RuntimeError('serial worker stopped unexpectedly')
            values = render(store, power_fallback)
            key = (store.accepted, store.rejected, values['/Connected'], values['/Tic/Status/PowerValid'])
            with service as batch:
                for path, value in values.items():
                    batch[path] = value
                if key != last_key:
                    batch['/UpdateIndex'] = (int(service['/UpdateIndex']) + 1) % 256
            last_key = key
            state = (values['/Connected'], values['/Tic/Status/State'])
            if state != last_state:
                LOG.info('TIC connected=%d state=%s', *state)
                last_state = state
            return True
        except BaseException as exc:
            failure = exc
            LOG.exception('D-Bus update failed; stopping service')
            loop.quit()
            return False

    def shutdown(signum, frame):
        loop.quit()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    worker.start()
    GLib.timeout_add(250, update)
    LOG.info('Native Linky grid service started, instance %d; active power estimated, ESS unqualified', instance)
    try:
        loop.run()
    finally:
        store.invalidate('service stopping')
        with service as batch:
            for path, value in render(store, power_fallback).items():
                batch[path] = value
        worker.stop()
    if failure:
        raise RuntimeError('D-Bus service failed') from failure


def main():
    parser = argparse.ArgumentParser(description='Linky standard TIC USB to native Venus OS D-Bus grid meter')
    parser.add_argument('--config', required=True, help='JSON configuration, independent of Modbus YAML')
    parser.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        config = load_dbus_config(args.config)
        if args.check_config:
            print('D-Bus configuration OK')
            return
        run(config)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
