import numpy as np

from hysteresis_analysis.config import load_settings
from hysteresis_analysis.io import FrequencyDataset, load_file, parse_frequency
from hysteresis_analysis.model import debye_component, fit_relaxation


def test_component_maximum_occurs_at_peak_frequency():
    f0 = 13.0
    amplitude = 0.7
    y = debye_component(np.array([f0]), amplitude, f0, beta=1.0)
    assert np.isclose(y[0], amplitude)


def test_two_timescale_conversion():
    f0 = 10.0
    tau = 1.0 / (2.0 * np.pi * f0)
    assert np.isclose(tau, 0.015915494309189534)


def test_single_component_fit_recovers_synthetic_peak():
    f = np.logspace(-2, 3, 50)
    y = debye_component(f, amplitude=0.42, f0=4.5, beta=1.0)
    ds = FrequencyDataset("synthetic", f, y)
    result = fit_relaxation(ds, k=1, weight_mode="all", cutoff_hz=100.0, power=2.0)
    assert result.k == 1
    assert np.isclose(result.amplitude[0], 0.42, rtol=0.03)
    assert np.isclose(result.f0_hz[0], 4.5, rtol=0.03)
    assert np.isclose(result.tau_s[0], 1 / (2 * np.pi * 4.5), rtol=0.03)


def test_csv_example_loads_two_devices():
    from pathlib import Path

    sample = Path(__file__).parents[1] / "examples" / "sample_hysteresis.csv"
    datasets = load_file(sample)
    assert [dataset.device for dataset in datasets] == ["Control", "TBT-4F"]
    assert all(len(dataset.frequency_hz) >= 3 for dataset in datasets)


def test_frequency_parser_units():
    assert parse_frequency("10 kHz") == 10000.0
    assert parse_frequency("500 mHz") == 0.5
    assert parse_frequency("2.5") == 2.5
    assert parse_frequency("invalid") is None


def test_default_config_is_valid():
    settings = load_settings()
    assert settings["fit"]["max_components"] == 4
    assert settings["fit"]["default_weight_mode"] in {"all", "downweight", "exclude"}


def test_xlsx_export_can_be_read_back(tmp_path):
    from hysteresis_analysis.io import read_xlsx
    from hysteresis_analysis.xlsx_export import write_simple_xlsx

    output = tmp_path / "roundtrip.xlsx"
    write_simple_xlsx(output, {"Results": [["Frequency_Hz", "Fit"], [1.0, 0.5], [10.0, 0.6]]})
    workbook = read_xlsx(str(output))
    assert workbook["Results"][0] == ["Frequency_Hz", "Fit"]
    assert workbook["Results"][1] == [1.0, 0.5]
