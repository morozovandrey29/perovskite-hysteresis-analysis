"""Tkinter desktop interface for the hysteresis relaxation fitting tool."""
from __future__ import annotations

import argparse
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator
import matplotlib
try:
    matplotlib.use("TkAgg")
except ImportError:  # pragma: no cover - fallback for headless import environments
    matplotlib.use("Agg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .config import load_settings
from .io import FrequencyDataset, load_file
from .model import FitResult, auto_fit, debye_component, fit_relaxation
from .xlsx_export import write_simple_xlsx

ION_LABELS = [
    "Unassigned",
    "V_I — iodine vacancy",
    "I_i — interstitial iodine",
    "V_Cl — chlorine vacancy",
    "Cl_i — interstitial chlorine",
    "A-site vacancy / organic cation",
    "Other hypothesized process",
]
PATH_LABELS = [
    "Unassigned",
    "Bulk",
    "Grain boundary",
    "Interface / contact",
    "Mixed pathway",
]


def fmt(x: float, sig: int = 4) -> str:
    if not np.isfinite(x):
        return "—"
    if x == 0:
        return "0"
    return f"{x:.{sig}g}"


def choose_figure_style(fig):
    fig.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.13)


class App(tk.Tk):
    def __init__(self, settings: dict | None = None):
        super().__init__()
        self.settings = settings or load_settings()
        app_cfg = self.settings["application"]
        fit_cfg = self.settings["fit"]
        display_cfg = self.settings["display"]
        self.title(app_cfg["title"])
        self.geometry(app_cfg["window_size"])
        self.minsize(*app_cfg["minimum_size"])

        self.datasets: list[FrequencyDataset] = []
        self.current_fit: FitResult | None = None
        self.current_ds: FrequencyDataset | None = None
        self.last_path: str | None = None
        self.component_ion_vars: list[tk.StringVar] = []
        self.component_path_vars: list[tk.StringVar] = []

        self.device_var = tk.StringVar()
        default_model = fit_cfg["default_model"]
        model_label = "Auto (AICc)" if str(default_model).lower() == "auto" else f"{int(default_model)} component(s)"
        weight_labels = {"all": "All frequencies", "downweight": "Down-weight high f", "exclude": "Exclude above f_cut"}
        self.model_var = tk.StringVar(value=model_label)
        self.weight_var = tk.StringVar(value=weight_labels[fit_cfg["default_weight_mode"]])
        self.cutoff_var = tk.StringVar(value=str(fit_cfg["cutoff_hz"]))
        self.power_var = tk.StringVar(value=str(fit_cfg["weight_power"]))
        self.beta_var = tk.StringVar(value=str(fit_cfg["beta"]))
        self.fit_baseline_var = tk.BooleanVar(value=bool(fit_cfg["fit_baseline"]))
        self.status_var = tk.StringVar(value="Open a data file.")
        self.smooth_var = tk.BooleanVar(value=bool(display_cfg["show_smoothed_original"]))

        self._build_ui()
        self._build_plot()

    # ---- UI construction --------------------------------------------------

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9))
        style.configure("Action.TButton", font=("Segoe UI", 10, "bold"))

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")

        ttk.Button(top, text="Open XLSX/CSV", command=self.open_file).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Label(top, text="Device:").grid(row=0, column=1, padx=(0, 5))
        self.device_box = ttk.Combobox(top, textvariable=self.device_var, width=18, state="readonly")
        self.device_box.grid(row=0, column=2, padx=(0, 15))
        self.device_box.bind("<<ComboboxSelected>>", self.on_device_selected)

        ttk.Label(top, text="Model:").grid(row=0, column=3, padx=(0, 5))
        model_options = ["Auto (AICc)"] + [f"{k} component(s)" for k in range(1, int(self.settings["fit"]["max_components"]) + 1)]
        self.model_box = ttk.Combobox(top, textvariable=self.model_var, width=16, state="readonly",
                                      values=model_options)
        self.model_box.grid(row=0, column=4, padx=(0, 15))

        ttk.Label(top, text="HF weighting:").grid(row=0, column=5, padx=(0, 5))
        self.weight_box = ttk.Combobox(top, textvariable=self.weight_var, width=25, state="readonly",
                                       values=["All frequencies", "Down-weight high f", "Exclude above f_cut"])
        self.weight_box.grid(row=0, column=6, padx=(0, 10))

        ttk.Button(top, text="FIT", style="Action.TButton", command=self.run_fit).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(top, text="Save results", command=self.export_results).grid(row=0, column=8, padx=(0, 8))

        ttk.Label(top, text="f_cut, Hz:").grid(row=1, column=1, pady=(8, 0), sticky="e")
        ttk.Entry(top, textvariable=self.cutoff_var, width=8).grid(row=1, column=2, pady=(8, 0), sticky="w")
        ttk.Label(top, text="Down-weighting power:").grid(row=1, column=3, pady=(8, 0), sticky="e")
        ttk.Entry(top, textvariable=self.power_var, width=8).grid(row=1, column=4, pady=(8, 0), sticky="w")
        ttk.Label(top, text="Peak-shape β:").grid(row=1, column=5, pady=(8, 0), sticky="e")
        ttk.Entry(top, textvariable=self.beta_var, width=7).grid(row=1, column=6, pady=(8, 0), sticky="w")
        ttk.Checkbutton(top, text="Show smoothed source curve", variable=self.smooth_var,
                        command=self.plot_current_fit).grid(row=1, column=7, pady=(8, 0), sticky="w")
        ttk.Checkbutton(top, text="Fit baseline H0", variable=self.fit_baseline_var,
                        command=self.run_fit).grid(row=1, column=8, pady=(8, 0), sticky="w")

        top.columnconfigure(9, weight=1)

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(main, padding=(4, 4))
        right = ttk.Frame(main, padding=(8, 4))
        main.add(left, weight=4)
        main.add(right, weight=2)

        self.plot_frame = left

        # Right panel: fit summary + component table + notes.
        ttk.Label(right, text="Fit summary", style="Header.TLabel").pack(anchor="w", pady=(0, 7))
        self.metrics_text = tk.Text(right, height=8, width=46, wrap="word", relief="solid", borderwidth=1,
                                    font=("Consolas", 9))
        self.metrics_text.pack(fill="x", pady=(0, 10))
        self.metrics_text.configure(state="disabled")

        ttk.Label(right, text="Components", style="Header.TLabel").pack(anchor="w")
        cols = ("i", "A", "f0", "tau", "ion", "path")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=7)
        headings = {"i": "No.", "A": "A", "f0": "f0, Hz", "tau": "tau, s", "ion": "Ion hypothesis", "path": "Path hypothesis"}
        widths = {"i": 38, "A": 65, "f0": 80, "tau": 80, "ion": 150, "path": 145}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill="x", pady=(5, 8))
        self.tree.bind("<Double-1>", self.edit_component_label)

        ttk.Label(right, text="Model notes", style="Header.TLabel").pack(anchor="w", pady=(5, 4))
        self.notes_text = tk.Text(right, height=16, width=46, wrap="word", relief="solid", borderwidth=1,
                                  font=("Segoe UI", 9))
        self.notes_text.pack(fill="both", expand=True)
        self.notes_text.configure(state="disabled")

        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=(8, 4))
        status.pack(fill="x", side="bottom")

    def _build_plot(self):
        self.fig = Figure(figsize=(8.2, 6.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        choose_figure_style(self.fig)
        self.ax.set_xscale("log")
        self.ax.set_xlabel("Frequency, Hz")
        self.ax.set_ylabel("Hysteresis area")
        self.ax.grid(True, which="both", alpha=0.20)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---- File/data operations --------------------------------------------

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Select a file containing Hyst_Area(f)",
            filetypes=[
                ("Excel workbook", "*.xlsx"),
                ("CSV / TXT", "*.csv *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            datasets = load_file(path, self.settings.get("input", {}))
        except Exception as exc:
            messagebox.showerror("File loading error", str(exc))
            return
        self.datasets = datasets
        self.last_path = path
        self.device_box["values"] = [d.device for d in datasets]
        self.device_var.set(datasets[0].device)
        self.status_var.set(f"Loaded {os.path.basename(path)} — {len(datasets)} dataset(s)")
        self.clear_results()
        self.run_fit()

    def get_current_ds(self) -> FrequencyDataset | None:
        target = self.device_var.get()
        for d in self.datasets:
            if d.device == target:
                return d
        return self.datasets[0] if self.datasets else None

    def on_device_selected(self, _event=None):
        """Refit the newly selected device instead of reusing a stale result."""
        self.clear_results()
        self.run_fit()

    def parse_fit_controls(self):
        cutoff = float(self.cutoff_var.get().replace(",", "."))
        power = float(self.power_var.get().replace(",", "."))
        beta = float(self.beta_var.get().replace(",", "."))
        if cutoff <= 0:
            raise ValueError("f_cut must be greater than 0.")
        if power <= 0:
            raise ValueError("Down-weighting power must be greater than 0.")
        if beta <= 0:
            raise ValueError("β must be greater than 0.")
        weight_label = self.weight_var.get()
        if weight_label == "All frequencies":
            mode = "all"
        elif weight_label == "Exclude above f_cut":
            mode = "exclude"
        else:
            mode = "down"
        return mode, cutoff, power, beta

    def clear_results(self):
        self.current_fit = None
        self.metrics_text.configure(state="normal")
        self.metrics_text.delete("1.0", "end")
        self.metrics_text.configure(state="disabled")
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.component_ion_vars.clear()
        self.component_path_vars.clear()

    # ---- Fit and plot -----------------------------------------------------

    def run_fit(self):
        ds = self.get_current_ds()
        if ds is None:
            messagebox.showinfo("No data", "Please open an XLSX/CSV file first.")
            return
        try:
            mode, cutoff, power, beta = self.parse_fit_controls()
            fit_baseline = bool(self.fit_baseline_var.get())
            selected = self.model_var.get()
            if selected.startswith("Auto"):
                max_k = int(self.settings["fit"]["max_components"])
                result = auto_fit(ds, max_k, mode, cutoff, power, beta, fit_baseline)
                selected_text = f"Auto → {result.k} component(s)"
            else:
                k = int(re.search(r"\d+", selected).group())
                result = fit_relaxation(ds, k, mode, cutoff, power, beta, fit_baseline)
                selected_text = selected
        except Exception as exc:
            messagebox.showerror("Fitting error", str(exc))
            return

        self.current_ds = ds
        self.current_fit = result
        self.status_var.set(
            f"{ds.device}: {selected_text}; used {result.n_used}/{len(ds.frequency_hz)} points; "
            f"AICc={fmt(result.aicc)}"
        )
        self.update_table(result)
        self.update_metrics(result, mode, cutoff)
        self.update_notes(result, mode, cutoff)
        self.plot_current_fit()

    def update_table(self, result: FitResult):
        """Refresh the component table while preserving user-entered labels."""
        old_ions = [v.get() for v in self.component_ion_vars]
        old_paths = [v.get() for v in self.component_path_vars]

        self.component_ion_vars = []
        self.component_path_vars = []
        for item in self.tree.get_children():
            self.tree.delete(item)

        ion_defaults = [
            "Unassigned",
            "Iodine vacancy (V_I)",
            "Chlorine vacancy (V_Cl)",
            "Interstitial iodine (I_i)",
            "Interstitial chlorine (Cl_i)",
            "Organic cation",
            "Other",
        ]
        path_defaults = [
            "Unassigned",
            "Bulk",
            "Grain boundary",
            "Interface",
            "Electrode/contact",
            "Mixed",
            "Other",
        ]

        for i, (a, f0, tau) in enumerate(
            zip(result.amplitude, result.f0_hz, result.tau_s), start=1
        ):
            ion = old_ions[i - 1] if i - 1 < len(old_ions) else ion_defaults[0]
            path = old_paths[i - 1] if i - 1 < len(old_paths) else path_defaults[0]
            self.component_ion_vars.append(tk.StringVar(value=ion))
            self.component_path_vars.append(tk.StringVar(value=path))
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(i, fmt(a), fmt(f0), fmt(tau), ion, path),
            )

    def edit_component_label(self, _event=None):
        """Edit ion/path hypothesis by double-clicking the corresponding cell."""
        item_id = self.tree.identify_row(_event.y) if _event is not None else ""
        col_id = self.tree.identify_column(_event.x) if _event is not None else ""
        if not item_id or not col_id:
            return

        try:
            i = int(item_id) - 1
        except ValueError:
            return
        if i < 0 or i >= len(self.component_ion_vars):
            return

        # Columns: #1=i, #2=A, #3=f0, #4=tau, #5=ion, #6=path.
        if col_id == "#5":
            current = self.component_ion_vars[i].get()
            value = simpledialog.askstring(
                "Ion hypothesis",
                f"Component {i + 1}. Enter a label or hypothesis:",
                initialvalue=current,
                parent=self,
            )
            if value is None:
                return
            self.component_ion_vars[i].set(value.strip() or "Unassigned")
        elif col_id == "#6":
            current = self.component_path_vars[i].get()
            value = simpledialog.askstring(
                "Migration pathway",
                f"Component {i + 1}. Enter a pathway hypothesis:",
                initialvalue=current,
                parent=self,
            )
            if value is None:
                return
            self.component_path_vars[i].set(value.strip() or "Unassigned")
        else:
            return

        values = list(self.tree.item(item_id, "values"))
        values[4] = self.component_ion_vars[i].get()
        values[5] = self.component_path_vars[i].get()
        self.tree.item(item_id, values=values)

    def update_metrics(self, result: FitResult, mode: str, cutoff: float):
        """Show a compact numerical summary of the fit."""
        if mode == "all":
            weighting = "All points have equal weight (1)"
        elif mode == "exclude":
            weighting = f"Points above {cutoff:g} Hz are excluded"
        else:
            weighting = f"High frequencies are down-weighted above {cutoff:g} Hz"

        lines = [
            f"Device: {result.device}",
            f"Components: {result.k}",
            f"H0 = {fmt(result.baseline)}" + ("  (fitted)" if result.baseline > 0 else "  (fixed at 0)"),
            f"β = {fmt(result.beta)}",
            f"R² (weighted) = {fmt(result.r2)}",
            f"RMSE (weighted) = {fmt(result.weighted_rmse)}",
            f"AICc = {fmt(result.aicc)}",
            f"Parameters = {result.n_params}; points = {result.n_used}",
            weighting,
        ]
        self.metrics_text.configure(state="normal")
        self.metrics_text.delete("1.0", "end")
        self.metrics_text.insert("1.0", "\n".join(lines))
        self.metrics_text.configure(state="disabled")

    def update_notes(self, result: FitResult, mode: str, cutoff: float):
        """Explain the physical interpretation conservatively."""
        mode_description = {"all": "all points", "down": "down-weighted", "exclude": "excluded above cutoff"}[mode]
        lines = [
            "Interpretation:",
            "",
            "Each component represents a phenomenological relaxation contribution, similar in form to a Debye/Cole–Cole process.",
            "f0 is the peak frequency; the effective timescale is τ = 1/(2πf0).",
            "By default, H0 is fixed at zero, assuming that the relaxation contribution",
            "approaches zero as f → 0.",
            "H0 can be fitted as a phenomenological measurement/model offset.",
            "",
            "Important: a single isothermal Hyst_Area(f) spectrum cannot uniquely identify",
            "a specific defect or migration pathway.",
            "Labels in the table are user-entered hypotheses, not automatically verified",
            "identifications.",
            "",
            f"High-frequency treatment: {mode_description}; f_cut = {cutoff:g} Hz.",
            "Check component stability when varying f_cut, β, and the number of",
            "components.",
            "Temperature-dependent measurements, as well as variation of film thickness,",
            "grain size, and device geometry, can help establish physical origins.",
        ]
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", "\n".join(lines))
        self.notes_text.configure(state="disabled")

    def plot_current_fit(self):
        self.ax.clear()
        self.ax.set_xscale("log")
        self.ax.set_xlabel("Frequency, Hz")
        self.ax.set_ylabel("Hysteresis area")
        self.ax.grid(True, which="both", alpha=0.20)

        ds = self.get_current_ds()
        result = self.current_fit
        if ds is None:
            self.canvas.draw_idle()
            return

        # Raw points
        self.ax.scatter(ds.frequency_hz, ds.hyst_area, s=38, label="Measured data", zorder=4)

        # Smooth interpolation of original data (display only; NOT used in fit)
        if self.smooth_var.get() and result is not None and len(result.y_smooth_x) > 1:
            self.ax.plot(result.y_smooth_x, result.y_smooth, linewidth=1.4, alpha=0.70,
                         label="Smoothed source data")

        if result is not None:
            self.ax.plot(result.x_fit, self.evaluate_total_dense(result), linewidth=2.6,
                         label=f"Total fit ({result.k} component(s))")
            for i, (f0, comp) in enumerate(zip(result.f0_hz, result.components_fit), start=1):
                self.ax.plot(result.x_fit, comp, linestyle="--", linewidth=1.5,
                             label=f"Component {i}: f0={fmt(f0)} Hz")
            if result.baseline > 0:
                self.ax.axhline(result.baseline, linestyle=":", linewidth=1.0, alpha=0.8, label=f"H0={fmt(result.baseline)}")

        self.ax.legend(loc="best", fontsize=8)
        title = f"{ds.device}: Hyst_Area(f)"
        if result is not None:
            title += f"  |  τ: " + ", ".join(f"{fmt(t)} s" for t in result.tau_s)
        self.ax.set_title(title, fontsize=11)
        self.canvas.draw_idle()

    @staticmethod
    def evaluate_total_dense(result: FitResult) -> np.ndarray:
        return result.y_fit

    def _result_rows(self, ds: FrequencyDataset, result: FitResult):
        """Build clean tabular data for the single Excel workbook export."""
        ions = [self.component_ion_vars[i].get() if i < len(self.component_ion_vars) else "Unassigned"
                for i in range(result.k)]
        paths = [self.component_path_vars[i].get() if i < len(self.component_path_vars) else "Unassigned"
                 for i in range(result.k)]

        params = [[
            "Device", "Component", "Amplitude_A", "f0_Hz", "tau_s", "H0", "Beta",
            "Weighting_mode", "Cutoff_Hz", "Weight_power", "Fit_baseline", "Model_selection",
            "R2_weighted", "RMSE_weighted", "RSS", "AIC", "AICc",
            "Ion_hypothesis", "Migration_path_hypothesis"
        ]]
        mode, cutoff_hz, power, _beta = self.parse_fit_controls()
        mode_name = {"all": "all", "down": "downweight", "exclude": "exclude"}[mode]
        selected_model = "auto_aicc" if self.model_var.get().startswith("Auto") else f"fixed_{result.k}_components"
        for i, (a, f0, tau) in enumerate(zip(result.amplitude, result.f0_hz, result.tau_s)):
            params.append([
                result.device, i + 1, float(a), float(f0), float(tau), float(result.baseline),
                float(result.beta), mode_name, float(cutoff_hz), float(power), bool(self.fit_baseline_var.get()),
                selected_model, float(result.r2), float(result.weighted_rmse), float(result.rss),
                float(result.aic), float(result.aicc), ions[i], paths[i]
            ])

        measured_headers = ["Frequency_Hz", "Measured_Hyst_Area", "Weight", "Total_Fit", "Residual", "H0"]
        measured_headers += [f"Component_{i}" for i in range(1, result.k + 1)]
        measured = [measured_headers]
        f = ds.frequency_hz
        y = ds.hyst_area
        y_pred = np.full_like(y, result.baseline, dtype=float)
        comp_values = []
        for a, f0 in zip(result.amplitude, result.f0_hz):
            c = debye_component(f, a, f0, result.beta)
            comp_values.append(c)
            y_pred += c
        for j in range(len(f)):
            measured.append([
                float(f[j]), float(y[j]), float(result.weights[j]), float(y_pred[j]),
                float(y_pred[j] - y[j]), float(result.baseline)
            ] + [float(c[j]) for c in comp_values])

        curve_headers = ["Frequency_Hz", "Smooth_Original", "Total_Fit", "H0"]
        curve_headers += [f"Component_{i}" for i in range(1, result.k + 1)]
        curve = [curve_headers]
        try:
            smooth_dense = PchipInterpolator(np.log10(result.y_smooth_x), result.y_smooth)(np.log10(result.x_fit))
            outside = (result.x_fit < result.y_smooth_x.min()) | (result.x_fit > result.y_smooth_x.max())
            smooth_dense = np.asarray(smooth_dense, dtype=float)
            smooth_dense[outside] = np.nan
        except Exception:
            smooth_dense = np.full_like(result.x_fit, np.nan)
        for j, freq in enumerate(result.x_fit):
            curve.append([
                float(freq), smooth_dense[j], float(result.y_fit[j]), float(result.baseline)
            ] + [float(c[j]) for c in result.components_fit])
        return params, measured, curve

    def export_results(self):
        if self.current_fit is None or self.current_ds is None:
            messagebox.showinfo("No fit result", "Run the fit first.")
            return

        ds = self.current_ds
        result = self.current_fit
        path = filedialog.asksaveasfilename(
            title="Save fit results",
            defaultextension=".xlsx",
            initialfile=f"{ds.device}_hysteresis_fit.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return

        params, measured, curve = self._result_rows(ds, result)
        try:
            write_simple_xlsx(path, {
                "Parameters": params,
                "Measured + Fit": measured,
                "Fit curves": curve,
            })
        except Exception as exc:
            messagebox.showerror("Export error", str(exc))
            return

        self.status_var.set(f"Saved {os.path.basename(path)} — 3 worksheets.")
        messagebox.showinfo(
            "Results saved",
            "An Excel workbook was created with the following worksheets:\n\n"
            "• Parameters — component parameters and fit metrics\n"
            "• Measured + Fit — measured points, total fit, residuals, and components\n"
            "• Fit curves — dense frequency grid for plotting\n\n"
            "The smoothed source curve is interpolated in log10(f),\n"
            "consistent with the logarithmic frequency axis.",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Fit frequency-dependent hysteresis-area spectra with a multi-relaxation model.")
    parser.add_argument("--config", type=Path, default=None, help="Path to a JSON settings file (optional).")
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    app = App(settings=settings)
    app.mainloop()


if __name__ == "__main__":
    main()
