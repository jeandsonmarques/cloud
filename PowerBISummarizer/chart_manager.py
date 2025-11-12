import os
from datetime import datetime

import matplotlib
import matplotlib.cm as cm  # Importação do ColorMap
import matplotlib.pyplot as plt

matplotlib.use("Agg")  # Para uso em background


class ChartManager:
    def __init__(self):
        self.output_dir = os.path.join(os.path.expanduser("~"), "QGIS_PowerBI_Charts")
        os.makedirs(self.output_dir, exist_ok=True)

    def create_interactive_charts(self, summary_data):
        """Cria múltiplos gráficos interativos."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Gráfico de barras para dados agrupados
        if summary_data["grouped_data"]:
            self.create_bar_chart(summary_data, timestamp)
            self.create_pie_chart(summary_data, timestamp)
            # O Box Plot só será chamado se houver dados de percentil
            self.create_box_plot(summary_data, timestamp)

        return self.output_dir

    def create_bar_chart(self, summary_data, timestamp):
        """Cria gráfico de barras."""
        groups = list(summary_data["grouped_data"].keys())
        sums = [data["sum"] for data in summary_data["grouped_data"].values()]

        plt.figure(figsize=(12, 8))

        # CORREÇÃO ANTERIOR (AttributeError: color_palette): usar um colormap nativo
        cmap = cm.get_cmap("viridis")
        colors = [cmap(i / len(groups)) for i in range(len(groups))]

        bars = plt.bar(groups, sums, color=colors)

        layer_name = summary_data["metadata"]["layer_name"]
        plt.title(f"Soma por Grupo - {layer_name}", fontsize=14, fontweight="bold")
        plt.xlabel("Grupos")
        plt.ylabel("Soma")
        plt.xticks(rotation=45, ha="right")

        # Adiciona valores nas barras
        for bar, value in zip(bars, sums):
            plt.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:,.0f}",
                ha="center",
                va="bottom",
            )

        plt.tight_layout()
        plt.savefig(
            os.path.join(self.output_dir, f"bar_chart_{timestamp}.png"),
            dpi=300,
            bbox_inches="tight",
        )
        plt.close()

    def create_pie_chart(self, summary_data, timestamp):
        """Cria gráfico de pizza."""
        groups = list(summary_data["grouped_data"].keys())
        percentages = [data["percentage"] for data in summary_data["grouped_data"].values()]

        plt.figure(figsize=(10, 8))
        plt.pie(percentages, labels=groups, autopct="%1.1f%%", startangle=90)
        layer_name = summary_data["metadata"]["layer_name"]
        plt.title(f"Distribuição Percentual - {layer_name}", fontsize=14, fontweight="bold")
        plt.axis("equal")
        plt.tight_layout()
        plt.savefig(
            os.path.join(self.output_dir, f"pie_chart_{timestamp}.png"),
            dpi=300,
            bbox_inches="tight",
        )
        plt.close()

    def create_box_plot(self, summary_data, timestamp):
        """Cria box plot para estatísticas."""
        stats = summary_data["basic_stats"]
        percentiles = summary_data.get("percentiles", {})

        # Adição de verificação de segurança (caso não haja dados)
        if not percentiles or "p25" not in percentiles or "p75" not in percentiles:
            return

        fig, ax = plt.subplots(figsize=(10, 6))

        # CORREÇÃO DO ERRO 'p25': acessar p25 e p75 do dicionário 'percentiles'
        data_for_box_plot = [
            stats["min"],
            percentiles["p25"],
            stats["median"],
            percentiles["p75"],
            stats["max"],
        ]

        ax.boxplot([data_for_box_plot], vert=True, patch_artist=True)

        layer_name = summary_data["metadata"]["layer_name"]
        ax.set_title(f"Estatísticas - {layer_name}", fontsize=14, fontweight="bold")
        ax.set_ylabel("Valores")
        ax.set_xticklabels([f"n={stats['count']}"])

        plt.tight_layout()
        plt.savefig(
            os.path.join(self.output_dir, f"box_plot_{timestamp}.png"),
            dpi=300,
            bbox_inches="tight",
        )
        plt.close()

