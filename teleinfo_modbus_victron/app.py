"""CLI lifecycle: native Python and Docker use the same entry point."""
import argparse
import asyncio
import logging
import signal

from .config import load_config
from .model import MeasurementStore
from .server import create_server
from .sources import simulated_source, tic_source

LOG = logging.getLogger(__name__)


async def run(config):
    store = MeasurementStore(config)
    server = create_server(config, store)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    metrics = None
    task = None
    waiter = None
    monitor = None

    async def watch():
        previous = None
        next_diagnostic = 0.0
        while True:
            snapshot = store.fresh()
            valid = snapshot is not None and snapshot.estimated_power is not None
            state = (snapshot.power_estimate.state if snapshot and snapshot.power_estimate
                     else "valid" if valid else store.reason)
            if (valid, state) != previous:
                LOG.log(logging.INFO if snapshot else logging.WARNING,
                        "Measurements %s (%s)", "valid" if valid else "unavailable",
                        state)
                previous = (valid, state)
            if snapshot and snapshot.power_estimate and loop.time() >= next_diagnostic:
                estimate = snapshot.power_estimate
                LOG.info("Power estimator state=%s VA=%.1f estimated_W=%s factor=%s energy_mean_W=%s "
                         "window_s=%.1f window_Wh=%d smoothing_s=%.2f calibration_age_s=%s",
                         estimate.state, snapshot.apparent_import - snapshot.apparent_export,
                         None if estimate.watts is None else round(estimate.watts, 1),
                         None if estimate.factor is None else round(estimate.factor, 3),
                         None if estimate.energy_mean_watts is None else round(estimate.energy_mean_watts, 1),
                         estimate.window_seconds, estimate.window_wh, estimate.smoothing_seconds,
                         estimate.calibration_age_seconds)
                next_diagnostic = loop.time() + 30
            await asyncio.sleep(0.5)

    try:
        await server.start()
        if config.metrics_enabled:
            try:
                from .metrics import start_metrics
            except ImportError as exc:
                raise RuntimeError("install package with [metrics] to enable Prometheus") from exc
            metrics = start_metrics(config, store)
        LOG.warning("EXPERIMENTAL MONITORING: power method=%s (simulated source bypasses learning); "
                    "frequency is configured %.1f Hz; ESS unqualified",
                    config.power_method, config.nominal_frequency)
        LOG.info("%s server listening on %s:%d, unit 1, serial %s, source %s",
                 server.contract.PRODUCT_NAME, config.host, config.port,
                 config.abb_serial if config.meter_profile == "abb_b21" else config.serial, config.source)
        if config.source == "tic" and config.power_method == "adaptive":
            LOG.info("Power window targets %.1f s OR %d Wh; minimums %.1f s AND %d Wh; maximum smoothing tau %.1f s",
                     config.power_window_seconds, config.power_window_wh,
                     config.power_min_seconds, config.power_min_wh, config.power_smoothing_seconds)
        task = asyncio.create_task(tic_source(config, store) if config.source == "tic"
                                   else simulated_source(config, store))
        waiter = asyncio.create_task(stop.wait())
        monitor = asyncio.create_task(watch())
        done, _ = await asyncio.wait((task, waiter, monitor), return_when=asyncio.FIRST_COMPLETED)
        for finished in done:
            finished.result()  # A failed source/monitor must terminate, never leave a stale server running.
    finally:
        store.invalidate("service stopping")
        for pending in (task, waiter, monitor):
            if pending:
                pending.cancel()
        await asyncio.gather(*(t for t in (task, waiter, monitor) if t), return_exceptions=True)
        await server.stop()
        if metrics:
            metrics[0].shutdown()
            metrics[0].server_close()


def main():
    parser = argparse.ArgumentParser(description="Linky standard TIC → experimental ABB B21 / EM24 TCP server")
    parser.add_argument("--config", help="YAML file; overridden by TIC_EM24_* environment variables")
    parser.add_argument("--check-config", action="store_true", help="validate and exit without opening USB/network")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        if args.check_config:
            print("Configuration OK")
            return
        asyncio.run(run(config))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
