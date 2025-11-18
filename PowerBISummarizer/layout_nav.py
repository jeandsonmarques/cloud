import os
from typing import Dict, Optional

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QWidget,
    QToolTip,
)

from .cloud_session import cloud_session


class SidebarController:
    """Slim icon-only navigation for the Power BI Summarizer dialog."""

    ICON_MAP = {
        "resumo": ("Resumo", "Table.svg"),
        "comparar": ("Comparar", "Workspace.svg"),
        "integracao": ("Integração", "Model.svg"),
    }

    PAGE_MAP = {
        "resumo": "pageResultados",
        "comparar": "pageComparar",
        "integracao": "pageIntegracao",
    }

    def __init__(self, ui_or_host):
        if hasattr(ui_or_host, "ui"):
            self.host = ui_or_host
            self.ui = ui_or_host.ui
        else:
            self.host = None
            self.ui = ui_or_host

        self.buttons: Dict[str, QPushButton] = {}
        self.export_button: Optional[QPushButton] = None
        self.upload_button: Optional[QPushButton] = None
        self.current_mode: Optional[str] = None

        self._build_sidebar()
        try:
            cloud_session.sessionChanged.connect(lambda *_: self._update_upload_button_state())
        except Exception:
            pass
        self._update_upload_button_state()
        self._set_mode("resumo")

    def _build_sidebar(self):
        container = getattr(self.ui, "sidebar_container", None)
        if container is None:
            return

        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

        icons_dir = os.path.join(os.path.dirname(__file__), "resources", "icons")

        for mode, (tooltip, icon_name) in self.ICON_MAP.items():
            btn = QPushButton("")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setFixedSize(40, 40)
            btn.setIconSize(QSize(24, 24))
            btn.setProperty("navIcon", "true")
            icon_path = os.path.join(icons_dir, icon_name)
            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
            btn.clicked.connect(lambda checked, m=mode: self._handle_nav_click(m))
            layout.addWidget(btn, 0, Qt.AlignTop)
            self.buttons[mode] = btn

        layout.addStretch(1)

        self.export_button = QPushButton("")
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.setToolTip("Exportar camadas")
        self.export_button.setFixedSize(40, 40)
        self.export_button.setIconSize(QSize(24, 24))
        self.export_button.setProperty("navIcon", "true")
        export_icon_path = os.path.join(icons_dir, "PowerPages.svg")
        if os.path.exists(export_icon_path):
            self.export_button.setIcon(QIcon(export_icon_path))
        layout.addWidget(self.export_button, 0, Qt.AlignBottom)
        if self.host is not None:
            self.export_button.clicked.connect(self._trigger_export)

        self.upload_button = QPushButton("")
        self.upload_button.setCursor(Qt.PointingHandCursor)
        self.upload_button.setToolTip("Enviar camadas para o PowerBI Cloud (apenas admin)")
        self.upload_button.setFixedSize(40, 40)
        self.upload_button.setIconSize(QSize(24, 24))
        self.upload_button.setProperty("navIcon", "true")
        upload_icon_path = os.path.join(icons_dir, "cloud.svg")
        if os.path.exists(upload_icon_path):
            self.upload_button.setIcon(QIcon(upload_icon_path))
        layout.addWidget(self.upload_button, 0, Qt.AlignBottom)
        if self.host is not None:
            self.upload_button.clicked.connect(self._trigger_upload)

    def _trigger_export(self):
        host = self.host
        if host is None:
            return
        try:
            host.export_all_vector_layers()
        except Exception:
            pass

    def _trigger_upload(self):
        host = self.host
        if host is None:
            return
        try:
            host.open_cloud_upload_tab()
        except Exception:
            pass

    def _update_upload_button_state(self):
        if self.upload_button is None:
            return
        is_admin = False
        try:
            is_admin = cloud_session.is_admin()
        except Exception:
            is_admin = False
        self.upload_button.setEnabled(is_admin)
        self.upload_button.setVisible(is_admin)

    def _handle_nav_click(self, mode: str):
        btn = self.buttons.get(mode)
        if btn is not None:
            pos = btn.mapToGlobal(btn.rect().center())
            QToolTip.showText(pos, btn.toolTip(), btn)
        self._set_mode(mode)

    def _set_mode(self, mode: str):
        if mode == self.current_mode:
            return

        self.current_mode = mode

        for key, btn in self.buttons.items():
            btn.setChecked(key == mode)

        stacked = getattr(self.ui, "stackedWidget", None)
        if stacked is not None:
            page_attr = self.PAGE_MAP.get(mode)
            page = getattr(self.ui, page_attr, None)
            if page is not None:
                stacked.setCurrentWidget(page)

        host = self.host
        if host is None:
            return

        try:
            if mode == "resumo":
                if getattr(host, "current_summary_data", None):
                    host.display_advanced_summary(host.current_summary_data)
                else:
                    host.show_summary_prompt()
            elif mode == "comparar":
                host.show_compare_prompt()
            elif mode == "integracao":
                host.show_integration_page()
        except Exception:
            pass

    # Public helpers ---------------------------------------------------
    def show_integration_page(self):
        self._set_mode("integracao")

    def show_results_page(self):
        self._set_mode("resumo")

    def show_compare_page(self):
        self._set_mode("comparar")
