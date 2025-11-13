from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .cloud_session import cloud_session
from .slim_dialogs import SlimDialogBase


class PowerBICloudDialog(SlimDialogBase):
    """Popup used both in the Integration tab and Browser shortcuts."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, geometry_key="PowerBISummarizer/cloud/dialog")
        self.setWindowTitle("PowerBI Cloud (beta)")
        self.resize(640, 420)
        self._build_ui()
        self._connect_signals()
        self._update_session_ui()
        self._update_config_ui()
        self._on_layers_changed()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Gerenciar sessao PowerBI Cloud", self)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self.cloud_status_badge = QLabel("Desconectado", self)
        self.cloud_status_badge.setObjectName("cloudDialogStatusBadge")
        header.addWidget(self.cloud_status_badge, 0, Qt.AlignRight)
        layout.addLayout(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("cloudDialogTabs")
        layout.addWidget(self.tabs, 1)

        # Session tab ----------------------------------------------------
        session_tab = QWidget(self.tabs)
        session_layout = QGridLayout(session_tab)
        session_layout.setContentsMargins(12, 12, 12, 12)
        session_layout.setHorizontalSpacing(12)
        session_layout.setVerticalSpacing(10)

        self.user_edit = QLineEdit(session_tab)
        self.user_edit.setPlaceholderText("usuario@empresa.com")
        self.password_edit = QLineEdit(session_tab)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("********")

        session_layout.addWidget(QLabel("Usuario", session_tab), 0, 0)
        session_layout.addWidget(self.user_edit, 0, 1)
        session_layout.addWidget(QLabel("Senha", session_tab), 1, 0)
        session_layout.addWidget(self.password_edit, 1, 1)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.login_btn = QPushButton("Entrar", session_tab)
        self.logout_btn = QPushButton("Sair", session_tab)
        self.logout_btn.setProperty("variant", "secondary")
        self.refresh_btn = QPushButton("Atualizar mock", session_tab)
        self.refresh_btn.setProperty("variant", "ghost")
        self.browser_btn = QPushButton("Abrir no Navegador", session_tab)
        self.browser_btn.setProperty("variant", "ghost")
        buttons_row.addWidget(self.login_btn)
        buttons_row.addWidget(self.logout_btn)
        buttons_row.addWidget(self.refresh_btn)
        buttons_row.addWidget(self.browser_btn)
        buttons_row.addStretch(1)
        session_layout.addLayout(buttons_row, 2, 0, 1, 2)

        self.session_detail = QLabel("Status: aguardando login.", session_tab)
        self.session_detail.setWordWrap(True)
        session_layout.addWidget(self.session_detail, 3, 0, 1, 2)

        sync_layout = QHBoxLayout()
        sync_layout.addWidget(QLabel("Ultima sincronizacao mock:", session_tab))
        self.last_sync_label = QLabel("-", session_tab)
        sync_layout.addWidget(self.last_sync_label)
        sync_layout.addStretch(1)
        session_layout.addLayout(sync_layout, 4, 0, 1, 2)

        self.warning_label = QLabel(
            "Cloud em preparacao. Camadas reais serao liberadas quando a hospedagem estiver ativa.",
            session_tab,
        )
        self.warning_label.setWordWrap(True)
        self.warning_label.setProperty("role", "helper")
        session_layout.addWidget(self.warning_label, 5, 0, 1, 2)

        self.tabs.addTab(session_tab, "Sessao")

        # Config tab -----------------------------------------------------
        config_tab = QWidget(self.tabs)
        config_layout = QGridLayout(config_tab)
        config_layout.setContentsMargins(12, 12, 12, 12)
        config_layout.setHorizontalSpacing(12)
        config_layout.setVerticalSpacing(10)

        self.base_url_edit = QLineEdit(config_tab)
        self.login_endpoint_edit = QLineEdit(config_tab)
        self.layers_endpoint_edit = QLineEdit(config_tab)
        self.hosting_checkbox = QCheckBox("Hospedagem ativa (liberar camadas reais)", config_tab)

        config_layout.addWidget(QLabel("Base URL", config_tab), 0, 0)
        config_layout.addWidget(self.base_url_edit, 0, 1)
        config_layout.addWidget(QLabel("Endpoint de login", config_tab), 1, 0)
        config_layout.addWidget(self.login_endpoint_edit, 1, 1)
        config_layout.addWidget(QLabel("Endpoint de camadas", config_tab), 2, 0)
        config_layout.addWidget(self.layers_endpoint_edit, 2, 1)
        config_layout.addWidget(self.hosting_checkbox, 3, 0, 1, 2)

        config_buttons = QHBoxLayout()
        config_buttons.setSpacing(8)
        self.save_config_btn = QPushButton("Salvar configuracoes", config_tab)
        self.test_real_btn = QPushButton("Testar camadas reais", config_tab)
        self.test_real_btn.setProperty("variant", "ghost")
        config_buttons.addWidget(self.save_config_btn)
        config_buttons.addWidget(self.test_real_btn)
        config_buttons.addStretch(1)
        config_layout.addLayout(config_buttons, 4, 0, 1, 2)

        config_hint = QLabel(
            "Planeje apontar para o dominio final (ex.: Hostinger) assim que a API estiver ativa. "
            "Enquanto estiver em preparacao, apenas camadas mock locais sao exibidas.",
            config_tab,
        )
        config_hint.setWordWrap(True)
        config_hint.setProperty("role", "helper")
        config_layout.addWidget(config_hint, 5, 0, 1, 2)

        self.tabs.addTab(config_tab, "Configuracoes Cloud")

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _connect_signals(self):
        self.login_btn.clicked.connect(self._handle_login)
        self.password_edit.returnPressed.connect(self._handle_login)
        self.logout_btn.clicked.connect(self._handle_logout)
        self.refresh_btn.clicked.connect(self._refresh_layers)
        self.browser_btn.clicked.connect(self._open_browser_hint)
        self.save_config_btn.clicked.connect(self._save_config)
        self.test_real_btn.clicked.connect(self._handle_real_access_attempt)
        cloud_session.sessionChanged.connect(lambda *_: self._update_session_ui())
        cloud_session.configChanged.connect(lambda *_: self._update_config_ui())
        cloud_session.layersChanged.connect(lambda *_: self._on_layers_changed())

    # ------------------------------------------------------------------ Cloud actions
    def _handle_login(self):
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "PowerBI Cloud", "Informe usuario e senha.")
            return
        try:
            session_payload = cloud_session.login(username, password)
            mode = session_payload.get("mode") or "mock"
            if mode == "remote":
                message = (
                    f"Sessao Cloud autenticada para {username}.\n"
                    "Catalogo carregado a partir da API configurada."
                )
            else:
                message = (
                    f"Sessao mock ativa para {username}.\n"
                    "Ative 'Hospedagem ativa' quando o deploy estiver pronto para usar o banco remoto."
                )
            QMessageBox.information(
                self,
                "PowerBI Cloud",
                message,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "PowerBI Cloud", str(exc))
        except Exception as exc:  # pragma: no cover - runtime safeguard
            QMessageBox.critical(self, "PowerBI Cloud", f"Falha no login: {exc}")
        finally:
            self.password_edit.clear()

    def _handle_logout(self):
        cloud_session.logout()

    def _refresh_layers(self):
        cloud_session.reload_mock_layers()
        self._on_layers_changed()
        if cloud_session.session().get("mode") == "remote" and cloud_session.hosting_ready():
            message = "Catalogo Cloud atualizado a partir da API."
        else:
            message = "Catalogo mock atualizado."
        QMessageBox.information(self, "PowerBI Cloud", message)

    def _open_browser_hint(self):
        QMessageBox.information(
            self,
            "PowerBI Cloud",
            "Abra o painel Navegador do QGIS e expanda PowerBI Summarizer -> PowerBI Cloud "
            "para carregar as camadas mockadas.",
        )

    def _save_config(self):
        cloud_session.update_config(
            base_url=self.base_url_edit.text().strip(),
            login_endpoint=self.login_endpoint_edit.text().strip(),
            layers_endpoint=self.layers_endpoint_edit.text().strip(),
            hosting_ready=self.hosting_checkbox.isChecked(),
        )
        QMessageBox.information(self, "PowerBI Cloud", "Configuracoes salvas.")

    def _handle_real_access_attempt(self):
        if not cloud_session.hosting_ready():
            QMessageBox.information(
                self,
                "PowerBI Cloud",
                "Cloud em preparacao. Camadas reais serao liberadas apos a hospedagem estar ativa.",
            )
            return
        QMessageBox.information(
            self,
            "PowerBI Cloud",
            "Endpoints reais serao conectados assim que a infraestrutura estiver publicada.",
        )

    # ------------------------------------------------------------------ Helpers
    def _set_status_badge(self, level: str, text: str):
        colors = {"online": "#2F8D46", "offline": "#B3261E", "sync": "#F2994A"}
        color = colors.get(level, "#5D5A58")
        self.cloud_status_badge.setText(text)
        self.cloud_status_badge.setStyleSheet(
            f"""
            QLabel#cloudDialogStatusBadge {{
                padding: 4px 14px;
                border-radius: 14px;
                font-weight: 600;
                color: #FFFFFF;
                background-color: {color};
            }}
            """
        )

    def _format_timestamp(self, iso_text: str) -> str:
        stamp = QDateTime.fromString(iso_text, Qt.ISODate)
        if stamp.isValid():
            return stamp.toString("dd/MM HH:mm")
        return iso_text

    def _update_session_ui(self):
        payload = cloud_session.status_payload()
        level = payload.get("level") or "offline"
        status_text = payload.get("text") or "Desconectado"
        self._set_status_badge(level, status_text)
        is_auth = cloud_session.is_authenticated()
        self.login_btn.setEnabled(not is_auth)
        self.user_edit.setEnabled(not is_auth)
        self.password_edit.setEnabled(not is_auth)
        self.logout_btn.setEnabled(is_auth)
        if is_auth:
            self.user_edit.setText(cloud_session.session().get("username", ""))
        session_details = []
        if is_auth:
            session_meta = cloud_session.session()
            issued = session_meta.get("issued")
            if issued:
                session_details.append(f"Iniciada em {self._format_timestamp(issued)}.")
            if session_meta.get("mode") == "remote":
                expires_at = session_meta.get("expires_at")
                if expires_at:
                    session_details.append(f"Token expira em {self._format_timestamp(expires_at)}.")
                session_details.append("Conectado ao banco remoto configurado.")
            else:
                session_details.append("Modo demonstracao usando camadas mock.")
        else:
            session_details.append("Status: aguardando login.")
        self.session_detail.setText("\n".join(session_details))
        self.warning_label.setVisible(not cloud_session.hosting_ready())

    def _update_config_ui(self):
        config = cloud_session.config()
        self.base_url_edit.setText(config.get("base_url", ""))
        self.login_endpoint_edit.setText(config.get("login_endpoint", ""))
        self.layers_endpoint_edit.setText(config.get("layers_endpoint", ""))
        self.hosting_checkbox.setChecked(bool(config.get("hosting_ready")))
        self.warning_label.setVisible(not cloud_session.hosting_ready())

    def _on_layers_changed(self):
        stamp = QDateTime.currentDateTime().toString("dd/MM HH:mm")
        self.last_sync_label.setText(stamp)


def open_cloud_dialog(parent: Optional[QWidget] = None) -> PowerBICloudDialog:
    """Helper used by different entry points."""
    dialog = PowerBICloudDialog(parent)
    dialog.exec_()
    return dialog


__all__ = ["PowerBICloudDialog", "open_cloud_dialog"]
