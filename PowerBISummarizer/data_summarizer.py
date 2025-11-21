import base64
import os
import re
import traceback
from datetime import datetime
from io import BytesIO
from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer, QTranslator, Qt, QVariant
from qgis.PyQt.QtGui import QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFieldProxyModel,
    QgsFields,
    QgsMapLayerProxyModel,
    QgsGeometry,
    QgsMapLayerStyle,
    QgsProject,
    QgsMessageLog,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
    Qgis,
)
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

from .dashboard_widget import DashboardWidget
from .export_manager import ExportManager
from .result_style import apply_result_style
from .ui_main_dialog import Ui_PowerBISummarizerDialog
from .layout_nav import SidebarController
from .integration_panel import IntegrationPanel
from .interactive_table import InteractiveTable
from .pivot_table_widget import PivotTableWidget
from .power_query_table import PowerQueryTable, PROTECTED_COLUMNS_DEFAULT
from .palette import palette_context
from .slim_dialogs import SlimDialogBase, SlimLayerSelectionDialog, slim_get_item
from .browser_integration import register_browser_provider, unregister_browser_provider
from . import resources_rc  # noqa: F401


def find_common_field_values(
    layer_a: QgsVectorLayer,
    field_a: str,
    layer_b: QgsVectorLayer,
    field_b: str,
    return_field: str,
):
    """
    Compara valores entre duas camadas e retorna os registros coincidentes da segunda camada.

    Returns
    -------
    dict
        Mapeia cada valor coincidência para a lista de valores do campo de retorno.
    """
    if not layer_a or not isinstance(layer_a, QgsVectorLayer):
        raise ValueError("Camada origem inválida.")
    if not layer_b or not isinstance(layer_b, QgsVectorLayer):
        raise ValueError("Camada alvo inválida.")

    if field_a not in layer_a.fields().names():
        raise ValueError(f"Campo '{field_a}' não encontrado na camada origem.")
    if field_b not in layer_b.fields().names():
        raise ValueError(f"Campo '{field_b}' não encontrado na camada alvo.")
    if return_field not in layer_b.fields().names():
        raise ValueError(f"Campo '{return_field}' não encontrado na camada alvo.")

    index_a = layer_a.fields().indexFromName(field_a)
    compare_index_b = layer_b.fields().indexFromName(field_b)
    return_index_b = layer_b.fields().indexFromName(return_field)

    values_a = set()
    for feature in layer_a.getFeatures():
        value = feature[index_a]
        if value not in (None, ""):
            values_a.add(value)

    matches = {}
    if not values_a:
        return matches

    for feature in layer_b.getFeatures():
        compare_value = feature[compare_index_b]
        if compare_value in values_a:
            matches.setdefault(compare_value, []).append(feature[return_index_b])

    return matches


