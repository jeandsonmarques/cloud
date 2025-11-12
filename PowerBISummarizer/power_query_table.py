
import math
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
from pandas.api import types as ptypes
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    Qt,
    QVariant,
)
from qgis.PyQt.QtGui import QClipboard, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QAction,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .slim_dialogs import (
    SlimChecklistDialog,
    SlimLayerSelectionDialog,
    slim_get_int,
    slim_get_item,
    slim_get_text,
)

PROTECTED_COLUMNS_DEFAULT: Set[str] = {"__feature_id", "__geometry_wkb", "__target_feature_id"}
NULL_SENTINEL = object()


def _display_text(value) -> str:
    if value is NULL_SENTINEL:
        return "(vazio)"
    if pd.isna(value):
        return "(vazio)"
    return str(value)


class PowerQueryModel(QAbstractTableModel):
    def __init__(self, df: Optional[pd.DataFrame] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._df: pd.DataFrame = df.copy() if df is not None else pd.DataFrame()
        self._visible_columns: List[str] = list(self._df.columns)
        self._sort_column: int = -1
        self._sort_order: Qt.SortOrder = Qt.AscendingOrder

    @property
    def dataframe(self) -> pd.DataFrame:
        return self._df

    @property
    def visible_columns(self) -> List[str]:
        return self._visible_columns

    def set_dataframe(self, df: pd.DataFrame, visible_columns: Optional[Sequence[str]] = None):
        self.beginResetModel()
        self._df = df.copy()
        if visible_columns is None:
            self._visible_columns = list(self._df.columns)
        else:
            self._visible_columns = [col for col in visible_columns if col in self._df.columns]
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._df.index)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._visible_columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return QVariant()
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return QVariant()
        column = self._visible_columns[index.column()]
        try:
            value = self._df.iloc[index.row()][column]
        except Exception:
            return ""
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            if math.isfinite(value):
                return f"{value:,.4f}".rstrip("0").rstrip(".")
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return super().headerData(section, orientation, role)
        if 0 <= section < len(self._visible_columns):
            label = self._visible_columns[section]
            if section == self._sort_column:
                arrow = " v" if self._sort_order == Qt.AscendingOrder else " ^"
                return f"{label}{arrow}"
            return label
        return QVariant()

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        if not (0 <= column < len(self._visible_columns)):
            return
        col_name = self._visible_columns[column]
        if col_name not in self._df.columns:
            return
        self.layoutAboutToBeChanged.emit()
        try:
            ascending = order == Qt.AscendingOrder
            self._df = self._df.sort_values(by=col_name, ascending=ascending, kind="mergesort")
        except Exception:
            converted = self._df[col_name].astype(str)
            self._df = self._df.assign(_sort_key_=converted)
            self._df = self._df.sort_values(by="_sort_key_", ascending=order == Qt.AscendingOrder, kind="mergesort")
            self._df = self._df.drop(columns="_sort_key_")
        self._df.reset_index(drop=True, inplace=True)
        self._sort_column = column
        self._sort_order = order
        self.layoutChanged.emit()


class ValueFilterDialog(SlimChecklistDialog):
    """Compact checklist dialog with slim styling for value-based filters."""

    def __init__(self, column: str, values: Sequence, parent: QWidget):
        self._payloads: List = []
        labels: List[str] = []
        seen_keys: Set[Tuple[str, str]] = set()

        for raw in values:
            if pd.isna(raw):
                key = ("null", "null")
                payload = NULL_SENTINEL
                display = "(vazio)"
            else:
                display = str(raw)
                payload = raw
                key = (type(raw).__name__, display)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            labels.append(display)
            self._payloads.append(payload)

        if not labels:
            labels.append("(sem valores disponiveis)")
            self._payloads.append(NULL_SENTINEL)

        super().__init__(
            title=f"Filtrar por valores - {column}",
            items=labels,
            parent=parent,
            checked_items=list(labels),
            geometry_key="PowerBISummarizer/dialogs/valueFilter",
            header_text=f"Selecione os valores que deseja manter em '{column}'",
            search_placeholder="Buscar valores...",
            select_all_label="Selecionar todas",
            clear_all_label="Desmarcar todas",
            empty_selection_message="Selecione pelo menos um valor antes de continuar.",
        )
        self.set_focus_on_search()

    def selected_values(self) -> List:
        indices = super().selected_indices()
        return [self._payloads[i] for i in indices if 0 <= i < len(self._payloads)]

    def total_items(self) -> int:
        return len(self._payloads)


