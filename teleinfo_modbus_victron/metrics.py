"""Optional Prometheus export: expired physical values are never exported."""
from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import GaugeMetricFamily


class Collector:
    def __init__(self, store):
        self.store = store

    def collect(self):
        snapshot = self.store.fresh()
        yield GaugeMetricFamily("tic_em24_source_valid", "Fresh validated TIC source", value=int(snapshot is not None))
        yield GaugeMetricFamily("tic_em24_power_estimate_valid", "Fresh available power estimate (not an accuracy guarantee)",
                               value=int(snapshot is not None and snapshot.estimated_power is not None))
        age = self.store.age()
        if age is not None:
            yield GaugeMetricFamily("tic_em24_source_age_seconds", "Time since last accepted frame", value=age)
        for name, value in (("frames_accepted", self.store.accepted),
                            ("frames_rejected", self.store.rejected),
                            ("serial_connections", self.store.reconnections)):
            yield GaugeMetricFamily(f"tic_em24_{name}", name, value=value)
        if snapshot:
            for name, value in (("voltage_volts", snapshot.voltage), ("current_amperes", snapshot.current),
                                ("apparent_import_va", snapshot.apparent_import),
                                ("apparent_export_va", snapshot.apparent_export),
                                ("energy_import_wh", snapshot.energy_import_wh),
                                ("energy_export_wh", snapshot.energy_export_wh)):
                yield GaugeMetricFamily(f"tic_em24_{name}", name, value=value)
            if snapshot.estimated_power is not None:
                yield GaugeMetricFamily("tic_em24_power_estimate_watts", "Estimated active power", value=snapshot.estimated_power)
            estimate = snapshot.power_estimate
            state = estimate.state if estimate else ("simulated" if self.store.config.source == "simulated" else "apparent")
            status = GaugeMetricFamily("tic_em24_power_estimate_state", "Estimator state", labels=["state"])
            status.add_metric([state], 1)
            yield status
            if estimate:
                for name, value in (("power_factor_estimate", estimate.factor),
                                    ("power_energy_mean_watts", estimate.energy_mean_watts),
                                    ("power_window_seconds", estimate.window_seconds),
                                    ("power_window_wh", estimate.window_wh),
                                    ("power_smoothing_seconds", estimate.smoothing_seconds),
                                    ("power_calibration_age_seconds", estimate.calibration_age_seconds)):
                    if value is not None:
                        yield GaugeMetricFamily(f"tic_em24_{name}", name, value=value)


def start_metrics(config, store):
    registry = CollectorRegistry()
    registry.register(Collector(store))
    return start_http_server(config.metrics_port, addr=config.metrics_host, registry=registry)