def __apply_theme_once(target):
    """Tenta aplicar o stylesheet do plugin uma única vez."""
    try:
        base_dir = os.path.dirname(__file__)
        qss_path = os.path.join(base_dir, "resources", "style.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as handler:
                qss = handler.read()
            if hasattr(target, "iface") and hasattr(target.iface, "mainWindow"):
                target.iface.mainWindow().setStyleSheet(qss)
            elif hasattr(target, "setStyleSheet"):
                target.setStyleSheet(qss)
    except Exception:
        pass


class PowerBISummarizer:
    def __init__(self, iface):
        try:
            __apply_theme_once(self)
        except Exception:
            pass

        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(
            self.plugin_dir, "i18n", f"PowerBISummarizer_{locale}.qm"
        )
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr("Power BI Summarizer")
        self.dlg = None
        self._browser_provider = None

    def tr(self, message):
        return QCoreApplication.translate("PowerBISummarizer", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "resources", "icon.svg")
        new_icon_path = os.path.join(self.plugin_dir, "resources", "icons", "cloud_database.svg")
        main_icon = QIcon(":/powerbi_summarizer_icons/cloud_database.svg")
        if main_icon.isNull():
            main_icon = QIcon(new_icon_path if os.path.exists(new_icon_path) else icon_path)
        self.action = QAction(
            main_icon,
            self.tr("Power BI Summarizer"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.action.setWhatsThis(
            self.tr("Resume dados de diferentes camadas como no Power BI")
        )

        self.actions.append(self.action)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

        # Add Integration menu action (standalone page)
        self.integration_action = QAction(
            QIcon(icon_path),
            self.tr("Integração / Fontes Externas"),
            self.iface.mainWindow(),
        )
        self.integration_action.triggered.connect(self.open_integration_dialog)
        self.actions.append(self.integration_action)
        self.iface.addPluginToMenu(self.menu, self.integration_action)

        try:
            if self._browser_provider is None:
                self._browser_provider = register_browser_provider()
        except Exception as exc:
            self._browser_provider = None
            message = f"Falha ao registrar nó PowerBI Summarizer no Navegador: {exc}"
            QgsMessageLog.logMessage(message, "PowerBISummarizer", Qgis.Critical)
            print(message)
            traceback.print_exc()

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self._browser_provider is not None:
            try:
                unregister_browser_provider(self._browser_provider)
            finally:
                self._browser_provider = None

    def run(self):
        try:
            __apply_theme_once(self)
        except Exception:
            pass

        if not self.dlg:
            self.dlg = PowerBISummarizerDialog(self.iface)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def open_integration_dialog(self):
        # Open as a full page inside the main plugin dialog, similar to 'Sobre'
        try:
            if not self.dlg:
                self.dlg = PowerBISummarizerDialog(self.iface)
            self.dlg.show()
            self.dlg.raise_()
            self.dlg.activateWindow()
            if hasattr(self.dlg, "sidebar") and self.dlg.sidebar:
                try:
                    self.dlg.sidebar.show_integration_page()
                except Exception:
                    pass
        except Exception as exc:
            QMessageBox.critical(self.iface.mainWindow(), "Integração", f"Falha ao abrir: {exc}")

    # Exposed to SidebarController to open the in-dialog full page
    def open_external_integration_dialog(self):
        try:
            if not self.dlg:
                self.dlg = PowerBISummarizerDialog(self.iface)
            self.dlg.show()
            self.dlg.raise_()
            self.dlg.activateWindow()
            if hasattr(self.dlg, "sidebar") and self.dlg.sidebar:
                self.dlg.sidebar.show_integration_page()
        except Exception as exc:
            QMessageBox.critical(self, "Integração", f"Falha ao abrir: {exc}")

    def _get_layer_by_name(self, layer_name: str):
        """Retorna a primeira camada cujo nome corresponde exatamente ao informado."""
        if not layer_name:
            return None

        matches = QgsProject.instance().mapLayersByName(layer_name)
        return matches[0] if matches else None

    def match_layer_fields(
        self,
        source_layer_name: str,
        source_field_name: str,
        target_layer_name: str,
        target_compare_field: str,
        target_return_field: str,
    ):
        """
        Localiza valores coincidentes entre duas camadas e retorna dados do campo alvo.

        Parameters
        ----------
        source_layer_name: Nome da primeira camada.
        source_field_name: Campo da primeira camada cujos valores serão usados na comparação.
        target_layer_name: Nome da camada alvo.
        target_compare_field: Campo da camada alvo que deve ser comparado com os valores da camada origem.
        target_return_field: Campo da camada alvo cujo valor será retornado quando houver correspondência.

        Returns
        -------
        dict
            Dicionário mapeando cada valor coincidente para uma lista de valores
            encontrados no campo alvo da segunda camada.
        """
        layer_a = self._get_layer_by_name(source_layer_name)
        layer_b = self._get_layer_by_name(target_layer_name)

        if not layer_a:
            raise ValueError(f"Camada origem não encontrada: {source_layer_name}")
        if not layer_b:
            raise ValueError(f"Camada alvo não encontrada: {target_layer_name}")

        return find_common_field_values(
            layer_a,
            source_field_name,
            layer_b,
            target_compare_field,
            target_return_field,
        )


class PowerBISummarizerDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ui = Ui_PowerBISummarizerDialog()
        self.ui.setupUi(self)
        self._square_scopes = []
        for attr in ("pageResultados", "pageComparar"):
            scope = getattr(self.ui, attr, None)
            if scope is not None:
                scope.setProperty("squareScope", True)
                self._square_scopes.append(scope)
        self._square_theme_applied = False
        try:
            self.ui.minimize_btn.clicked.connect(self.showMinimized)
            self.ui.maximize_btn.clicked.connect(self.toggle_window_state)
        except Exception:
            pass

        # External integration state (not used in main dialog anymore)
        self.external_df = None
        self.external_last_path_key = "PowerBISummarizer/external/lastPath"

        logo_path = os.path.join(
            os.path.dirname(__file__), "resources", "icons", "plugin_logo.svg"
        )
        self.setWindowIcon(QIcon(logo_path))

        context = palette_context()
        base_font = QFont(context.get("font_family", "Montserrat"), context.get("font_body_size", 11))
        base_font.setWeight(QFont.Medium)
        self.setFont(base_font)

        self.export_manager = ExportManager()
        self.dashboard_widget = DashboardWidget()
        # Inject QuickOSM-like sidebar navigation without altering the ui file
        try:
            self.sidebar = SidebarController(self)
        except Exception:
            self.sidebar = None

        self.export_formats = {
            "Excel (.xlsx)": {"filter": "Excel (*.xlsx)", "extension": ".xlsx"},
            "CSV (.csv)": {"filter": "CSV (*.csv)", "extension": ".csv"},
            "PDF (.pdf)": {"filter": "PDF (*.pdf)", "extension": ".pdf"},
            "JSON (.json)": {"filter": "JSON (*.json)", "extension": ".json"},
        }
        self._timestamp_pattern = re.compile(r"_\d{8}_\d{6}$")
        self._updating_export_path = False
        self._export_base_path = ""

        self.current_summary_data = None
        self.integration_datasets: Dict[str, pd.DataFrame] = {}
        self._active_numeric_field = None
        self._compare_preview_layer_id = None
        self._last_compare_context = {}

        self.ui.export_format_combo.addItems(self.export_formats.keys())
        self.ui.export_format_combo.setCurrentIndex(0)

        # Prepare widgets for the Results view
        try:
            layout = self.ui.results_body_layout
            self.pivot_widget = PivotTableWidget(self.ui.results_body)
            layout.addWidget(self.pivot_widget)
            try:
                self.pivot_widget.set_auto_update_checkbox(self.ui.auto_update_check)
            except Exception:
                pass
            try:
                self.pivot_widget.add_dashboard_button(self.ui.dashboard_btn)
            except Exception:
                pass

            self.summary_message_widget = QTextEdit(self.ui.results_body)
            self.summary_message_widget.setReadOnly(True)
            self.summary_message_widget.setStyleSheet(
                "font-family: 'Montserrat', 'Segoe UI', sans-serif; font-size: 10.5pt;"
            )
            self.summary_message_widget.setVisible(False)
            layout.addWidget(self.summary_message_widget)

            self.table_view = InteractiveTable(self.ui.results_body)
            layout.addWidget(self.table_view)
            self.table_view.setVisible(False)
        except Exception:
            self.pivot_widget = None
            self.summary_message_widget = None
            self.table_view = None

        try:
            compare_layout = self.ui.compare_results_layout
            self.compare_message_widget = QTextEdit(self.ui.compare_results_frame)
            self.compare_message_widget.setReadOnly(True)
            self.compare_message_widget.setStyleSheet(
                "font-family: 'Montserrat', 'Segoe UI', sans-serif; font-size: 10.5pt;"
            )
            compare_layout.addWidget(self.compare_message_widget)

            self.compare_query_table = PowerQueryTable(self.ui.compare_results_frame)
            self.compare_query_table.setVisible(False)
            self.compare_query_table.set_materialize_callback(self._materialize_power_query_result)
            compare_layout.addWidget(self.compare_query_table)
        except Exception:
            self.compare_message_widget = None
            self.compare_query_table = None

        self.setup_connections()
        self.load_layers()
        self.apply_styles()
        self.on_export_format_changed()
        self.setup_compare_controls()

        try:
            self.show_summary_prompt()
        except Exception:
            pass

        self.integration_panel = None
        self.integration_scroll = None
        try:
            layout = self.ui.pageIntegracao.layout()
            if layout is None:
                layout = QVBoxLayout(self.ui.pageIntegracao)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            placeholder = getattr(self.ui, "integration_placeholder", None)
            if placeholder is not None:
                layout.removeWidget(placeholder)
                placeholder.deleteLater()
                self.ui.integration_placeholder = None

            scroll = QScrollArea(self.ui.pageIntegracao)
            scroll.setObjectName("integrationScrollArea")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            layout.addWidget(scroll, 1)
            self.integration_scroll = scroll

            panel = IntegrationPanel(self, self.iface)
            scroll.setWidget(panel)
            self.integration_panel = panel

            manage_btn = getattr(self.ui, "manage_connections_btn", None)
            if manage_btn is not None:
                manage_btn.clicked.connect(panel.open_connections_manager)
        except Exception:
            self.integration_panel = None
    def toggle_window_state(self):
        if self.isMaximized():
            self.showNormal()
            try:
                self.ui.maximize_btn.setText("Max")
                self.ui.maximize_btn.setToolTip("Maximizar")
            except Exception:
                pass
        else:
            self.showMaximized()
            try:
                self.ui.maximize_btn.setText("Res")
                self.ui.maximize_btn.setToolTip("Restaurar")
            except Exception:
                pass

    def apply_styles(self):
        """Aplica stylesheets personalizados, se existirem."""
        style_path = os.path.join(os.path.dirname(__file__), "resources", "style.qss")
        if not os.path.exists(style_path):
            self._apply_square_theme()
            return

        try:
            from string import Template

            with open(style_path, "r", encoding="utf-8") as handler:
                template = Template(handler.read())
            context = palette_context()
            self.setStyleSheet(template.safe_substitute(context))
        except Exception:
            try:
                with open(style_path, "r", encoding="utf-8") as handler:
                    self.setStyleSheet(handler.read())
            except Exception:
                pass
        self._apply_square_theme()

    def _apply_square_theme(self):
        if getattr(self, "_square_theme_applied", False):
            return
        if not getattr(self, "_square_scopes", None):
            return
        square_path = os.path.join(os.path.dirname(__file__), "ui", "square.qss")
        if not os.path.exists(square_path):
            return
        try:
            with open(square_path, "r", encoding="utf-8") as handler:
                square_qss = handler.read()
        except Exception:
            return
        existing = self.styleSheet() or ""
        combined = f"{existing}\n{square_qss}" if existing else square_qss
        self.setStyleSheet(combined)
        self._square_theme_applied = True

    def setup_connections(self):
        self.ui.layer_combo.layerChanged.connect(self.on_layer_changed)
        self.ui.dashboard_btn.clicked.connect(self.show_dashboard)

        self.ui.export_execute_btn.clicked.connect(self.export_results)
        self.ui.export_browse_btn.clicked.connect(self.choose_export_path)
        self.ui.export_format_combo.currentIndexChanged.connect(
            self.on_export_format_changed
        )
        self.ui.export_path_edit.editingFinished.connect(self.on_export_path_edited)
        self.ui.compare_source_layer_combo.layerChanged.connect(
            self.on_compare_source_layer_changed
        )
        self.ui.compare_target_layer_combo.layerChanged.connect(
            self.on_compare_target_layer_changed
        )
        self.ui.compare_execute_btn.clicked.connect(self.execute_layer_comparison)
        self.ui.compare_select_matches_btn.clicked.connect(
            self.select_matched_features
        )
        self.ui.compare_create_layer_btn.clicked.connect(
            self.create_comparison_temp_layer
        )
        self.ui.compare_materialize_btn.clicked.connect(self.materialize_comparison_result)
        self.ui.compare_params_toggle_btn.toggled.connect(self.toggle_compare_params)
        self.ui.footer_about_btn.clicked.connect(self.show_about_dialog)

        # Auto atualização também para 'Comparar'
        try:
            self.ui.compare_source_field_combo.fieldChanged.connect(self._compare_auto_update)
            self.ui.compare_target_field_combo.fieldChanged.connect(self._compare_auto_update)
            self.ui.compare_return_field_combo.fieldChanged.connect(self._compare_auto_update)
            self.ui.compare_source_layer_combo.layerChanged.connect(self._compare_auto_update)
            self.ui.compare_target_layer_combo.layerChanged.connect(self._compare_auto_update)
        except Exception:
            pass

        # External integration connections removed (handled by dedicated dialog)

    def _compare_auto_update(self):
        """Se 'Atualização automática' estiver marcada, executa a comparação.

        Evita avisos quando campos/camadas não estão prontos.
        """
        try:
            if not self.ui.auto_update_check.isChecked():
                return
            layer_a = self.ui.compare_source_layer_combo.currentLayer()
            layer_b = self.ui.compare_target_layer_combo.currentLayer()
            field_a = self.ui.compare_source_field_combo.currentField()
            compare_field = self.ui.compare_target_field_combo.currentField()
            return_field = self.ui.compare_return_field_combo.currentField()
            if not (layer_a and layer_b and field_a and compare_field and return_field):
                return
            QTimer.singleShot(500, self.execute_layer_comparison)
        except Exception:
            pass

    def _render_comparison_full_table(
        self,
        layer_a,
        layer_b,
        field_a,
        compare_field,
        return_field,
        matches=None,
    ):
        try:
            if matches is None:
                matches = find_common_field_values(layer_a, field_a, layer_b, compare_field, return_field)
            if not matches:
                return False

            target_geom_map = {}
            target_feature_map = {}
            try:
                compare_index_b = layer_b.fields().indexFromName(compare_field)
            except Exception:
                compare_index_b = -1
            if compare_index_b != -1:
                for target_feat in layer_b.getFeatures():
                    key = target_feat[compare_index_b]
                    if key in target_geom_map:
                        continue
                    try:
                        geom_hex = target_feat.geometry().asWkb().hex()
                    except Exception:
                        geom_hex = ""
                    target_geom_map[key] = geom_hex
                    target_feature_map[key] = target_feat.id()

            rows = []
            for feat in layer_a.getFeatures():
                key = feat[layer_a.fields().indexFromName(field_a)]
                if key not in matches:
                    continue
                row = {field.name(): feat[field.name()] for field in layer_a.fields()}
                values = matches[key]
                result_label = return_field if return_field else "Valores"
                row[f"{result_label}_matches"] = ", ".join(str(v) for v in values)
                row["match_count"] = len(values)
                row["__feature_id"] = feat.id()
                row["__target_feature_id"] = target_feature_map.get(key)
                geom_hex = target_geom_map.get(key)
                if not geom_hex:
                    try:
                        geom_hex = feat.geometry().asWkb().hex()
                    except Exception:
                        geom_hex = ""
                row["__geometry_wkb"] = geom_hex
                rows.append(row)

            if not rows or getattr(self, "compare_query_table", None) is None:
                return False

            df = pd.DataFrame(rows)
            self.compare_query_table.set_dataframe(df, protected_columns=PROTECTED_COLUMNS_DEFAULT)
            self._last_compare_context = {
                "source_layer_id": layer_a.id() if layer_a else None,
                "target_layer_id": layer_b.id() if layer_b else None,
                "geometry_layer_id": (layer_b.id() if layer_b else (layer_a.id() if layer_a else None)),
                "source_layer_name": layer_a.name() if layer_a else "",
                "target_layer_name": layer_b.name() if layer_b else "",
            }
            self._publish_compare_preview_layer(df, layer_b or layer_a)
            self._set_compare_view("table")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Comparação de camadas", f"Falha ao gerar pré-visualização: {exc}")
        return False

    def _publish_compare_preview_layer(self, df: pd.DataFrame, source_layer: Optional[QgsVectorLayer]):
        if source_layer is None or df.empty or "__geometry_wkb" not in df.columns:
            if getattr(self, "_compare_preview_layer_id", None):
                try:
                    layer = QgsProject.instance().mapLayer(self._compare_preview_layer_id)
                    if layer is not None:
                        QgsProject.instance().removeMapLayer(layer)
                except Exception:
                    pass
                self._compare_preview_layer_id = None
            return
        try:
            geom_type = QgsWkbTypes.displayString(source_layer.wkbType())
            crs_authid = source_layer.crs().authid()
            uri = geom_type if not crs_authid else f"{geom_type}?crs={crs_authid}"

            if getattr(self, "_compare_preview_layer_id", None):
                try:
                    old_layer = QgsProject.instance().mapLayer(self._compare_preview_layer_id)
                    if old_layer is not None:
                        QgsProject.instance().removeMapLayer(old_layer)
                except Exception:
                    pass

            preview_name = self._unique_layer_name(f"Previa_Comparacao_{source_layer.name()}")
            temp_layer = QgsVectorLayer(uri, preview_name, "memory")
            if not temp_layer or not temp_layer.isValid():
                return

            provider = temp_layer.dataProvider()
            qfields = QgsFields()
            existing = []
            for column in df.columns:
                if column in PROTECTED_COLUMNS_DEFAULT:
                    continue
                field_name = self._make_unique_field_name(existing, column)
                qvariant = self._variant_type_for_series(df[column])
                qfields.append(QgsField(field_name, qvariant))
                existing.append(field_name)
            if not provider.addAttributes(qfields):
                return
            temp_layer.updateFields()

            features = []
            for _, row in df.iterrows():
                geom_hex = row.get("__geometry_wkb")
                if not geom_hex:
                    continue
                try:
                    geometry = QgsGeometry.fromWkb(bytes.fromhex(geom_hex))
                except Exception:
                    continue
                feature = QgsFeature(temp_layer.fields())
                feature.setGeometry(geometry)
                attrs = []
                for column in df.columns:
                    if column in PROTECTED_COLUMNS_DEFAULT:
                        continue
                    attrs.append(self._python_value(row[column]))
                feature.setAttributes(attrs)
                features.append(feature)

            if not features:
                return
            if not provider.addFeatures(features):
                return
            temp_layer.updateExtents()
            QgsProject.instance().addMapLayer(temp_layer)
            self._compare_preview_layer_id = temp_layer.id()
        except Exception:
            pass

    def _set_results_view(self, mode: str):
        """Switch between pivot (summary), message (HTML) and table (comparison) views."""
        pivot_visible = mode == "pivot"
        message_visible = mode == "message"
        table_visible = mode == "table"

        pivot_widget = getattr(self, "pivot_widget", None)
        if pivot_widget is not None:
            pivot_widget.setVisible(pivot_visible)

        message_widget = getattr(self, "summary_message_widget", None)
        if message_widget is not None:
            message_widget.setVisible(message_visible)

        table_widget = getattr(self, "table_view", None)
        if table_widget is not None:
            table_widget.setVisible(table_visible)

    def _set_compare_view(self, mode: str):
        message_visible = mode == "message"
        table_visible = mode == "table"

        message_widget = getattr(self, "compare_message_widget", None)
        if message_widget is not None:
            message_widget.setVisible(message_visible)

        table_widget = getattr(self, "compare_query_table", None)
        if table_widget is not None:
            table_widget.setVisible(table_visible)

    def show_results_message(self, html: str):
        """Display HTML content in the results area."""
        message_widget = getattr(self, "summary_message_widget", None)
        if message_widget is None:
            return
        try:
            message_widget.setHtml(apply_result_style(html))
        except Exception:
            message_widget.setHtml(html)
        self._set_results_view("message")

    def show_compare_message(self, html: str):
        widget = getattr(self, "compare_message_widget", None)
        if widget is None:
            return
        try:
            widget.setHtml(apply_result_style(html))
        except Exception:
            widget.setHtml(html)
        self._set_compare_view("message")

    def show_summary_prompt(self):
        self._set_integration_footer_visible(False)
        self.show_results_message(
            "<p style='margin:8px 0;'>Selecione uma camada e clique em Gerar Resumo.</p>"
        )

    def show_compare_prompt(self):
        self._set_integration_footer_visible(False)
        table = getattr(self, "compare_query_table", None)
        data_available = False
        if table is not None:
            try:
                df = table.dataframe()
                data_available = df is not None and not df.empty
            except Exception:
                data_available = False
        if data_available:
            try:
                self.ui.stackedWidget.setCurrentWidget(self.ui.pageComparar)
            except Exception:
                pass
            self._set_compare_view("table")
            return
        self.show_compare_message(
            "<p style='margin:8px 0;'>Defina os parametros de comparacao e execute a analise.</p>"
        )
        try:
            self.ui.compare_params_toggle_btn.setChecked(False)
        except Exception:
            pass
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageComparar)
        except Exception:
            pass

    def toggle_compare_params(self, checked: bool):
        container = getattr(self.ui, "compare_params_container", None)
        if container is None:
            return
        container.setVisible(bool(checked))
        try:
            self.ui.compare_params_toggle_btn.setText("Parametros v" if checked else "Parametros >")
        except Exception:
            pass

    def _set_integration_footer_visible(self, visible: bool):
        btn = getattr(self.ui, "manage_connections_btn", None)
        if btn is not None:
            btn.setVisible(bool(visible))

    def show_integration_page(self):
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageIntegracao)
        except Exception:
            pass
        scroll = getattr(self, "integration_scroll", None)
        if scroll is not None:
            try:
                scroll.verticalScrollBar().setValue(0)
            except Exception:
                pass
        self._set_integration_footer_visible(True)
        panel = getattr(self, "integration_panel", None)
        if panel is not None:
            try:
                panel.refresh_recents()
            except Exception:
                pass

    def register_integration_dataframe(self, df: pd.DataFrame, metadata: Dict) -> Dict:
        if df is None or df.empty:
            return {}

        descriptor = dict(metadata or {})
        descriptor.setdefault("display_name", descriptor.get("source_path") or "Dados externos")
        descriptor.setdefault("connector", descriptor.get("connector") or "Fonte externa")
        descriptor.setdefault("record_count", int(len(df)))
        descriptor.setdefault("timestamp", descriptor.get("timestamp") or datetime.now().isoformat())

        summary_data = self._build_dataframe_summary(df, descriptor)
        self.current_summary_data = summary_data
        self.display_advanced_summary(summary_data)
        self.update_charts_preview(summary_data)
        self.prepare_export_tab_defaults(summary_data)

        layer = self._create_memory_table_from_dataframe(df, descriptor)
        if layer is not None and layer.isValid():
            descriptor["layer_id"] = layer.id()
            descriptor["layer_name"] = layer.name()
            self.integration_datasets[layer.id()] = df.copy()

        self.sidebar.show_results_page()
        self._set_integration_footer_visible(False)
        return descriptor

    def _build_dataframe_summary(self, df: pd.DataFrame, descriptor: Dict) -> Dict:
        numeric_columns = [col for col in df.columns if ptypes.is_numeric_dtype(df[col])]
        stats = {
            "total": 0.0,
            "count": int(len(df)),
            "average": 0.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
            "std_dev": 0.0,
        }
        percentiles = {}

        if numeric_columns:
            series = pd.to_numeric(df[numeric_columns[0]], errors="coerce").dropna()
            if not series.empty:
                stats.update(
                    {
                        "total": float(series.sum()),
                        "average": float(series.mean()),
                        "min": float(series.min()),
                        "max": float(series.max()),
                        "median": float(series.median()),
                        "std_dev": float(series.std()),
                    }
                )
                percentiles = {
                    "p25": float(series.quantile(0.25)),
                    "p50": float(series.quantile(0.50)),
                    "p75": float(series.quantile(0.75)),
                    "p90": float(series.quantile(0.90)),
                    "p95": float(series.quantile(0.95)),
                }

        metadata = {
            "layer_name": descriptor.get("display_name", "Dados externos"),
            "field_name": numeric_columns[0] if numeric_columns else "-",
            "timestamp": descriptor.get("timestamp", datetime.now().isoformat()),
            "total_features": len(df),
            "source": descriptor.get("connector"),
        }

        return {
            "basic_stats": stats,
            "grouped_data": {},
            "percentiles": percentiles,
            "metadata": metadata,
            "filter_description": "Nenhum",
            "raw_data": {
                "columns": list(df.columns),
                "rows": df.to_dict(orient="records"),
            },
        }

    def _create_memory_table_from_dataframe(self, df: pd.DataFrame, descriptor: Dict) -> Optional[QgsVectorLayer]:
        try:
            base_name = (descriptor.get("display_name") or "Tabela externa").strip()
            if not base_name:
                base_name = "Tabela externa"

            project = QgsProject.instance()
            existing_names = {layer.name() for layer in project.mapLayers().values()}
            name = base_name
            suffix = 2
            while name in existing_names:
                name = f"{base_name} ({suffix})"
                suffix += 1

            layer = QgsVectorLayer("None", name, "memory")
            provider = layer.dataProvider()
            fields = QgsFields()
            for column in df.columns:
                variant = self._map_series_to_variant(df[column])
                fields.append(QgsField(column[:254], variant))
            provider.addAttributes(fields)
            layer.updateFields()

            features = []
            columns = list(df.columns)
            for _, row in df.iterrows():
                feature = QgsFeature()
                feature.setFields(fields)
                attrs = []
                for column in columns:
                    value = row[column]
                    if pd.isna(value):
                        attrs.append(None)
                    elif ptypes.is_datetime64_any_dtype(df[column]):
                        try:
                            attrs.append(pd.to_datetime(value).to_pydatetime())
                        except Exception:
                            attrs.append(str(value))
                    else:
                        attrs.append(value.item() if hasattr(value, "item") else value)
                feature.setAttributes(attrs)
                features.append(feature)
            if features:
                provider.addFeatures(features)
            layer.updateExtents()
            project.addMapLayer(layer)
            return layer
        except Exception:
            return None

    def _map_series_to_variant(self, series: pd.Series) -> QVariant.Type:
        if ptypes.is_integer_dtype(series):
            return QVariant.LongLong
        if ptypes.is_float_dtype(series):
            return QVariant.Double
        if ptypes.is_bool_dtype(series):
            return QVariant.Bool
        if ptypes.is_datetime64_any_dtype(series):
            return QVariant.DateTime
        return QVariant.String

    def load_layers(self):
        """QgsMapLayerComboBox já lida automaticamente com as camadas."""
        pass

    def setup_compare_controls(self):
        combos = [
            self.ui.compare_source_layer_combo,
            self.ui.compare_target_layer_combo,
        ]
        for combo in combos:
            combo.setFilters(QgsMapLayerProxyModel.VectorLayer)

        self.on_compare_source_layer_changed()
        self.on_compare_target_layer_changed()

    def on_compare_source_layer_changed(self):
        layer = self.ui.compare_source_layer_combo.currentLayer()
        self.ui.compare_source_field_combo.setLayer(layer)
        self.ui.compare_source_field_combo.setFilters(QgsFieldProxyModel.AllTypes)

    def on_compare_target_layer_changed(self):
        layer = self.ui.compare_target_layer_combo.currentLayer()
        self.ui.compare_target_field_combo.setLayer(layer)
        self.ui.compare_target_field_combo.setFilters(QgsFieldProxyModel.AllTypes)
        self.ui.compare_return_field_combo.setLayer(layer)
        self.ui.compare_return_field_combo.setFilters(QgsFieldProxyModel.AllTypes)

    def execute_layer_comparison(self):
        layer_a = self.ui.compare_source_layer_combo.currentLayer()
        layer_b = self.ui.compare_target_layer_combo.currentLayer()
        field_a = self.ui.compare_source_field_combo.currentField()
        compare_field = self.ui.compare_target_field_combo.currentField()
        return_field = self.ui.compare_return_field_combo.currentField()

        if not layer_a or not layer_b or not field_a or not compare_field or not return_field:
            QMessageBox.warning(
                self,
                "Comparação de Camadas",
                "Selecione todas as camadas e campos antes de executar a comparação.",
            )
            return

        try:
            matches = find_common_field_values(
                layer_a, field_a, layer_b, compare_field, return_field
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Comparação de Camadas", str(exc))
            return

        if not matches:
            html = "<p><strong>Nenhuma correspondência encontrada.</strong></p>"
        else:
            rows = []
            for value, results in matches.items():
                values_str = ", ".join(str(v) if v not in (None, "") else "(vazio)" for v in results)
                rows.append(
                    f"<tr><td>{self._escape_html(str(value))}</td><td>{self._escape_html(values_str)}</td></tr>"
                )
            table = (
                "<table><tr><th>Valor coincidência</th><th>Valores retornados</th></tr>"
                + "".join(rows)
                + "</table>"
            )
            html = f"<div><h3>Resultados da comparação</h3>{table}</div>"

        self.show_compare_message(html)
        # Try to render interactive table with all target layer fields
        if not self._render_comparison_full_table(
            layer_a,
            layer_b,
            field_a,
            compare_field,
            return_field,
            matches=matches,
        ):
            self._set_compare_view("message")
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageComparar)
        except Exception:
            pass

    def select_matched_features(self):
        table = getattr(self, "compare_query_table", None)
        if table is None:
            QMessageBox.warning(self, "Seleção de feições", "Nenhuma tabela de comparação está disponível.")
            return

        layer_a = self.ui.compare_source_layer_combo.currentLayer()
        if layer_a is None:
            QMessageBox.warning(self, "Seleção de feições", "Selecione uma camada origem antes de continuar.")
            return

        df = table.dataframe()
        if df.empty or "__feature_id" not in df.columns:
            QMessageBox.warning(
                self,
                "Seleção de feições",
                "As transformações atuais não preservam o identificador das feições. Refaça a comparação ou mantenha as colunas protegidas.",
            )
            return

        ids = df["__feature_id"].dropna().unique().tolist()
        if not ids:
            QMessageBox.information(
                self,
                "Seleção de feições",
                "Nenhuma feição restante após as transformações.",
            )
            return

        try:
            ids = [int(v) for v in ids]
        except Exception:
            QMessageBox.warning(self, "Seleção de feições", "Não foi possível interpretar os identificadores das feições.")
            return

        layer_a.selectByIds(ids, QgsVectorLayer.SetSelection)
        try:
            self.iface.setActiveLayer(layer_a)
        except Exception:
            pass
        layer_a.triggerRepaint()

        QMessageBox.information(
            self,
            "Seleção de feições",
            f"{len(ids)} feições selecionadas na camada '{layer_a.name()}'.",
        )
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageComparar)
        except Exception:
            pass

    def create_comparison_temp_layer(self):
        table = getattr(self, "compare_query_table", None)
        if table is None:
            QMessageBox.warning(self, "Camada temporária", "Nenhuma tabela de comparação está disponível.")
            return

        df = table.dataframe()
        if df.empty:
            QMessageBox.information(self, "Camada temporária", "Nenhum dado disponível para criar a camada.")
            return

        source_layer, target_layer, geometry_layer = self._get_compare_context_layers()
        geometry_layer = geometry_layer or target_layer or source_layer

        base_name = ""
        if target_layer is not None:
            base_name = target_layer.name()
        elif source_layer is not None:
            base_name = source_layer.name()
        if not base_name:
            base_name = "resultado"
        temp_layer_name = self._unique_layer_name(f"Comparação {base_name}")

        temp_layer, error_message = self._create_layer_from_dataframe(
            df,
            temp_layer_name,
            with_geometry=True,
            geometry_layer=geometry_layer,
        )
        if temp_layer is None:
            QMessageBox.warning(
                self,
                "Camada temporária",
                error_message or "Não foi possível criar a camada temporária.",
            )
            return

        QgsProject.instance().addMapLayer(temp_layer)
        QMessageBox.information(
            self,
            "Camada temporária",
            f"Camada temporária '{temp_layer.name()}' criada com {temp_layer.featureCount()} feições.",
        )

    def materialize_comparison_result(self):
        table = getattr(self, "compare_query_table", None)
        if table is None:
            QMessageBox.warning(self, "Materializar resultado", "Nenhuma tabela de comparacao esta disponivel.")
            return

        df = table.dataframe()
        if df.empty:
            QMessageBox.information(
                self,
                "Materializar resultado",
                "Nenhum dado disponivel para materializar.",
            )
            return

        source_layer, target_layer, geometry_layer = self._get_compare_context_layers()
        geometry_layer = geometry_layer or target_layer or source_layer

        has_geometry_column = False
        if "__geometry_wkb" in df.columns:
            try:
                has_geometry_column = df["__geometry_wkb"].notna().any()
            except Exception:
                has_geometry_column = False

        can_recover_geometry = has_geometry_column
        if not can_recover_geometry and geometry_layer is not None and geometry_layer.isValid():
            can_recover_geometry = "__target_feature_id" in df.columns

        base_name = ""
        if target_layer is not None:
            base_name = target_layer.name()
        elif source_layer is not None:
            base_name = source_layer.name()
        if not base_name:
            base_name = "resultado"

        self._materialize_dataframe_dialog(
            df,
            base_name,
            can_use_geometry=can_recover_geometry,
            geometry_layer=geometry_layer,
            settings_key="PowerBISummarizer/compare/lastMaterializeDir",
            dialog_title="Materializar resultado",
            table_prefix="Tabela",
            memory_prefix="Comparacao",
            export_prefix="Comparacao",
        )


    def _get_compare_context_layers(self):
        context = getattr(self, "_last_compare_context", None)
        if not context:
            return None, None, None
        project = QgsProject.instance()

        def _layer_from_id(layer_id):
            if not layer_id:
                return None
            try:
                return project.mapLayer(layer_id)
            except Exception:
                return None

        source_layer = _layer_from_id(context.get("source_layer_id"))
        target_layer = _layer_from_id(context.get("target_layer_id"))
        geometry_layer = _layer_from_id(context.get("geometry_layer_id"))
        if geometry_layer is None:
            geometry_layer = target_layer or source_layer
        return source_layer, target_layer, geometry_layer

    def _build_geometry_lookup(self, layer: QgsVectorLayer, id_series: pd.Series):
        if layer is None or not layer.isValid():
            return {}
        if id_series is None or id_series.empty:
            return {}
        try:
            unique_ids = id_series.dropna().unique().tolist()
        except Exception:
            return {}
        candidate_ids = []
        for raw in unique_ids:
            if pd.isna(raw):
                continue
            try:
                candidate_ids.append(int(float(raw)))
            except Exception:
                try:
                    candidate_ids.append(int(str(raw)))
                except Exception:
                    continue
        if not candidate_ids:
            return {}
        lookup = {}
        request = QgsFeatureRequest()
        request.setFilterFids(candidate_ids)
        try:
            for feature in layer.getFeatures(request):
                try:
                    lookup[int(feature.id())] = feature.geometry().clone()
                except Exception:
                    pass
        except Exception:
            return {}
        return lookup

    def _geometry_from_lookup(self, fid_value, geometry_lookup):
        if fid_value is None or pd.isna(fid_value):
            return None
        try:
            fid = int(float(fid_value))
        except Exception:
            try:
                fid = int(str(fid_value))
            except Exception:
                return None
        geometry = geometry_lookup.get(fid)
        if geometry is None:
            return None
        try:
            return geometry.clone()
        except Exception:
            return QgsGeometry(geometry)

    def _create_layer_from_dataframe(
        self,
        df: pd.DataFrame,
        layer_name: str,
        with_geometry: bool,
        geometry_layer: Optional[QgsVectorLayer] = None,
    ):
        if df is None or df.empty:
            return None, "Nenhum dado disponível para materializar."

        display_columns = [c for c in df.columns if c not in PROTECTED_COLUMNS_DEFAULT]
        if not display_columns:
            return None, "Nenhuma coluna disponível após proteger os campos internos."

        qfields = QgsFields()
        field_mapping = {}
        existing_names = []
        for column in display_columns:
            try:
                variant = self._variant_type_for_series(df[column])
            except Exception:
                variant = QVariant.String
            safe_name = self._make_unique_field_name(existing_names, column)
            qfields.append(QgsField(safe_name, variant))
            field_mapping[column] = safe_name
            existing_names.append(safe_name)

        geometry_lookup = {}
        geometry_column_available = False
        geom_type = None
        crs_authid = ""

        if with_geometry:
            if "__geometry_wkb" in df.columns:
                try:
                    geometry_column_available = df["__geometry_wkb"].notna().any()
                except Exception:
                    geometry_column_available = False

            if geometry_layer is not None and geometry_layer.isValid():
                geom_type = QgsWkbTypes.displayString(geometry_layer.wkbType())
                try:
                    crs_authid = geometry_layer.crs().authid()
                except Exception:
                    crs_authid = ""

            if "__target_feature_id" in df.columns and geometry_layer is not None and geometry_layer.isValid():
                geometry_lookup = self._build_geometry_lookup(geometry_layer, df["__target_feature_id"])
                if geometry_lookup:
                    geometry_column_available = True
                    if geom_type is None:
                        geom_type = QgsWkbTypes.displayString(geometry_layer.wkbType())
                        try:
                            crs_authid = geometry_layer.crs().authid()
                        except Exception:
                            crs_authid = ""

            if geom_type is None and geometry_column_available:
                sample_hex = None
                try:
                    for raw in df["__geometry_wkb"]:
                        if isinstance(raw, str) and raw:
                            sample_hex = raw
                            break
                except Exception:
                    sample_hex = None
                if sample_hex:
                    try:
                        sample_geom = QgsGeometry.fromWkb(bytes.fromhex(sample_hex))
                        geom_type = QgsWkbTypes.displayString(sample_geom.wkbType())
                    except Exception:
                        geom_type = None

            if not geometry_column_available:
                return None, "Os dados atuais não possuem geometria disponível."
            if geom_type is None:
                return None, "Não foi possível determinar o tipo de geometria."

        uri = "None"
        if with_geometry:
            uri = geom_type if not crs_authid else f"{geom_type}?crs={crs_authid}"

        temp_layer = QgsVectorLayer(uri, layer_name, "memory")
        if not temp_layer or not temp_layer.isValid():
            return None, "Não foi possível criar a camada em memória."

        provider = temp_layer.dataProvider()
        if not provider.addAttributes(qfields):
            return None, "Falha ao definir os campos da camada."
        temp_layer.updateFields()

        features = []
        for _, row in df.iterrows():
            feature = QgsFeature(temp_layer.fields())
            if with_geometry:
                geometry = None
                geom_hex = row.get("__geometry_wkb") if "__geometry_wkb" in df.columns else None
                if isinstance(geom_hex, str) and geom_hex:
                    try:
                        geometry = QgsGeometry.fromWkb(bytes.fromhex(geom_hex))
                    except Exception:
                        geometry = None
                if geometry is None and geometry_lookup:
                    geometry = self._geometry_from_lookup(row.get("__target_feature_id"), geometry_lookup)
                if geometry is None:
                    continue
                try:
                    feature.setGeometry(geometry)
                except Exception:
                    continue
            attrs = []
            for column in display_columns:
                attrs.append(self._python_value(row[column]))
            feature.setAttributes(attrs)
            features.append(feature)

        if not features:
            return None, "Nenhuma feição gerada a partir dos dados filtrados."

        if not provider.addFeatures(features):
            return None, "Falha ao adicionar as feições na camada."

        temp_layer.updateExtents()
        return temp_layer, None

    def _export_layer_to_gpkg(self, layer: QgsVectorLayer, path: str, layer_name: str):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV2(layer, path, context, options)
        error = result[0] if isinstance(result, (list, tuple)) else result
        message = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else ""
        if error != QgsVectorFileWriter.NoError:
            return False, message
        return True, ""

    def _variant_type_for_series(self, series: pd.Series) -> QVariant.Type:
        try:
            if ptypes.is_bool_dtype(series):
                return QVariant.Bool
            if ptypes.is_integer_dtype(series):
                return QVariant.LongLong
            if ptypes.is_float_dtype(series):
                return QVariant.Double
            if ptypes.is_datetime64_any_dtype(series):
                return QVariant.DateTime
        except Exception:
            pass
        return QVariant.String

    def _python_value(self, value):
        if pd.isna(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, np.bool_):
            return bool(value)
        return value

    def _format_comparison_values(self, values):
        formatted = []
        for value in values:
            if not self._is_meaningful_value(value):
                formatted.append("(vazio)")
            else:
                formatted.append(str(value))
        return ", ".join(formatted)

    def _sanitize_field_name(self, raw_name: str) -> str:
        if not raw_name:
            raw_name = "resultado"
        sanitized = re.sub(r"\W+", "_", raw_name).strip("_")
        if not sanitized:
            sanitized = "resultado"
        if sanitized[0].isdigit():
            sanitized = f"f_{sanitized}"
        return sanitized[:30]

    def _make_unique_field_name(self, existing_names, base_name: str) -> str:
        sanitized = self._sanitize_field_name(base_name)
        candidate = sanitized
        counter = 1
        existing = set(existing_names)
        while candidate in existing:
            counter += 1
            candidate = f"{sanitized}_{counter}"
        return candidate

    def _unique_layer_name(self, base_name: str) -> str:
        base = base_name.strip() if base_name else "Camada_Comparacao"
        if not base:
            base = "Camada_Comparacao"
        existing_names = {
            layer.name() for layer in QgsProject.instance().mapLayers().values()
        }
        candidate = base
        counter = 1
        while candidate in existing_names:
            counter += 1
            candidate = f"{base} ({counter})"
        return candidate

    def _is_meaningful_value(self, value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return False
            return stripped.lower() not in {"null", "none"}
        return True

    def _filter_empty_matches(self, matches):
        filtered = {}
        for key, values in matches.items():
            meaningful_values = [value for value in values if self._is_meaningful_value(value)]
            if meaningful_values:
                filtered[key] = meaningful_values
        return filtered

    def on_layer_changed(self):
        layer = self.ui.layer_combo.currentLayer()
        if layer and isinstance(layer, QgsVectorLayer):
            self._active_numeric_field = self._select_default_numeric_field(layer)
        else:
            self._active_numeric_field = None

        if self._active_numeric_field is None:
            self.current_summary_data = None
            self.show_summary_prompt()
            return

        if self.ui.auto_update_check.isChecked():
            QTimer.singleShot(300, self.generate_summary)

    def _select_default_numeric_field(self, layer: QgsVectorLayer) -> Optional[str]:
        if not layer:
            return None
        try:
            for field in layer.fields():
                try:
                    if field.isNumeric():
                        return field.name()
                except Exception:
                    pass
                try:
                    if QVariant.Double == field.type() or QVariant.Int == field.type():
                        return field.name()
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def generate_summary(self):
        layer = self.ui.layer_combo.currentLayer()
        if not layer or not isinstance(layer, QgsVectorLayer):
            return
        field_name = self._active_numeric_field or self._select_default_numeric_field(layer)
        if not field_name:
            QMessageBox.warning(
                self,
                "Resumo",
                "Nenhum campo numérico foi encontrado na camada selecionada.",
            )
            self.show_summary_prompt()
            return
        self._active_numeric_field = field_name
        group_field = None
        filter_field = None
        filter_value = None

        # Ensure pivot view becomes visible when gererating summaries
        self._set_results_view("pivot")
        if getattr(self, "summary_message_widget", None) is not None:
            self.summary_message_widget.clear()

        try:
            summary_data = self.calculate_advanced_summary(
            layer, field_name, group_field, filter_field, filter_value
        )
            self.current_summary_data = summary_data
            self.display_advanced_summary(summary_data)
            self.update_charts_preview(summary_data)
            self.prepare_export_tab_defaults(summary_data)
        except Exception as exc:
            QMessageBox.warning(self, "Erro", f"Erro ao gerar resumo: {exc}")

    def calculate_advanced_summary(
        self,
        layer,
        field_name,
        group_field=None,
        filter_field=None,
        filter_value=None,
    ):
        field_index = layer.fields().indexFromName(field_name)
        group_index = layer.fields().indexFromName(group_field) if group_field else -1
        filter_index = layer.fields().indexFromName(filter_field) if filter_field else -1

        request = QgsFeatureRequest()
        filter_description = "Nenhum"
        if filter_field and filter_value:
            filter_description = f'{filter_field} contém "{filter_value}"'
            expression = f'"{filter_field}" ILIKE \'%{filter_value}%\''
            request.setFilterExpression(expression)

        summary = {
            "basic_stats": {
                "total": 0.0,
                "count": 0,
                "average": 0.0,
                "min": float("inf"),
                "max": float("-inf"),
                "median": 0.0,
                "std_dev": 0.0,
            },
            "grouped_data": {},
            "percentiles": {},
            "metadata": {
                "layer_name": layer.name(),
                "field_name": field_name,
                "timestamp": datetime.now().isoformat(),
                "total_features": layer.featureCount(),
            },
            "filter_description": filter_description,
        }

        if field_index < 0:
            raise ValueError(f"Campo numérico '{field_name}' não encontrado na camada.")

        field_names = [f.name() for f in layer.fields()]
        raw_rows = []
        values = []
        grouped_values = {}

        for feature in layer.getFeatures(request):
            attrs = feature.attributes()
            raw_rows.append(
                {field_names[idx]: attrs[idx] for idx in range(len(field_names))}
            )

            value = attrs[field_index]
            if value in (None, ""):
                continue

            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue

            values.append(numeric_value)
            summary["basic_stats"]["total"] += numeric_value
            summary["basic_stats"]["min"] = min(
                summary["basic_stats"]["min"], numeric_value
            )
            summary["basic_stats"]["max"] = max(
                summary["basic_stats"]["max"], numeric_value
            )

            if group_index != -1:
                group_value = feature[group_index]
                grouped_values.setdefault(group_value, []).append(numeric_value)

        if values:
            n = len(values)
            sorted_vals = sorted(values)

            summary["basic_stats"]["count"] = n
            summary["basic_stats"]["average"] = summary["basic_stats"]["total"] / n

            if n % 2 == 0:
                summary["basic_stats"]["median"] = (
                    sorted_vals[n // 2 - 1] + sorted_vals[n // 2]
                ) / 2
            else:
                summary["basic_stats"]["median"] = sorted_vals[n // 2]

            mean = summary["basic_stats"]["average"]
            variance = sum((x - mean) ** 2 for x in values) / n
            summary["basic_stats"]["std_dev"] = variance ** 0.5

            summary["percentiles"] = {
                "p25": np.percentile(sorted_vals, 25),
                "p50": np.percentile(sorted_vals, 50),
                "p75": np.percentile(sorted_vals, 75),
                "p90": np.percentile(sorted_vals, 90),
                "p95": np.percentile(sorted_vals, 95),
            }
        else:
            summary["basic_stats"]["min"] = 0.0
            summary["basic_stats"]["max"] = 0.0

        for group, numbers in grouped_values.items():
            if not numbers:
                continue

            group_sum = sum(numbers)
            summary["grouped_data"][str(group)] = {
                "count": len(numbers),
                "sum": group_sum,
                "average": group_sum / len(numbers),
                "min": min(numbers),
                "max": max(numbers),
                "percentage": (
                    (group_sum / summary["basic_stats"]["total"]) * 100
                    if summary["basic_stats"]["total"]
                    else 0.0
                ),
            }

        summary["raw_data"] = {"columns": field_names, "rows": raw_rows}

        return summary

    def display_advanced_summary(self, summary_data):
        self._set_integration_footer_visible(False)
        pivot = getattr(self, "pivot_widget", None)
        if pivot is not None:
            try:
                pivot.set_summary_data(summary_data)
                self._set_results_view("pivot")
                return
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Tabela dinamica",
                    f"Nao foi possivel atualizar a tabela dinamica: {exc}",
                )
                self._set_results_view("message")
                self.show_results_message(
                    "<p style='margin:8px 0;'>Nao foi possivel exibir a tabela dinamica para estes dados.</p>"
                )
                return

        self._set_results_view("message")
        self.show_results_message(
            "<p style='margin:8px 0;'>Nao foi possivel exibir a tabela dinamica para estes dados.</p>"
        )
        return

    def _escape_html(self, text: str) -> str:
        if text is None:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def update_charts_preview(self, summary_data):
        if not hasattr(self.ui, "chart_preview_text"):
            return
        grouped = summary_data.get("grouped_data") or {}
        layer_name = summary_data.get("metadata", {}).get("layer_name", "-")
        field_name = summary_data.get("metadata", {}).get("field_name", "-")
        stats = summary_data.get("basic_stats", {})

        timestamp_str = summary_data.get("metadata", {}).get("timestamp")
        try:
            human_ts = datetime.fromisoformat(timestamp_str).strftime("%d/%m/%Y %H:%M")
        except Exception:
            human_ts = datetime.now().strftime("%d/%m/%Y %H:%M")

        total_label = f"{stats.get('total', 0):,.2f}"

        if not grouped:
            empty_html = f"""
            <div class="preview-card empty">
                <div class="preview-header">
                    <h2>Distribuição percentual dos grupos – "{self._escape_html(field_name)}" em {self._escape_html(layer_name)}</h2>
                    <div class="meta-grid">
                        <div class="meta-item">
                            <span class="meta-label">Camada</span>
                            <span class="meta-value">{self._escape_html(layer_name)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Campo numérico</span>
                            <span class="meta-value">{self._escape_html(field_name)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Total geral</span>
                            <span class="meta-value">{total_label}</span>
                        </div>
                    </div>
                </div>
                <div class="empty-body">
                    Nenhum agrupamento disponível para exibir.
                </div>
                <div class="preview-footer">Gerado em: {human_ts}</div>
            </div>
            """
            self.ui.chart_preview_text.setHtml(
                apply_result_style(empty_html) + self._chart_preview_style_block()
            )
            return

        sorted_groups = sorted(
            grouped.items(), key=lambda item: item[1].get("percentage", 0), reverse=True
        )

        labels = [
            "Sem valor" if key in (None, "") else str(key) for key, _ in sorted_groups
        ]
        values = [max(data.get("percentage", 0.0), 0.0) for _, data in sorted_groups]

        chart_html = ""
        if values and max(values) > 0:
            figure_height = max(3.0, len(values) * 0.45)
            fig, ax = plt.subplots(figsize=(6.5, figure_height))
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")

            bars = ax.barh(
                labels,
                values,
                color="#153C8A",
                edgecolor="#0f2558",
                alpha=0.95,
            )
            ax.invert_yaxis()
            ax.set_xlabel("% do total", color="#1d2a4b")
            ax.set_xlim(0, max(values) * 1.1)
            ax.tick_params(axis="x", colors="#44516b")
            ax.tick_params(axis="y", colors="#1d2a4b")
            ax.grid(axis="x", linestyle="--", linewidth=0.5, alpha=0.3)

            for bar, perc in zip(bars, values):
                ax.text(
                    perc + max(values) * 0.02,
                    bar.get_y() + bar.get_height() / 2,
                    f"{perc:.1f}%",
                    va="center",
                    ha="left",
                    fontsize=9,
                    color="#1d2a4b",
                )

            fig.tight_layout()
            buffer = BytesIO()
            fig.savefig(
                buffer,
                format="png",
                dpi=130,
                bbox_inches="tight",
                transparent=True,
            )
            plt.close(fig)
            buffer.seek(0)
            encoded = base64.b64encode(buffer.read()).decode("utf-8")
            chart_html = f'<img class="preview-chart" src="data:image/png;base64,{encoded}" alt="Distribuição percentual dos grupos">'

        html = f"""
        <div class="preview-card">
            <div class="preview-header">
                <h2>Distribuição percentual dos grupos – "{self._escape_html(field_name)}" em {self._escape_html(layer_name)}</h2>
                <div class="meta-grid">
                    <div class="meta-item">
                        <span class="meta-label">Camada</span>
                        <span class="meta-value">{self._escape_html(layer_name)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Campo numérico</span>
                        <span class="meta-value">{self._escape_html(field_name)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Total geral</span>
                        <span class="meta-value">{total_label}</span>
                    </div>
                </div>
            </div>
            <div class="groups-wrapper">
                {chart_html or '<div class="empty-body">Nenhum agrupamento disponível para exibir.</div>'}
            </div>
            <div class="preview-footer">Gerado em: {human_ts}</div>
        </div>
        """

        self.ui.chart_preview_text.setHtml(
            apply_result_style(html) + self._chart_preview_style_block()
        )

    def _chart_preview_style_block(self) -> str:
        return """
        <style>
            .preview-card {
                background: #f5f6fb;
                border: 1px solid #e3e7f1;
                border-radius: 0px;
                padding: 18px 22px;
                display: flex;
                flex-direction: column;
                gap: 18px;
            }
            .preview-card.empty {
                gap: 24px;
            }
            .preview-header h2 {
                margin: 0 0 12px 0;
                font-size: 18px;
                color: #1d2a4b;
            }
            .meta-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 10px;
            }
            .meta-item {
                background: #ffffff;
                border-radius: 0px;
                border: 1px solid #e6eaf4;
                padding: 10px 12px;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .meta-label {
                font-size: 10pt;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .meta-value {
                font-size: 12pt;
                font-weight: 600;
                color: #1d2a4b;
            }
            .groups-wrapper {
                display: flex;
                justify-content: center;
                padding: 4px;
            }
            .preview-chart {
                max-width: 100%;
                background: rgba(255, 255, 255, 0.7);
                border-radius: 0px;
                padding: 6px;
                border: 1px solid #e6eaf4;
            }
            .preview-footer {
                margin-top: 8px;
                font-size: 10pt;
                color: #7b8794;
                text-align: right;
            }
            .empty-body {
                background: #ffffff;
                border-radius: 0px;
                border: 1px dashed #d2d8e6;
                padding: 18px;
                text-align: center;
                color: #7b8794;
                font-size: 11pt;
            }
        </style>
        """

    def open_export_tab(self):
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageResultados)
        except Exception:
            pass
        if self.current_summary_data:
            self.prepare_export_tab_defaults(self.current_summary_data)
        else:
            QMessageBox.information(
                self, "Informação", "Gere um resumo antes de exportar."
            )

    def _current_export_format(self):
        text = self.ui.export_format_combo.currentText()
        return self.export_formats.get(text, next(iter(self.export_formats.values())))

    def _strip_existing_timestamp(self, base_path: str) -> str:
        if self._timestamp_pattern.search(base_path):
            return self._timestamp_pattern.sub("", base_path)
        return base_path

    def _normalize_filename_component(self, value: str) -> str:
        if not value:
            return ""
        normalized = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip()
        )
        return normalized.strip("_")

    def _build_default_export_basename(self, summary_data):
        metadata = summary_data.get("metadata", {})
        layer_part = self._normalize_filename_component(metadata.get("layer_name", ""))
        field_part = self._normalize_filename_component(metadata.get("field_name", ""))
        parts = [part for part in (layer_part, field_part) if part]
        return "_".join(parts) if parts else "resumo_powerbi"

    def _set_export_path(self, path: str):
        base, ext = os.path.splitext(path)
        base = self._strip_existing_timestamp(base)
        sanitized = base + ext
        self._export_base_path = base
        self._updating_export_path = True
        self.ui.export_path_edit.setText(sanitized)
        self._updating_export_path = False

    def prepare_export_tab_defaults(self, summary_data):
        if not summary_data:
            return
        format_info = self._current_export_format()
        base_name = self._build_default_export_basename(summary_data)
        suggested_dir = self.export_manager.export_dir
        suggested_path = os.path.join(
            suggested_dir, base_name + format_info["extension"]
        )
        self._set_export_path(suggested_path)

    def on_export_format_changed(self):
        format_info = self._current_export_format()
        if self._export_base_path:
            self._set_export_path(self._export_base_path + format_info["extension"])
        elif self.current_summary_data:
            self.prepare_export_tab_defaults(self.current_summary_data)

    def on_export_path_edited(self):
        if self._updating_export_path:
            return
        path = self.ui.export_path_edit.text().strip()
        if not path:
            self._export_base_path = ""
            return

        base, _ = os.path.splitext(path)
        base = self._strip_existing_timestamp(base)
        format_info = self._current_export_format()
        self._set_export_path(base + format_info["extension"])

    def _prompt_layer_selection(self, layers):
        names = [layer.name() or "Camada sem nome" for layer in layers]
        dialog = SlimLayerSelectionDialog("Selecionar camadas", names, parent=self)
        dialog.set_focus_on_search()
        if dialog.exec_() != QDialog.Accepted:
            return None
        indices = dialog.selected_indices()
        return [layers[idx] for idx in indices]

    def export_all_vector_layers(self):
        project = QgsProject.instance()
        if project is None:
            QMessageBox.warning(
                self, "Aviso", "Projeto QGIS não encontrado. Tente novamente."
            )
            return

        vector_layers = [
            layer
            for layer in project.mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]

        if not vector_layers:
            QMessageBox.information(
                self,
                "Informação",
                "Nenhuma camada vetorial carregada para exportar.",
            )
            return

        selected_layers = self._prompt_layer_selection(vector_layers)
        if selected_layers is None:
            return
        if not selected_layers:
            QMessageBox.information(
                self,
                "Informação",
                "Nenhuma camada selecionada para exportar.",
            )
            return

        target_dir = self._prompt_layers_export_directory()
        if not target_dir:
            return

        exported_count = 0
        errors = []
        style_warnings = []
        transform_context = project.transformContext()

        for layer in selected_layers:
            layer_name = layer.name() or "camada"
            safe_name = self._normalize_filename_component(layer_name) or "camada"
            destination_path = os.path.join(target_dir, f"{safe_name}.gpkg")
            final_path = destination_path
            suffix = 1
            while os.path.exists(final_path):
                final_path = os.path.join(target_dir, f"{safe_name}_{suffix}.gpkg")
                suffix += 1

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.fileEncoding = layer.dataProvider().encoding()

            layer_style = QgsMapLayerStyle()
            try:
                style_captured = layer_style.readFromLayer(layer)
            except Exception:
                style_captured = False

            write_output = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                final_path,
                transform_context,
                options,
            )

            result = write_output
            error_message = ""
            status = write_output
            if isinstance(write_output, tuple):
                if write_output:
                    status = write_output[0]
                if len(write_output) > 1:
                    if isinstance(write_output[1], str):
                        error_message = write_output[1]
                    elif write_output[1]:
                        error_message = str(write_output[1])
                if not error_message and len(write_output) > 2:
                    if isinstance(write_output[2], str):
                        error_message = write_output[2]
                    elif write_output[2]:
                        error_message = str(write_output[2])
            elif hasattr(write_output, "status"):
                status = write_output.status()
                try:
                    error_message = getattr(write_output, "errorMessage", lambda: "")()
                except Exception:
                    error_message = ""
            elif hasattr(write_output, "errorMessage"):
                try:
                    error_message = write_output.errorMessage()
                except Exception:
                    error_message = ""

            is_success = False
            if status == QgsVectorFileWriter.NoError:
                is_success = True
            elif hasattr(status, "value"):
                try:
                    is_success = status.value == QgsVectorFileWriter.NoError
                except Exception:
                    is_success = False
            else:
                try:
                    is_success = int(status) == int(QgsVectorFileWriter.NoError)
                except Exception:
                    is_success = False

            if is_success:
                exported_count += 1
                if style_captured:
                    try:
                        gpkg_uri = f"{final_path}|layername={layer_name}"
                        exported_layer = QgsVectorLayer(gpkg_uri, layer_name, "ogr")
                        if not exported_layer.isValid():
                            exported_layer = QgsVectorLayer(final_path, layer_name, "ogr")
                        if exported_layer.isValid():
                            if not layer_style.writeToLayer(exported_layer):
                                style_warnings.append(
                                    (layer_name, "Não foi possível aplicar o estilo.")
                                )
                            else:
                                try:
                                    save_result = exported_layer.saveStyleToDatabase(
                                        layer_name,
                                        "Estilo exportado automaticamente",
                                        True,
                                    )
                                    saved_ok = False
                                    save_error = ""
                                    if isinstance(save_result, tuple):
                                        if save_result:
                                            saved_ok = bool(save_result[0])
                                            if len(save_result) > 1:
                                                save_error = str(save_result[1])
                                    else:
                                        saved_ok = bool(save_result)
                                    if not saved_ok:
                                        message = (
                                            "Estilo aplicado, mas não pôde ser salvo no GeoPackage."
                                        )
                                        if save_error:
                                            message += f" Detalhes: {save_error}"
                                        style_warnings.append(
                                            (
                                                layer_name,
                                                message,
                                            )
                                        )
                                except Exception as exc:
                                    style_warnings.append(
                                        (
                                            layer_name,
                                            f"Falha ao salvar estilo no GeoPackage: {exc}",
                                        )
                                    )
                        else:
                            style_warnings.append(
                                (
                                    layer_name,
                                    "Camada exportada não pôde ser reaberta para aplicar o estilo.",
                                )
                            )
                        exported_layer = None
                    except Exception as exc:
                        style_warnings.append(
                            (layer_name, f"Falha ao transferir estilo: {exc}")
                        )
            else:
                errors.append((layer_name, error_message or "Erro desconhecido"))
                try:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                except Exception:
                    pass

        summary_lines = [
            f"{exported_count} de {len(selected_layers)} camada(s) exportada(s) para GeoPackage em:",
            target_dir,
        ]

        detail_lines = []
        if errors:
            detail_lines.append("Falhas de exportação:")
            detail_lines.extend(f"- {name}: {msg}" for name, msg in errors)
        if style_warnings:
            detail_lines.append("Avisos de estilo:")
            detail_lines.extend(f"- {name}: {msg}" for name, msg in style_warnings)

        if not errors and not style_warnings:
            QMessageBox.information(
                self,
                "Exportação concluída",
                "\n".join(summary_lines),
            )
        else:
            QMessageBox.warning(
                self,
                "Exportação concluída com avisos",
                "\n".join(summary_lines + [""] + detail_lines),
            )

    def open_cloud_upload_tab(self):
        """Open the Cloud dialog focusing the upload tab (admin only)."""
        try:
            from .cloud_dialogs import open_cloud_dialog
            from .cloud_session import cloud_session

            if not cloud_session.is_authenticated() or not cloud_session.is_admin():
                QMessageBox.information(
                    self,
                    "PowerBI Cloud",
                    "Somente administradores conectados podem enviar camadas para o Cloud.",
                )
                return
            open_cloud_dialog(self, initial_tab="upload")
        except Exception:
            # Safe fallback: ignore failures to open the dialog
            pass

    def _prompt_layers_export_directory(self):
        settings = QSettings()
        last_dir = settings.value("PowerBISummarizer/export/gpkgDir", "")
        fallback_dir = self.export_manager.export_dir
        initial_dir = last_dir if last_dir and os.path.isdir(last_dir) else fallback_dir

        directory = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de destino",
            initial_dir,
        )

        if not directory:
            return None

        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Exportar camadas",
                f"Nao foi possivel criar a pasta selecionada:\n{directory}\nDetalhes: {exc}",
            )
            return None

        settings.setValue("PowerBISummarizer/export/gpkgDir", directory)
        return directory

    def choose_export_path(self):
        format_info = self._current_export_format()
        initial_path = self.ui.export_path_edit.text().strip()
        if not initial_path:
            initial_path = os.path.join(self.export_manager.export_dir, "")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Selecionar arquivo",
            initial_path,
            format_info["filter"],
        )

        if file_path:
            base, _ = os.path.splitext(file_path)
            base = self._strip_existing_timestamp(base)
            self._set_export_path(base + format_info["extension"])
            return True
        return False

    def export_results(self):
        if not self.current_summary_data:
            QMessageBox.warning(self, "Aviso", "Gere um resumo primeiro!")
            self.open_export_tab()
            return

        format_info = self._current_export_format()
        target_path = self.ui.export_path_edit.text().strip()

        if not target_path:
            if not self.choose_export_path():
                QMessageBox.warning(
                    self, "Aviso", "Selecione o arquivo de destino para exportar."
                )
                return
            target_path = self.ui.export_path_edit.text().strip()

        base, _ = os.path.splitext(target_path)
        base = self._strip_existing_timestamp(base)

        if self.ui.export_include_timestamp_check.isChecked():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"{base}_{stamp}{format_info['extension']}"
        else:
            export_path = base + format_info["extension"]

        try:
            self.export_manager.export_data(
                self.current_summary_data, export_path, format_info["filter"]
            )
            QMessageBox.information(
                self, "Sucesso", f"Dados exportados para:\n{export_path}"
            )
            self._set_export_path(base + format_info["extension"])
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Erro na exportação: {exc}")

    def _materialize_power_query_result(self, df: pd.DataFrame, geometry_available: bool):
        if df is None or df.empty:
            QMessageBox.information(
                self,
                "Criar camada",
                "Nenhum dado disponivel para materializar.",
            )
            return

        source_layer, target_layer, geometry_layer = self._get_compare_context_layers()
        geometry_layer = geometry_layer or target_layer or source_layer

        can_recover_geometry = bool(geometry_available)
        if not can_recover_geometry and geometry_layer is not None and geometry_layer.isValid():
            can_recover_geometry = "__target_feature_id" in df.columns

        base_name = ""
        if target_layer is not None:
            base_name = target_layer.name()
        elif source_layer is not None:
            base_name = source_layer.name()
        if not base_name:
            base_name = "PowerQuery"

        self._materialize_dataframe_dialog(
            df,
            base_name,
            can_use_geometry=can_recover_geometry,
            geometry_layer=geometry_layer,
            settings_key="PowerBISummarizer/powerquery/lastMaterializeDir",
            dialog_title="Criar camada",
            table_prefix="Tabela",
            memory_prefix="PowerQuery",
            export_prefix="PowerQuery",
        )

    def _materialize_dataframe_dialog(
        self,
        df: pd.DataFrame,
        base_name: str,
        can_use_geometry: bool,
        geometry_layer: Optional[QgsVectorLayer],
        settings_key: str,
        dialog_title: str,
        table_prefix: str,
        memory_prefix: str,
        export_prefix: str,
    ):
        if df is None or df.empty:
            QMessageBox.information(self, dialog_title, "Nenhum dado disponivel para materializar.")
            return

        base_name = (base_name or "resultado").strip()
        if not base_name:
            base_name = "resultado"

        options = ["Tabela (somente atributos)"]
        gpkg_label = "Salvar como GPKG"
        if can_use_geometry:
            options.append("Camada temporaria (memoria)")
            options.append(gpkg_label)
        else:
            gpkg_label = "Salvar como GPKG (tabela)"
            options.append(gpkg_label)

        choice, ok = slim_get_item(
            self,
            dialog_title,
            "Escolha como deseja materializar o resultado atual:",
            options,
            current=0,
        )
        if not ok or not choice:
            return

        if choice.startswith("Tabela"):
            table_name = self._unique_layer_name(f"{table_prefix} {base_name}".strip())
            layer, error_message = self._create_layer_from_dataframe(
                df,
                table_name,
                with_geometry=False,
            )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Nao foi possivel gerar a tabela.",
                )
                return
            QgsProject.instance().addMapLayer(layer)
            QMessageBox.information(
                self,
                dialog_title,
                f"Tabela '{layer.name()}' criada com {layer.featureCount()} registros.",
            )
            return

        if choice.startswith("Camada temporaria"):
            layer_name = self._unique_layer_name(f"{memory_prefix} {base_name}".strip())
            layer, error_message = self._create_layer_from_dataframe(
                df,
                layer_name,
                with_geometry=True,
                geometry_layer=geometry_layer,
            )
            fallback_note = ""
            if (
                layer is None
                and can_use_geometry
                and error_message
                and "Nenhuma feicao" in error_message
            ):
                layer, error_message = self._create_layer_from_dataframe(
                    df,
                    layer_name,
                    with_geometry=False,
                    geometry_layer=None,
                )
                if layer is not None:
                    fallback_note = (
                        "\n\nAs transformacoes removeram as geometrias. "
                        "Foi criada uma tabela temporaria sem geometria."
                    )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Nao foi possivel criar a camada temporaria.",
                )
                return
            QgsProject.instance().addMapLayer(layer)
            QMessageBox.information(
                self,
                dialog_title,
                f"Camada '{layer.name()}' criada com {layer.featureCount()} feicoes.{fallback_note}",
            )
            return

        if choice.startswith("Salvar como GPKG"):
            suggested_name = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", base_name).strip("_") or "resultado"
            last_dir = ""
            if settings_key:
                try:
                    last_dir = QSettings().value(settings_key, "", type=str)
                except Exception:
                    last_dir = ""
            default_path = (
                os.path.join(last_dir, f"{suggested_name}.gpkg") if last_dir else f"{suggested_name}.gpkg"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar GeoPackage",
                default_path,
                "GeoPackage (*.gpkg)",
            )
            if not path:
                return
            directory = os.path.dirname(path)
            if settings_key and directory:
                QSettings().setValue(settings_key, directory)
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"

            with_geometry = can_use_geometry and not choice.endswith("(tabela)")
            export_layer_name = f"{export_prefix} {base_name}".strip() or base_name
            layer, error_message = self._create_layer_from_dataframe(
                df,
                export_layer_name,
                with_geometry=with_geometry,
                geometry_layer=geometry_layer,
            )
            fallback_note = ""
            if (
                layer is None
                and with_geometry
                and error_message
                and "Nenhuma feicao" in error_message
            ):
                layer, error_message = self._create_layer_from_dataframe(
                    df,
                    export_layer_name,
                    with_geometry=False,
                    geometry_layer=None,
                )
                if layer is not None:
                    fallback_note = (
                        "\n\nAs transformacoes removeram as geometrias. "
                        "O arquivo foi salvo apenas com atributos."
                    )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Nao foi possivel preparar os dados para exportacao.",
                )
                return

            success, writer_message = self._export_layer_to_gpkg(layer, path, export_layer_name)
            if not success:
                QMessageBox.critical(
                    self,
                    dialog_title,
                    writer_message or "Falha ao exportar o GeoPackage.",
                )
                return

            try:
                uri = f"{path}|layername={export_layer_name}"
                exported_layer = QgsVectorLayer(uri, export_layer_name, "ogr")
                if exported_layer and exported_layer.isValid():
                    QgsProject.instance().addMapLayer(exported_layer)
            except Exception:
                pass

            final_message = f"Arquivo GeoPackage salvo em:\n{path}{fallback_note}"
            QMessageBox.information(
                self,
                dialog_title,
                final_message,
            )

    def show_dashboard(self):
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageResultados)
        except Exception:
            pass
        pivot_widget = getattr(self, "pivot_widget", None)
        if pivot_widget is None:
            QMessageBox.warning(
                self,
                "Dashboard",
                "A tabela dinâmica ainda não está disponível para este resumo.",
            )
            return

        try:
            pivot_df = pivot_widget.get_visible_pivot_dataframe()
            metadata = pivot_widget.get_summary_metadata()
            config = pivot_widget.get_current_configuration()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Dashboard",
                f"Não foi possível obter os dados filtrados da tabela dinâmica: {exc}",
            )
            return

        self.dashboard_widget.set_pivot_data(pivot_df, metadata, config)
        self.dashboard_widget.show()
        self.dashboard_widget.raise_()

    def show_about_dialog(self):
        dialog = SlimDialogBase(self, geometry_key="PowerBISummarizer/dialogs/about")
        dialog.setWindowTitle("Sobre")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Power BI Summarizer", dialog)
        title.setProperty("sublabel", True)
        layout.addWidget(title)

        body = QLabel(
            "Resumo e exporta??uo de camadas do QGIS com visual inspirado no Power BI.",
            dialog,
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setObjectName("SlimPrimaryButton")
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec_()



