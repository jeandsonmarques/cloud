import json
import math
import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle


class ExportManager:
    def __init__(self):
        self.export_dir = os.path.join(os.path.expanduser("~"), "QGIS_PowerBI_Exports")
        os.makedirs(self.export_dir, exist_ok=True)

    def _ensure_parent_dir(self, file_path):
        directory = os.path.dirname(file_path)
        if not directory:
            directory = self.export_dir
            file_path = os.path.join(directory, file_path)
        os.makedirs(directory, exist_ok=True)
        return file_path

    def export_data(self, summary_data, file_path, file_filter):
        """Exporta dados para vários formatos."""
        if "Excel" in file_filter:
            self.export_to_excel(summary_data, file_path)
        elif "CSV" in file_filter:
            self.export_to_csv(summary_data, file_path)
        elif "JSON" in file_filter:
            self.export_to_json(summary_data, file_path)
        elif "PDF" in file_filter:
            self.export_to_pdf(summary_data, file_path)

    def export_to_excel(self, summary_data, file_path):
        """Exporta para Excel com múltiplas abas."""
        file_path = self._ensure_parent_dir(file_path)
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            basic_stats = pd.DataFrame([summary_data.get("basic_stats", {})])
            basic_stats.to_excel(writer, sheet_name="Estatísticas_Básicas", index=False)

            grouped = summary_data.get("grouped_data") or {}
            if grouped:
                grouped_df = pd.DataFrame.from_dict(grouped, orient="index")
                grouped_df.to_excel(writer, sheet_name="Dados_Agrupados")

            percentiles = pd.DataFrame([summary_data.get("percentiles", {})])
            percentiles.to_excel(writer, sheet_name="Percentis", index=False)

    def export_to_csv(self, summary_data, file_path):
        """Exporta dados agrupados para CSV."""
        grouped = summary_data.get("grouped_data") or {}
        if not grouped:
            return

        file_path = self._ensure_parent_dir(file_path)
        df = pd.DataFrame.from_dict(grouped, orient="index")
        df.to_csv(file_path)

    def export_to_json(self, summary_data, file_path):
        """Exporta dados completos para JSON."""
        file_path = self._ensure_parent_dir(file_path)
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(summary_data, handle, indent=2, ensure_ascii=False)

    def export_to_pdf(self, summary_data, file_path):
        """Gera relatório em PDF com estatísticas e destaques visuais."""
        file_path = self._ensure_parent_dir(file_path)

        metadata = summary_data.get("metadata", {})
        stats = summary_data.get("basic_stats", {})
        percentiles = summary_data.get("percentiles", {})
        grouped = summary_data.get("grouped_data") or {}

        top_groups = []
        if grouped:
            top_groups = sorted(
                grouped.items(),
                key=lambda item: item[1].get("sum", 0),
                reverse=True,
            )[:10]

        def fmt(value, digits=2):
            if isinstance(value, (int, float)):
                if not math.isfinite(value):
                    return "-"
                return f"{value:,.{digits}f}"
            if value is None:
                return "-"
            return str(value)

        with PdfPages(file_path) as pdf:
            # Página 1 - Estatísticas e resumo textual
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.patch.set_facecolor("#F5F7FB")
            ax = fig.add_axes([0, 0, 1, 1])
            ax.axis("off")

            header = Rectangle(
                (0, 0.93),
                1,
                0.07,
                transform=ax.transAxes,
                color="#0078D4",
                zorder=0,
            )
            ax.add_patch(header)
            icon_bg = Rectangle(
                (0.02, 0.935),
                0.065,
                0.055,
                transform=ax.transAxes,
                color="#003A80",
                zorder=1,
            )
            ax.add_patch(icon_bg)

            icon_bars = [
                (0.024, 0.94, 0.014, 0.035, "#FFFFFF"),
                (0.041, 0.94, 0.014, 0.045, "#2DB79A"),
                (0.058, 0.94, 0.014, 0.055, "#5CC1F5"),
            ]
            for x, y, w, h, color in icon_bars:
                ax.add_patch(
                    Rectangle(
                        (x, y),
                        w,
                        h,
                        transform=ax.transAxes,
                        color=color,
                        zorder=2,
                        linewidth=0,
                        clip_on=False,
                    )
                )


            timestamp = metadata.get(
                "timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            ax.text(
                0.1,
                0.965,
                "Relatório Power BI Summarizer",
                color="white",
                fontsize=18,
                fontweight="bold",
                va="center",
            )
            ax.text(
                0.1,
                0.93,
                f"Camada: {metadata.get('layer_name', '-')}",
                color="white",
                fontsize=10,
                va="top",
            )
            ax.text(
                0.1,
                0.905,
                f"Campo: {metadata.get('field_name', '-')}",
                color="white",
                fontsize=10,
                va="top",
            )
            ax.text(
                0.98,
                0.93,
                timestamp,
                color="white",
                fontsize=10,
                ha="right",
                va="top",
            )

            ax.text(
                0.02,
                0.87,
                "Estatísticas Basicas",
                fontsize=14,
                color="#1F2933",
                fontweight="bold",
            )
            stats_lines = [
                ("Total", stats.get("total"), 2),
                ("Contagem", stats.get("count"), 0),
                ("Media", stats.get("average"), 2),
                ("Mediana", stats.get("median"), 2),
                ("Minimo", stats.get("min"), 2),
                ("Maximo", stats.get("max"), 2),
                ("Desvio Padrao", stats.get("std_dev"), 2),
            ]
            y_stats = 0.84
            for label, value, digits in stats_lines:
                ax.text(
                    0.03,
                    y_stats,
                    f"{label}:",
                    fontsize=11,
                    color="#475569",
                    fontweight="bold",
                )
                ax.text(
                    0.33,
                    y_stats,
                    fmt(value, digits),
                    fontsize=11,
                    color="#0A66C2",
                )
                y_stats -= 0.035

            ax.text(
                0.55,
                0.87,
                "Percentis",
                fontsize=14,
                color="#1F2933",
                fontweight="bold",
            )
            percent_lines = [
                ("P25", percentiles.get("p25"), 2),
                ("P50", percentiles.get("p50") or stats.get("median"), 2),
                ("P75", percentiles.get("p75"), 2),
                ("P90", percentiles.get("p90"), 2),
                ("P95", percentiles.get("p95"), 2),
            ]
            y_percent = 0.84
            for label, value, digits in percent_lines:
                ax.text(
                    0.56,
                    y_percent,
                    f"{label}:",
                    fontsize=11,
                    color="#475569",
                    fontweight="bold",
                )
                ax.text(
                    0.78,
                    y_percent,
                    fmt(value, digits),
                    fontsize=11,
                    color="#0A66C2",
                    ha="right",
                )
                y_percent -= 0.035

            info_lines = [
                ("Total de feicoes", stats.get("count"), 0),
                ("Filtro aplicado", summary_data.get("filter_description", "Nenhum"), None),
                ("Gerado em", timestamp, None),
            ]
            y_info = min(y_stats, y_percent) - 0.05
            ax.text(
                0.02,
                y_info + 0.03,
                "Informações adicionais",
                fontsize=14,
                color="#1F2933",
                fontweight="bold",
            )
            for label, value, digits in info_lines:
                ax.text(
                    0.03,
                    y_info,
                    f"{label}:",
                    fontsize=11,
                    color="#475569",
                    fontweight="bold",
                )
                formatted = fmt(value, digits) if isinstance(digits, int) else str(value)
                ax.text(
                    0.33,
                    y_info,
                    formatted,
                    fontsize=11,
                    color="#0A66C2",
                )
                y_info -= 0.032

            y_groups = y_info - 0.04
            if top_groups:
                ax.text(
                    0.02,
                    y_groups,
                    "Top 10 grupos (por soma)",
                    fontsize=14,
                    color="#1F2933",
                    fontweight="bold",
                )
                y_groups -= 0.04
                for index, (group_name, group_stats) in enumerate(top_groups, start=1):
                    clean_name = str(group_name) if group_name not in (None, "") else "Sem valor"
                    ax.text(
                        0.03,
                        y_groups,
                        f"{index:02d}. {clean_name}",
                        fontsize=10,
                        color="#475569",
                    )
                    ax.text(
                        0.55,
                        y_groups,
                        fmt(group_stats.get("sum"), 2),
                        fontsize=10,
                        color="#0A66C2",
                    )
                    ax.text(
                        0.78,
                        y_groups,
                        f"{fmt(group_stats.get('percentage'), 1)}%",
                        fontsize=10,
                        color="#16A34A",
                        ha="right",
                    )
                    y_groups -= 0.028
                    if y_groups < 0.1:
                        break

            ax.text(
                0.02,
                0.06,
                "Relatório gerado automaticamente pelo plugin Power BI Summarizer no QGIS.",
                fontsize=9,
                color="#64748B",
            )

            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

            # Página 2 - Gráfico de barras com grupos principais
            if top_groups:
                fig, ax = plt.subplots(figsize=(11.69, 8.27))
                fig.patch.set_facecolor("#F5F7FB")

                groups = [
                    str(item[0]) if item[0] not in (None, "") else "Sem valor"
                    for item in top_groups
                ]
                sums = [item[1].get("sum", 0) for item in top_groups]
                percentages = [item[1].get("percentage", 0) for item in top_groups]

                positions = range(len(groups))
                bars = ax.barh(
                    list(positions),
                    sums,
                    color="#0078D4",
                    edgecolor="#005A9E",
                )

                ax.invert_yaxis()
                ax.set_title(
                    "Top 10 grupos por soma",
                    fontsize=16,
                    fontweight="bold",
                    color="#1F2933",
                )
                ax.set_xlabel("Soma", fontsize=12, color="#1F2933")
                ax.set_yticks(list(positions))
                ax.set_yticklabels(groups, fontsize=11, color="#1F2933")
                ax.tick_params(axis="x", colors="#475569")
                ax.tick_params(axis="y", colors="#1F2933")
                ax.grid(axis="x", linestyle="--", alpha=0.3)

                for bar, percentage, total_sum in zip(bars, percentages, sums):
                    width = bar.get_width()
                    ax.text(
                        width,
                        bar.get_y() + bar.get_height() / 2,
                        f"{fmt(percentage, 1)}% ({fmt(total_sum, 0)})",
                        va="center",
                        ha="left",
                        fontsize=10,
                        color="#1F2933",
                    )

                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)




