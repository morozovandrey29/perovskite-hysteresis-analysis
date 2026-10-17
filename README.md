# Perovskite Hysteresis Relaxation Analysis

A small Python desktop application for fitting frequency-dependent hysteresis-area spectra with a sum of phenomenological relaxation peaks. It is intended for comparing spectra across devices and estimating effective characteristic timescales.

> **Scientific caveat:** the fit is not a microscopic defect-identification method. A single isothermal `Hyst_Area(f)` curve generally cannot uniquely assign a fitted component to a particular ion, vacancy, grain-boundary process, or interface. Treat such labels as hypotheses, not as direct measurements.

## Features

- Desktop GUI built with Tkinter and Matplotlib.
- Input: `.xlsx`, `.csv`, or `.txt`; Excel is read without pandas/openpyxl.
- Automatically separates records by device when a `Device`-like column is available.
- Fits 1 to *N* components, with automatic model selection by AICc. The maximum number of components is configurable.
- Optional high-frequency down-weighting or exclusion; all points can also be weighted equally.
- Optional fitted baseline `H0`, configurable peak-shape parameter `beta`, and log-frequency interpolation for display only.
- Exports one `.xlsx` workbook with `Parameters`, `Measured + Fit`, and `Fit curves` sheets.
- Keeps model fitting, file parsing, GUI, and export helpers in separate modules.

## Model

The model is

\[
H(f)=H_0+\sum_{i=1}^{N} A_i\frac{2(f/f_{0,i})^\beta}{1+(f/f_{0,i})^{2\beta}}.
\]

`A_i` is the amplitude of component *i*, `f0_i` is its peak frequency, and `beta` is a fixed phenomenological shape parameter. When `beta = 1`, each component has the Debye-like loss-peak form. The effective characteristic timescale is reported as `tau_i = 1 / (2*pi*f0_i)`. This timescale should not be interpreted as a direct measurement of a uniquely identified microscopic process without independent evidence.

In automatic mode, the application compares models with 1 through `max_components` and selects the candidate with the lowest finite AICc. The weights change the objective function and therefore can affect the selected model; report this choice and test fit stability.

## Requirements

- Python 3.10 or newer.
- NumPy, SciPy, Matplotlib.
- Tkinter, normally included with the standard Windows Python distribution. On Linux it may need to be installed via the OS package manager (for example `python3-tk`).

## Run on Windows

1. Download or clone this repository.
2. Open the repository folder in a terminal.
3. Create an environment and install dependencies:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e .
   ```

4. Launch the GUI:

   ```powershell
   python -m hysteresis_analysis
   ```

   Or use `run_windows.bat`, which creates the environment, installs dependencies, and starts the application.

## Run on macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
python -m hysteresis_analysis
```

You can alternatively run `./run.sh`. If Tkinter is unavailable, install the platform's Tk package first.

## Input data format

### CSV example

```csv
Device,Frequency_Hz,Hyst_Area
Control,0.01,0.0123
Control,0.1,0.123
Control,1,0.234
Modified,0.01,0.014
Modified,0.1,0.141
Modified,1,0.261
```

Use at least three valid, positive frequency points per device. Duplicate frequencies are merged using the median. If no device column is present, the sheet/file name is used as the dataset label. Frequency values can be numeric Hz values or strings such as `100 Hz`, `10 kHz`, or `500 mHz`.

For Excel, the loader searches for a sheet named `Analysis Results` first (case-insensitive normalized matching), then searches other sheets. The required headers can be aliased in the JSON settings.

A synthetic two-device example is included in [`examples/sample_hysteresis.csv`](examples/sample_hysteresis.csv). It is artificial test data, not experimental data.

## Configuration

Defaults live in [`src/hysteresis_analysis/config.example.json`](src/hysteresis_analysis/config.example.json). To maintain your own local defaults, copy it to `src/hysteresis_analysis/config.json` and edit that copy; the local file is git-ignored. Alternatively, pass a JSON file directly:

```bash
python -m hysteresis_analysis --config path/to/my_settings.json
```

Configurable options include:

- Window title and size.
- Maximum number of components (1–8) and default model mode.
- Default weighting strategy, cut-off frequency, down-weighting power, `beta`, and whether to fit `H0`.
- Whether to show the interpolated source curve.
- Expected input column aliases and preferred worksheet name.

`cutoff_hz`, `weight_power`, and `beta` must be greater than zero. The cut-off, power, and beta can also be changed from the GUI.

## Output workbook

- **Parameters** — amplitudes, peak frequencies, effective timescales, fit metrics, weighting mode/cutoff/power, baseline setting, model-selection mode, and optional user-entered ion/path hypotheses.
- **Measured + Fit** — measured points, total model, residuals, weights, baseline, and individual component values.
- **Fit curves** — dense frequency grid for making smooth plots.

The smoothed curve is interpolated in log-frequency for display/export only; it is not used as the fitted target.

## Project layout

```text
src/hysteresis_analysis/
  app entry point: __main__.py
  gui.py          Tkinter GUI
  model.py        fit model and optimization
  io.py           XLSX/CSV parsing and data validation
  xlsx_export.py  result workbook writer
  config.py       settings and validation
  config.example.json
tests/            model and data tests
examples/         synthetic CSV example
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## License

MIT. See [`LICENSE`](LICENSE). Copyright holder: Morozov Andrei.