class PowerQueryTable(QWidget):
    """Compact Power Query inspired preview with ribbon actions and context menus."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._protected_columns: Set[str] = set(PROTECTED_COLUMNS_DEFAULT)
        self._base_df = pd.DataFrame()
        self._transformed_df = pd.DataFrame()
        self._filtered_df = pd.DataFrame()
        self._geometry_available = True
        self._active_filters: Dict[str, List] = {}
        self._model = PowerQueryModel(pd.DataFrame(), self)
        self._materialize_callback: Optional[Callable[[pd.DataFrame, bool], None]] = None

        self._build_ui()
        self._configure_view()

    # ------------------------------------------------------------------ UI helpers
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.ribbon = QFrame()
        self.ribbon.setObjectName("pqRibbon")
        ribbon_layout = QHBoxLayout(self.ribbon)
        ribbon_layout.setContentsMargins(12, 8, 12, 8)
        ribbon_layout.setSpacing(8)

        self.ribbon_label = QLabel("Transformacoes velozes")
        self.ribbon_label.setProperty("role", "helper")
        ribbon_layout.addWidget(self.ribbon_label)
        ribbon_layout.addStretch()

        self.choose_columns_btn = QToolButton()
        self.choose_columns_btn.setText("Colunas")
        self.choose_columns_btn.setToolTip("Escolher colunas visiveis")
        ribbon_layout.addWidget(self.choose_columns_btn)

        self.remove_columns_btn = QToolButton()
        self.remove_columns_btn.setText("Remover")
        self.remove_columns_btn.setToolTip("Remover colunas selecionadas")
        ribbon_layout.addWidget(self.remove_columns_btn)

        self.split_column_btn = QToolButton()
        self.split_column_btn.setText("Dividir")
        ribbon_layout.addWidget(self.split_column_btn)

        self.group_by_btn = QToolButton()
        self.group_by_btn.setText("Agrupar")
        ribbon_layout.addWidget(self.group_by_btn)

        self.replace_values_btn = QToolButton()
        self.replace_values_btn.setText("Substituir")
        ribbon_layout.addWidget(self.replace_values_btn)

        self.revert_btn = QToolButton()
        self.revert_btn.setText("Reverter")
        ribbon_layout.addWidget(self.revert_btn)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("Atualizar")
        ribbon_layout.addWidget(self.refresh_btn)

        self.clear_filters_btn = QToolButton()
        self.clear_filters_btn.setText("Limpar filtros")
        ribbon_layout.addWidget(self.clear_filters_btn)

        self.materialize_btn = QToolButton()
        self.materialize_btn.setText("Criar camada")
        self.materialize_btn.setToolTip("Materializar dados filtrados")
        ribbon_layout.addWidget(self.materialize_btn)

        for button in [
            self.choose_columns_btn,
            self.remove_columns_btn,
            self.split_column_btn,
            self.group_by_btn,
            self.replace_values_btn,
            self.revert_btn,
            self.refresh_btn,
            self.clear_filters_btn,
            self.materialize_btn,
        ]:
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(28)

        layout.addWidget(self.ribbon, 0)
        self.materialize_btn.setEnabled(False)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("pqSplitter")
        layout.addWidget(self.splitter, 1)

        # Filter panel
        self.filter_panel = QFrame()
        self.filter_panel.setObjectName("filterPanel")
        filter_layout = QVBoxLayout(self.filter_panel)
        filter_layout.setContentsMargins(12, 12, 12, 12)
        filter_layout.setSpacing(6)

        filter_header = QHBoxLayout()
        filter_label = QLabel("Filtros ativos")
        filter_label.setProperty("role", "section")
        filter_header.addWidget(filter_label)
        filter_header.addStretch()
        filter_layout.addLayout(filter_header)

        self.filter_placeholder = QLabel("Nenhum filtro aplicado")
        self.filter_placeholder.setProperty("role", "helper")
        filter_layout.addWidget(self.filter_placeholder)

        self.filter_badge_container = QVBoxLayout()
        self.filter_badge_container.setContentsMargins(0, 0, 0, 0)
        self.filter_badge_container.setSpacing(6)
        filter_layout.addLayout(self.filter_badge_container)
        filter_layout.addStretch()

        self.splitter.addWidget(self.filter_panel)

        # Table panel
        self.table_panel = QFrame()
        self.table_panel.setObjectName("tablePanel")
        table_layout = QVBoxLayout(self.table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)

        self.view = QTableView()
        self.view.setModel(self._model)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.view, 1)

        self.status_bar = QFrame()
        self.status_bar.setObjectName("statusBar")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(12, 6, 12, 6)
        status_layout.setSpacing(12)

        self.status_label = QLabel("0 linha(s)")
        self.status_label.setProperty("role", "helper")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "helper")
        status_layout.addWidget(self.summary_label)

        table_layout.addWidget(self.status_bar, 0)

        self.splitter.addWidget(self.table_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setSizes([220, 880])

        # Connections
        self.choose_columns_btn.clicked.connect(self._choose_columns)
        self.remove_columns_btn.clicked.connect(self._remove_columns_command)
        self.split_column_btn.clicked.connect(self._split_column_command)
        self.group_by_btn.clicked.connect(self._group_by_command)
        self.replace_values_btn.clicked.connect(self._replace_values_command)
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        self.revert_btn.clicked.connect(self._revert_to_base)
        self.refresh_btn.clicked.connect(self._refresh_preview)
        self.materialize_btn.clicked.connect(self._materialize_current_view)

    def _configure_view(self):
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_cell_menu)

        header = self.view.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        header.setHighlightSections(False)

        self.view.setStyleSheet(
            """
            QFrame#pqRibbon {
                background-color: #ffffff;
                border: 1px solid #dfe3ec;
                border-radius: 0px;
            }
            QSplitter#pqSplitter::handle {
                background-color: #dfe3ec;
                width: 4px;
            }
            QFrame#filterPanel {
                background-color: #ffffff;
                border: 1px solid #dfe3ec;
                border-radius: 0px;
            }
            QFrame#tablePanel {
                background-color: #ffffff;
                border: 1px solid #dfe3ec;
                border-radius: 0px;
                padding: 8px;
            }
            QTableView {
                background-color: #f5f6fa;
                alternate-background-color: #eef1f8;
                gridline-color: #d9dce3;
                selection-background-color: #fff3c2;
                selection-color: #1d2a4b;
                border: none;
            }
            QTableView::item {
                padding: 4px 8px;
            }
            QHeaderView::section {
                background-color: #e7ebf5;
                color: #1d2a4b;
                font-weight: 600;
                border: none;
                border-right: 1px solid #d9dce3;
                padding: 6px 10px;
            }
            QFrame#statusBar {
                background-color: #ffffff;
                border-top: 1px solid #dfe3ec;
            }
            QFrame#filterBadge {
                background-color: #f7f9ff;
                border: 1px solid #d0d8ef;
                border-radius: 0px;
            }
            QFrame#filterBadge QPushButton {
                border: none;
                background: transparent;
                color: #1d2a4b;
            }
            QFrame#filterBadge QPushButton:hover {
                color: #d9534f;
            }
            """
        )

    # ------------------------------------------------------------------ Public API
    def set_dataframe(
        self,
        df: pd.DataFrame,
        protected_columns: Optional[Sequence[str]] = None,
    ):
        self._base_df = df.copy()
        self._transformed_df = df.copy()
        self._filtered_df = df.copy()
        self._active_filters.clear()
        if protected_columns is None:
            protected_columns = PROTECTED_COLUMNS_DEFAULT
        self._protected_columns = set(protected_columns)
        visible_cols = [c for c in df.columns if c not in self._protected_columns]
        self._set_transformed_df(df, visible_cols, reset_filters=True)

    def dataframe(self) -> pd.DataFrame:
        return self._filtered_df.copy()

    def geometry_available(self) -> bool:
        return self._geometry_available

    # ------------------------------------------------------------------ Internal helpers
    def _apply_dataframe(self, df: pd.DataFrame, visible: Optional[Sequence[str]] = None):
        if visible is None:
            visible = self._model.visible_columns
        if not visible:
            visible = [c for c in df.columns if c not in self._protected_columns]
        self._model.set_dataframe(df, visible)
        self._filtered_df = df.copy()
        row_count = len(df.index)
        col_count = len([c for c in df.columns if c not in self._protected_columns])
        self.status_label.setText(f"{row_count} linha(s)")
        self.summary_label.setText(f"{col_count} coluna(s)")
        self.view.resizeColumnsToContents()

    def _set_transformed_df(
        self,
        df: pd.DataFrame,
        visible: Optional[Sequence[str]] = None,
        reset_filters: bool = False,
    ):
        self._transformed_df = df.copy()
        self._update_geometry_flag()
        if reset_filters:
            self._active_filters.clear()
        else:
            to_remove = [col for col in self._active_filters if col not in df.columns]
            for col in to_remove:
                self._active_filters.pop(col, None)
        if visible is None:
            visible = [c for c in df.columns if c not in self._protected_columns]
        self._apply_dataframe(df, visible)
        self._refresh_filter_badges()

    def _update_geometry_flag(self):
        if "__geometry_wkb" not in self._transformed_df.columns:
            self._geometry_available = False
            return
        series = self._transformed_df["__geometry_wkb"]
        self._geometry_available = series.notna().any()

    def _visible_user_columns(self) -> List[str]:
        return [c for c in self._transformed_df.columns if c not in self._protected_columns]

    def _format_filter_values(self, values: List) -> str:
        display_values = [_display_text(val) for val in values]
        if len(display_values) > 3:
            return ", ".join(display_values[:3]) + f" (+{len(display_values) - 3})"
        return ", ".join(display_values) if display_values else "Todos"

    def _refresh_filter_badges(self):
        while self.filter_badge_container.count():
            item = self.filter_badge_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._active_filters:
            self.filter_placeholder.setVisible(True)
            return
        self.filter_placeholder.setVisible(False)
        for column, values in self._active_filters.items():
            badge = QFrame()
            badge.setObjectName("filterBadge")
            badge_layout = QHBoxLayout(badge)
            badge_layout.setContentsMargins(10, 6, 6, 6)
            badge_layout.setSpacing(6)
            label = QLabel(f"{column}: {self._format_filter_values(values)}")
            label.setWordWrap(True)
            badge_layout.addWidget(label)
            clear_btn = QPushButton("x")
            clear_btn.setFixedSize(18, 18)
            clear_btn.clicked.connect(lambda _, col=column: self._remove_filter(col))
            badge_layout.addWidget(clear_btn, 0, Qt.AlignTop)
            self.filter_badge_container.addWidget(badge, 0, Qt.AlignTop)
        self.filter_badge_container.addStretch()

    def _remove_filter(self, column: str):
        if column in self._active_filters:
            self._active_filters.pop(column, None)
            self._apply_filters()

    def _apply_filters(self):
        df = self._transformed_df.copy()
        for column, values in self._active_filters.items():
            if column not in df.columns:
                continue
            series = df[column]
            allowed_values = [val for val in values if val is not NULL_SENTINEL]
            mask = pd.Series(True, index=df.index)
            if allowed_values:
                mask &= series.isin(allowed_values)
            if any(val is NULL_SENTINEL for val in values):
                mask |= series.isna()
            df = df[mask]
        self._apply_dataframe(df, self._model.visible_columns)
        self._refresh_filter_badges()

    def _ensure_column_available(self, column: str) -> bool:
        if column not in self._transformed_df.columns:
            QMessageBox.warning(self, "Coluna", f"A coluna '{column}' nao esta disponivel.")
            return False
        if column in self._protected_columns:
            QMessageBox.warning(self, "Coluna", "Esta coluna e protegida e nao pode ser alterada.")
            return False
        return True

    def _unique_column_name(self, base_name: str) -> str:
        candidate = base_name
        counter = 1
        existing = set(self._transformed_df.columns)
        while candidate in existing:
            counter += 1
            candidate = f"{base_name}_{counter}"
        return candidate

    # ------------------------------------------------------------------ Command bar actions
    def _choose_columns(self):
        columns = self._visible_user_columns()
        if not columns:
            QMessageBox.information(self, "Colunas", "Nao ha colunas disponiveis.")
            return
        dialog = SlimLayerSelectionDialog(
            "Escolher colunas",
            columns,
            parent=self,
            checked_items=self._model.visible_columns,
            geometry_key="PowerBISummarizer/dialogs/chooseColumns",
            header_text="Selecione as colunas que deseja exibir",
            search_placeholder="Buscar colunas...",
            select_all_label="Selecionar todas",
            clear_all_label="Limpar selecao",
            empty_selection_message="Selecione ao menos uma coluna.",
        )
        dialog.set_focus_on_search()
        if dialog.exec_() != QDialog.Accepted:
            return
        selected = dialog.selected_labels()
        if not selected:
            QMessageBox.warning(self, "Colunas", "Selecione ao menos uma coluna.")
            return
        visible = [c for c in selected if c in self._transformed_df.columns]
        self._apply_dataframe(self._filtered_df, visible)

    def _remove_columns_command(self):
        columns = self._visible_user_columns()
        if not columns:
            QMessageBox.information(self, "Remover colunas", "Nao ha colunas removiveis.")
            return
        dialog = SlimLayerSelectionDialog(
            "Remover colunas",
            columns,
            parent=self,
            checked_items=columns,
            geometry_key="PowerBISummarizer/dialogs/removeColumns",
            header_text="Desmarque as colunas que deseja remover",
            search_placeholder="Buscar colunas...",
            select_all_label="Selecionar todas",
            clear_all_label="Limpar selecao",
            empty_selection_message="Nenhuma coluna selecionada.",
        )
        dialog.set_focus_on_search()
        if dialog.exec_() != QDialog.Accepted:
            return
        selected = dialog.selected_labels()
        if not selected:
            return
        df = self._transformed_df.drop(columns=[c for c in selected if c in self._transformed_df.columns])
        visible = [c for c in self._model.visible_columns if c in df.columns]
        self._set_transformed_df(df, visible, reset_filters=True)

    def _split_column_command(self):
        column = self._prompt_single_column("Dividir coluna")
        if not column:
            return
        choice, ok = slim_get_item(
            self,
            "Dividir coluna",
            "Escolha o metodo:",
            ["Por delimitador", "Em segmentos de tamanho fixo"],
            current=0,
        )
        if not ok:
            return
        if choice == "Por delimitador":
            self._split_column_delimiter(column)
        else:
            self._split_column_every(column)

    def _group_by_command(self):
        column = self._prompt_single_column("Agrupar por")
        if column:
            self._group_by(column)

    def _replace_values_command(self):
        column = self._prompt_single_column("Substituir valores")
        if column:
            self._replace_values(column)

    def _clear_filters(self):
        if not self._active_filters:
            self._apply_dataframe(self._transformed_df, self._model.visible_columns)
            return
        self._active_filters.clear()
        self._apply_filters()

    def _revert_to_base(self):
        visible = [c for c in self._base_df.columns if c not in self._protected_columns]
        self._set_transformed_df(self._base_df, visible, reset_filters=True)

    def _refresh_preview(self):
        self._apply_dataframe(self._transformed_df, self._model.visible_columns)

    def _prompt_single_column(self, title: str) -> Optional[str]:
        columns = self._model.visible_columns
        if not columns:
            QMessageBox.information(self, title, "Nenhuma coluna disponivel.")
            return None
        column, ok = slim_get_item(self, title, "Coluna:", columns, current=0)
        if not ok or not column:
            return None
        return column

    def set_materialize_callback(self, callback: Optional[Callable[[pd.DataFrame, bool], None]]):
        self._materialize_callback = callback
        self.materialize_btn.setEnabled(callback is not None)

    def _materialize_current_view(self):
        if self._materialize_callback is None:
            QMessageBox.information(
                self,
                "Criar camada",
                "Nenhuma rotina de materializacao foi configurada.",
            )
            return
        df = self.dataframe()
        if df.empty:
            QMessageBox.information(
                self,
                "Criar camada",
                "Nenhum dado filtrado para materializar.",
            )
            return
        try:
            self._materialize_callback(df, self.geometry_available())
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Criar camada",
                f"Falha ao materializar os dados: {exc}",
            )

    # ------------------------------------------------------------------ Menu building
    def _show_header_menu(self, pos: QPoint):
        header = self.view.horizontalHeader()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return
        column = self._model.visible_columns[logical_index]
        menu = QMenu(self)

        menu.addAction("Filtrar por valores", lambda: self._filter_values(column))
        menu.addAction("Limpar filtros", self._clear_filters)
        menu.addSeparator()
        menu.addAction("Copiar coluna", lambda: self._copy_column(column))
        menu.addSeparator()

        remove_action = QAction("Remover coluna", self)
        remove_action.triggered.connect(lambda: self._remove_column(column))
        menu.addAction(remove_action)

        remove_others = QAction("Remover outras colunas", self)
        remove_others.triggered.connect(lambda: self._remove_other_columns(column))
        menu.addAction(remove_others)

        duplicate_action = QAction("Duplicar coluna", self)
        duplicate_action.triggered.connect(lambda: self._duplicate_column(column))
        menu.addAction(duplicate_action)

        add_example = QAction("Adicionar coluna de exemplo", self)
        add_example.triggered.connect(lambda: self._add_example_column(column))
        menu.addAction(add_example)

        menu.addSeparator()
        menu.addAction("Remover duplicadas", lambda: self._remove_duplicates(column))
        menu.addAction("Remover erros", lambda: self._remove_errors(column))

        type_menu = menu.addMenu("Alterar tipo")
        type_menu.addAction("Texto", lambda: self._change_type(column, "text"))
        type_menu.addAction("Inteiro", lambda: self._change_type(column, "int"))
        type_menu.addAction("Decimal", lambda: self._change_type(column, "float"))
        type_menu.addAction("Data", lambda: self._change_type(column, "date"))

        replace_action = QAction("Substituir valores", self)
        replace_action.triggered.connect(lambda: self._replace_values(column))
        menu.addAction(replace_action)

        split_menu = menu.addMenu("Dividir coluna")
        split_menu.addAction("Por delimitador", lambda: self._split_column_delimiter(column))
        split_menu.addAction("Em segmentos de tamanho", lambda: self._split_column_every(column))

        menu.addSeparator()
        menu.addAction("Agrupar por", lambda: self._group_by(column))
        menu.addAction("Preencher para baixo", lambda: self._fill_down(column))
        menu.addSeparator()
        menu.addAction("Transformar colunas em linhas (Unpivot)", self._unpivot_columns)
        menu.addAction("Transformar linhas em colunas (Pivot)", lambda: self._pivot_columns(column))

        menu.addSeparator()
        menu.addAction("Renomear", lambda: self._rename_column(column))
        move_menu = menu.addMenu("Mover")
        move_menu.addAction("Esquerda", lambda: self._move_column(column, -1))
        move_menu.addAction("Direita", lambda: self._move_column(column, 1))

        menu.exec_(header.mapToGlobal(pos))

    def _show_cell_menu(self, pos: QPoint):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        column = self._model.visible_columns[index.column()]
        try:
            value = self._filtered_df.iloc[row][column]
        except Exception:
            value = None

        menu = QMenu(self)
        menu.addAction("Copiar valor", lambda: self._copy_value(value))
        menu.addAction("Copiar linha", lambda: self._copy_row(row))
        menu.addSeparator()
        menu.addAction("Manter apenas este valor", lambda: self._drill_down(column, value))
        menu.addAction("Remover este valor", lambda: self._exclude_value(column, value))
        menu.addSeparator()
        menu.addAction("Remover linha", lambda: self._remove_rows([row]))
        menu.exec_(self.view.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ Column & row operations
    def _filter_values(self, column: str):
        if column not in self._transformed_df.columns:
            return
        dialog = ValueFilterDialog(column, self._transformed_df[column], self)
        if dialog.exec_() != QDialog.Accepted:
            return
        selected = dialog.selected_values()
        if not selected or len(selected) == dialog.total_items():
            self._active_filters.pop(column, None)
        else:
            self._active_filters[column] = selected
        self._apply_filters()

    def _copy_column(self, column: str):
        if column not in self._filtered_df.columns:
            return
        clipboard: QClipboard = QGuiApplication.clipboard()
        text = "\n".join("" if pd.isna(v) else str(v) for v in self._filtered_df[column])
        clipboard.setText(text)

    def _remove_column(self, column: str):
        if not self._ensure_column_available(column):
            return
        df = self._transformed_df.drop(columns=[column])
        visible = [c for c in self._model.visible_columns if c != column]
        self._set_transformed_df(df, visible, reset_filters=True)

    def _remove_other_columns(self, column: str):
        if not self._ensure_column_available(column):
            return
        keep = [c for c in self._transformed_df.columns if c in self._protected_columns or c == column]
        df = self._transformed_df[keep].copy()
        visible = [c for c in df.columns if c not in self._protected_columns]
        self._set_transformed_df(df, visible, reset_filters=True)

    def _duplicate_column(self, column: str):
        if column not in self._transformed_df.columns:
            return
        new_name = self._unique_column_name(f"{column}_copia")
        df = self._transformed_df.copy()
        df[new_name] = df[column]
        visible = list(self._model.visible_columns)
        if column in visible:
            insert_index = visible.index(column) + 1
            visible.insert(insert_index, new_name)
        else:
            visible.append(new_name)
        self._set_transformed_df(df, visible, reset_filters=False)

    def _add_example_column(self, column: str):
        if column not in self._transformed_df.columns:
            return
        option, ok = slim_get_item(
            self,
            "Coluna de exemplo",
            "Escolha um modelo:",
            ["Maiusculas", "Minusculas", "Tamanho do texto"],
            current=0,
        )
        if not ok or not option:
            return
        df = self._transformed_df.copy()
        base_series = df[column]
        if option == "Maiusculas":
            new_series = base_series.astype(str).str.upper()
            suffix = "upper"
        elif option == "Minusculas":
            new_series = base_series.astype(str).str.lower()
            suffix = "lower"
        else:
            new_series = base_series.astype(str).str.len()
            suffix = "len"
        new_name = self._unique_column_name(f"{column}_{suffix}")
        df[new_name] = new_series
        visible = list(self._model.visible_columns)
        if column in visible:
            visible.insert(visible.index(column) + 1, new_name)
        else:
            visible.append(new_name)
        self._set_transformed_df(df, visible, reset_filters=False)

    def _remove_duplicates(self, column: str):
        if column not in self._transformed_df.columns:
            return
        df = self._transformed_df.drop_duplicates(subset=[column])
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=True)

    def _remove_errors(self, column: str):
        if column not in self._transformed_df.columns:
            return
        series = self._transformed_df[column]
        mask = ~series.isna()
        if series.dtype == object:
            mask &= series.astype(str).str.strip().ne("")
        df = self._transformed_df[mask]
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=True)

    def _change_type(self, column: str, target: str):
        if column not in self._transformed_df.columns:
            return
        df = self._transformed_df.copy()
        try:
            if target == "text":
                df[column] = df[column].astype(str)
            elif target == "int":
                df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
            elif target == "float":
                df[column] = pd.to_numeric(df[column], errors="coerce")
            elif target == "date":
                df[column] = pd.to_datetime(df[column], errors="coerce")
        except Exception as exc:
            QMessageBox.warning(self, "Alterar tipo", f"Nao foi possivel converter os valores: {exc}")
            return
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=False)

    def _replace_values(self, column: str):
        if column not in self._transformed_df.columns:
            return
        old_value, ok = slim_get_text(self, "Substituir valores", "Valor a substituir:")
        if not ok:
            return
        new_value, ok = slim_get_text(self, "Substituir valores", "Novo valor:")
        if not ok:
            return
        df = self._transformed_df.copy()
        df[column] = df[column].replace(old_value, new_value)
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=False)

    def _split_column_delimiter(self, column: str):
        if not self._ensure_column_available(column):
            return
        delimiter, ok = slim_get_text(self, "Dividir coluna", "Informe o delimitador:", text=",")
        if not ok or delimiter == "":
            return
        df = self._transformed_df.copy()
        split_df = (
            df[column]
            .astype(str)
            .str.split(delimiter, expand=True)
            .replace({None: "", "None": ""})
        )
        new_columns = []
        for idx in range(split_df.shape[1]):
            new_name = self._unique_column_name(f"{column}_part{idx + 1}")
            df[new_name] = split_df[idx].str.strip()
            new_columns.append(new_name)
        visible = list(self._model.visible_columns)
        insert_at = visible.index(column) + 1 if column in visible else len(visible)
        for offset, name in enumerate(new_columns):
            visible.insert(insert_at + offset, name)
        self._set_transformed_df(df, visible, reset_filters=False)

    def _split_column_every(self, column: str):
        if not self._ensure_column_available(column):
            return
        size, ok = slim_get_int(self, "Dividir coluna", "Tamanho de cada segmento:", 2, 1, 100, step=1)
        if not ok:
            return
        df = self._transformed_df.copy()
        series = df[column].fillna("").astype(str)
        chunks = series.apply(lambda text: [text[i : i + size] for i in range(0, len(text), size)])
        max_parts = chunks.apply(len).max()
        new_columns = []
        for idx in range(max_parts):
            new_name = self._unique_column_name(f"{column}_chunk{idx + 1}")
            df[new_name] = chunks.apply(lambda parts, index=idx: parts[index] if index < len(parts) else "")
            new_columns.append(new_name)
        visible = list(self._model.visible_columns)
        insert_at = visible.index(column) + 1 if column in visible else len(visible)
        for offset, name in enumerate(new_columns):
            visible.insert(insert_at + offset, name)
        self._set_transformed_df(df, visible, reset_filters=False)

    def _group_by(self, column: str):
        if column not in self._transformed_df.columns:
            return
        choice, ok = slim_get_item(
            self,
            "Agrupar por",
            "Escolha o agregado:",
            ["Contagem", "Soma", "Media"],
            current=0,
        )
        if not ok:
            return
        df = self._transformed_df.copy()
        numeric_cols = [c for c in df.columns if ptypes.is_numeric_dtype(df[c]) and c not in self._protected_columns]
        group = df.groupby(column, dropna=False)
        if choice == "Contagem":
            result = group.size().reset_index(name="contagem")
        elif choice == "Soma":
            if not numeric_cols:
                QMessageBox.warning(self, "Agrupar por", "Nao ha colunas numericas para somar.")
                return
            result = group[numeric_cols].sum(min_count=1).reset_index()
        else:
            if not numeric_cols:
                QMessageBox.warning(self, "Agrupar por", "Nao ha colunas numericas para calcular a media.")
                return
            result = group[numeric_cols].mean(numeric_only=True).reset_index()
        self._set_transformed_df(result, [c for c in result.columns if c not in self._protected_columns], reset_filters=True)

    def _fill_down(self, column: str):
        if column not in self._transformed_df.columns:
            return
        df = self._transformed_df.copy()
        df[column] = df[column].ffill()
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=False)

    def _unpivot_columns(self):
        columns = self._visible_user_columns()
        if len(columns) < 2:
            QMessageBox.warning(self, "Unpivot", "Sao necessarias ao menos duas colunas.")
            return
        dialog = SlimLayerSelectionDialog(
            "Colunas para transformar em linhas",
            columns,
            parent=self,
            checked_items=columns,
            geometry_key="PowerBISummarizer/dialogs/unpivotColumns",
            header_text="Selecione as colunas que serao transformadas em linhas",
            search_placeholder="Buscar colunas...",
            select_all_label="Selecionar todas",
            clear_all_label="Limpar selecao",
            empty_selection_message="Nenhuma coluna selecionada.",
        )
        dialog.set_focus_on_search()
        if dialog.exec_() != QDialog.Accepted:
            return
        value_columns = dialog.selected_labels()
        if not value_columns:
            return
        id_columns = [c for c in self._transformed_df.columns if c not in value_columns]
        try:
            melted = self._transformed_df.melt(
                id_vars=id_columns,
                value_vars=value_columns,
                var_name="coluna",
                value_name="valor",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Unpivot", f"Nao foi possivel transformar as colunas: {exc}")
            return
        self._set_transformed_df(melted, [c for c in melted.columns if c not in self._protected_columns], reset_filters=True)

    def _pivot_columns(self, column: str):
        if column not in self._transformed_df.columns:
            return
        value_candidates = [c for c in self._visible_user_columns() if c != column]
        if not value_candidates:
            QMessageBox.warning(self, "Pivot", "Selecione ao menos uma coluna de valores.")
            return
        value_col, ok = slim_get_item(self, "Pivot", "Coluna de valores:", value_candidates, current=0)
        if not ok or not value_col:
            return
        index_candidates = [c for c in self._visible_user_columns() if c not in (column, value_col)]
        if not index_candidates:
            QMessageBox.warning(self, "Pivot", "Defina uma coluna base para o pivot.")
            return
        index_col, ok = slim_get_item(self, "Pivot", "Coluna base:", index_candidates, current=0)
        if not ok or not index_col:
            return
        agg_choice, ok = slim_get_item(
            self,
            "Pivot",
            "Agregacao:",
            ["Soma", "Media", "Contagem"],
            current=0,
        )
        if not ok:
            return
        agg_map = {"Soma": "sum", "Media": "mean", "Contagem": "count"}
        try:
            table = self._transformed_df.pivot_table(
                index=index_col,
                columns=column,
                values=value_col,
                aggfunc=agg_map[agg_choice],
                fill_value=0,
            ).reset_index()
        except Exception as exc:
            QMessageBox.warning(self, "Pivot", f"Nao foi possivel realizar o pivot: {exc}")
            return
        flat_columns = []
        for col in table.columns:
            if isinstance(col, tuple):
                col = "_".join(str(part) for part in col if part not in ("", None))
            flat_columns.append(str(col))
        table.columns = flat_columns
        self._set_transformed_df(table, [c for c in table.columns if c not in self._protected_columns], reset_filters=True)

    def _rename_column(self, column: str):
        if column not in self._transformed_df.columns:
            return
        new_name, ok = slim_get_text(self, "Renomear coluna", "Novo nome:", text=column)
        if not ok or not new_name:
            return
        if new_name in self._transformed_df.columns:
            QMessageBox.warning(self, "Renomear coluna", "Ja existe uma coluna com esse nome.")
            return
        df = self._transformed_df.copy()
        df = df.rename(columns={column: new_name})
        visible = [new_name if c == column else c for c in self._model.visible_columns]
        self._set_transformed_df(df, visible, reset_filters=False)

    def _move_column(self, column: str, offset: int):
        if column not in self._transformed_df.columns:
            return
        columns = list(self._transformed_df.columns)
        index = columns.index(column)
        new_index = max(0, min(len(columns) - 1, index + offset))
        if index == new_index:
            return
        columns.insert(new_index, columns.pop(index))
        df = self._transformed_df[columns]
        visible = [c for c in self._model.visible_columns if c in columns]
        if column in visible:
            vidx = visible.index(column)
            new_vidx = max(0, min(len(visible) - 1, vidx + offset))
            visible.insert(new_vidx, visible.pop(vidx))
        self._set_transformed_df(df, visible, reset_filters=False)

    def _copy_value(self, value):
        clipboard: QClipboard = QGuiApplication.clipboard()
        clipboard.setText("" if pd.isna(value) else str(value))

    def _copy_row(self, row: int):
        if self._filtered_df.empty or row >= len(self._filtered_df.index):
            return
        series = self._filtered_df.iloc[row]
        text = "\t".join("" if pd.isna(series[col]) else str(series[col]) for col in self._model.visible_columns if col in series.index)
        clipboard: QClipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def _drill_down(self, column: str, value):
        if column not in self._transformed_df.columns:
            return
        if value is None or pd.isna(value):
            selection = [NULL_SENTINEL]
        else:
            selection = [value]
        self._active_filters[column] = selection
        self._apply_filters()

    def _exclude_value(self, column: str, value):
        if column not in self._transformed_df.columns:
            return
        series = self._transformed_df[column]
        if value is None or pd.isna(value):
            self._active_filters[column] = [val for val in series.dropna().unique().tolist()]
        else:
            unique_values = series.dropna().unique().tolist()
            selection = [val for val in unique_values if val != value]
            if series.isna().any():
                selection.append(NULL_SENTINEL)
            self._active_filters[column] = selection
        self._apply_filters()

    def _remove_rows(self, rows: List[int]):
        if not rows or self._filtered_df.empty:
            return
        indexes = self._filtered_df.iloc[rows].index
        df = self._transformed_df.drop(index=indexes, errors="ignore")
        self._set_transformed_df(df, self._model.visible_columns, reset_filters=True)

