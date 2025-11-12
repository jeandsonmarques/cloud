import os
from qgis.PyQt.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QComboBox,
    QPushButton,
    QCheckBox,
    QLineEdit,
    QGridLayout,
    QProgressBar,
    QWidget,
    QSizePolicy,
    QFrame,
    QStackedWidget,
    QToolButton,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox
from qgis.core import QgsMapLayerProxyModel


class Ui_PowerBISummarizerDialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(1200, 800)
        Dialog.setWindowTitle("Power BI Summarizer - QGIS")

        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setContentsMargins(12, 12, 12, 12)
        self.verticalLayout.setSpacing(8)

        # Header ----------------------------------------------------------------
        self.header_widget = QFrame()
        self.header_widget.setObjectName("headerCard")
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(16, 16, 16, 12)
        header_layout.setSpacing(16)

        logo_path = os.path.join(
            os.path.dirname(__file__), "resources", "icons", "plugin_logo.svg"
        )
        self.logo_label = QLabel()
        logo_pixmap = QPixmap(logo_path)
        if not logo_pixmap.isNull():
            self.logo_label.setPixmap(
                logo_pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        header_layout.addWidget(self.logo_label, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.title_label = QLabel("Power BI Summarizer")
        self.title_label.setProperty("role", "title")
        header_layout.addWidget(self.title_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addStretch()

        self.minimize_btn = QToolButton()
        self.minimize_btn.setText("Min")
        self.minimize_btn.setToolTip("Minimizar")
        self.minimize_btn.setAutoRaise(True)
        self.minimize_btn.setCursor(Qt.PointingHandCursor)
        header_layout.addWidget(self.minimize_btn, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.maximize_btn = QToolButton()
        self.maximize_btn.setText("Max")
        self.maximize_btn.setToolTip("Maximizar")
        self.maximize_btn.setAutoRaise(True)
        self.maximize_btn.setCursor(Qt.PointingHandCursor)
        header_layout.addWidget(self.maximize_btn, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.verticalLayout.addWidget(self.header_widget)

        # Progress bar ----------------------------------------------------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.setFixedHeight(14)
        self.verticalLayout.addWidget(self.progress_bar)

        # Central stacked content ----------------------------------------------
        self.central_frame = QFrame()
        central_layout = QHBoxLayout(self.central_frame)
        central_layout.setContentsMargins(0, 12, 0, 12)
        central_layout.setSpacing(12)

        self.sidebar_container = QFrame()
        self.sidebar_container.setObjectName("sidebarContainer")
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        self.sidebar_container.setMaximumWidth(72)
        self.sidebar_container.setMinimumWidth(64)
        central_layout.addWidget(self.sidebar_container, 0, Qt.AlignTop)

        self.content_frame = QFrame()
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.stackedWidget = QStackedWidget()
        content_layout.addWidget(self.stackedWidget, 1)

        central_layout.addWidget(self.content_frame, 1)

        # Results page ----------------------------------------------------------
        self.pageResultados = QWidget()
        resultados_layout = QVBoxLayout(self.pageResultados)
        resultados_layout.setContentsMargins(0, 0, 0, 0)
        resultados_layout.setSpacing(12)

        self.results_header_frame = QFrame()
        header_layout = QVBoxLayout(self.results_header_frame)
        header_layout.setContentsMargins(16, 16, 16, 8)
        header_layout.setSpacing(10)

        layer_row = QHBoxLayout()
        self.layer_label = QLabel("Camada:")
        layer_row.addWidget(self.layer_label)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        layer_row.addWidget(self.layer_combo, 1)
        header_layout.addLayout(layer_row)

        actions_row = QHBoxLayout()
        self.auto_update_check = QCheckBox("Atualização automática")
        self.auto_update_check.setChecked(True)
        self.auto_update_check.setProperty("role", "helper")
        actions_row.addWidget(self.auto_update_check)
        actions_row.addStretch()
        self.dashboard_btn = QPushButton("Dashboard Interativo")
        self.dashboard_btn.setProperty("variant", "secondary")
        actions_row.addWidget(self.dashboard_btn)
        header_layout.addLayout(actions_row)

        resultados_layout.addWidget(self.results_header_frame)

        self.results_body = QFrame()
        self.results_body.setObjectName("resultsBody")
        self.results_body_layout = QVBoxLayout(self.results_body)
        self.results_body_layout.setContentsMargins(0, 0, 0, 0)
        self.results_body_layout.setSpacing(12)
        resultados_layout.addWidget(self.results_body, 1)

        self.export_card = QFrame()
        self.export_card.setObjectName("exportCard")
        export_layout = QVBoxLayout(self.export_card)
        export_layout.setContentsMargins(16, 16, 16, 16)
        export_layout.setSpacing(12)

        self.export_info_label = QLabel(
            "Configure o formato e o destino para exportar o resumo."
        )
        self.export_info_label.setWordWrap(True)
        self.export_info_label.setProperty("role", "helper")
        export_layout.addWidget(self.export_info_label)

        export_form_layout = QGridLayout()
        export_form_layout.addWidget(QLabel("Formato:"), 0, 0)
        self.export_format_combo = QComboBox()
        export_form_layout.addWidget(self.export_format_combo, 0, 1, 1, 2)

        export_form_layout.addWidget(QLabel("Arquivo de destino:"), 1, 0)
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setPlaceholderText("Selecione o arquivo de destino...")
        export_form_layout.addWidget(self.export_path_edit, 1, 1)
        self.export_browse_btn = QPushButton("Procurar...")
        self.export_browse_btn.setProperty("variant", "secondary")
        export_form_layout.addWidget(self.export_browse_btn, 1, 2)

        export_layout.addLayout(export_form_layout)

        self.export_include_timestamp_check = QCheckBox(
            "Adicionar data e hora ao nome do arquivo"
        )
        self.export_include_timestamp_check.setChecked(True)
        self.export_include_timestamp_check.setProperty("role", "helper")
        export_layout.addWidget(self.export_include_timestamp_check)

        export_button_layout = QHBoxLayout()
        export_button_layout.addStretch()
        self.export_execute_btn = QPushButton("Exportar")
        export_button_layout.addWidget(self.export_execute_btn)
        export_layout.addLayout(export_button_layout)

        resultados_layout.addWidget(self.export_card)

        self.stackedWidget.addWidget(self.pageResultados)

        # Comparison page -------------------------------------------------------
        self.pageComparar = QWidget()
        comparar_layout = QVBoxLayout(self.pageComparar)
        comparar_layout.setContentsMargins(0, 0, 0, 0)
        comparar_layout.setSpacing(12)

        self.compare_card = QFrame()
        self.compare_card.setObjectName("compareCard")
        compare_card_layout = QVBoxLayout(self.compare_card)
        compare_card_layout.setContentsMargins(16, 12, 16, 12)
        compare_card_layout.setSpacing(8)

        self.compare_params_header = QFrame()
        params_header_layout = QHBoxLayout(self.compare_params_header)
        params_header_layout.setContentsMargins(0, 0, 0, 0)
        params_header_layout.setSpacing(6)
        self.compare_params_title = QLabel("Parametros")
        self.compare_params_title.setProperty("role", "helper")
        params_header_layout.addWidget(self.compare_params_title)
        params_header_layout.addStretch()
        self.compare_params_toggle_btn = QPushButton("Parametros >")
        self.compare_params_toggle_btn.setCheckable(True)
        self.compare_params_toggle_btn.setChecked(False)
        self.compare_params_toggle_btn.setFlat(True)
        self.compare_params_toggle_btn.setProperty("variant", "ghost")
        params_header_layout.addWidget(self.compare_params_toggle_btn)
        compare_card_layout.addWidget(self.compare_params_header)

        self.compare_params_container = QWidget()
        params_layout = QVBoxLayout(self.compare_params_container)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(6)

        compare_form_layout = QGridLayout()
        compare_form_layout.setHorizontalSpacing(10)
        compare_form_layout.setVerticalSpacing(6)

        camada_origem_label = QLabel("Camada origem")
        camada_origem_label.setToolTip("Selecione a camada que contém os registros de origem.")
        compare_form_layout.addWidget(camada_origem_label, 0, 0)
        self.compare_source_layer_combo = QgsMapLayerComboBox()
        self.compare_source_layer_combo.setMinimumHeight(26)
        self.compare_source_layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_form_layout.addWidget(self.compare_source_layer_combo, 0, 1)

        camada_alvo_label = QLabel("Camada alvo")
        camada_alvo_label.setToolTip("Selecione a camada que receberá a comparação.")
        compare_form_layout.addWidget(camada_alvo_label, 0, 2)
        self.compare_target_layer_combo = QgsMapLayerComboBox()
        self.compare_target_layer_combo.setMinimumHeight(26)
        self.compare_target_layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_form_layout.addWidget(self.compare_target_layer_combo, 0, 3)

        campo_origem_label = QLabel("Campo origem")
        campo_origem_label.setToolTip("Campo da camada de origem usado como chave.")
        compare_form_layout.addWidget(campo_origem_label, 1, 0)
        self.compare_source_field_combo = QgsFieldComboBox()
        self.compare_source_field_combo.setMinimumHeight(26)
        self.compare_source_field_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_form_layout.addWidget(self.compare_source_field_combo, 1, 1)

        campo_comp_label = QLabel("Campo comparação")
        campo_comp_label.setToolTip("Campo da camada alvo usado para comparar.")
        compare_form_layout.addWidget(campo_comp_label, 1, 2)
        self.compare_target_field_combo = QgsFieldComboBox()
        self.compare_target_field_combo.setMinimumHeight(26)
        self.compare_target_field_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_form_layout.addWidget(self.compare_target_field_combo, 1, 3)

        campo_retorno_label = QLabel("Campo retorno")
        campo_retorno_label.setToolTip("Campo da camada alvo cujo valor será retornado.")
        compare_form_layout.addWidget(campo_retorno_label, 2, 0)
        self.compare_return_field_combo = QgsFieldComboBox()
        self.compare_return_field_combo.setMinimumHeight(26)
        self.compare_return_field_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        compare_form_layout.addWidget(self.compare_return_field_combo, 2, 1)
        compare_form_layout.setColumnStretch(1, 1)
        compare_form_layout.setColumnStretch(3, 1)

        params_layout.addLayout(compare_form_layout)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.compare_execute_btn = QPushButton("Executar comparação")
        buttons_row.addWidget(self.compare_execute_btn)
        self.compare_select_matches_btn = QPushButton("Selecionar feições")
        self.compare_select_matches_btn.setProperty("variant", "secondary")
        buttons_row.addWidget(self.compare_select_matches_btn)
        self.compare_create_layer_btn = QPushButton("Gerar camada temporária")
        self.compare_create_layer_btn.setProperty("variant", "secondary")
        buttons_row.addWidget(self.compare_create_layer_btn)
        self.compare_materialize_btn = QPushButton("Criar camada/tabela")
        self.compare_materialize_btn.setProperty("variant", "secondary")
        buttons_row.addWidget(self.compare_materialize_btn)
        buttons_row.addStretch()

        params_layout.addLayout(buttons_row)

        compare_card_layout.addWidget(self.compare_params_container)
        self.compare_params_container.setVisible(False)

        comparar_layout.addWidget(self.compare_card)

        self.compare_results_frame = QFrame()
        self.compare_results_frame.setObjectName("compareResultsFrame")
        self.compare_results_layout = QVBoxLayout(self.compare_results_frame)
        self.compare_results_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_results_layout.setSpacing(8)
        comparar_layout.addWidget(self.compare_results_frame, 1)

        self.stackedWidget.addWidget(self.pageComparar)

        # Integration page ------------------------------------------------------
        self.pageIntegracao = QWidget()
        integracao_layout = QVBoxLayout(self.pageIntegracao)
        integracao_layout.setContentsMargins(0, 0, 0, 0)
        integracao_layout.setSpacing(12)

        self.integration_placeholder = QLabel(
            "Integrações externas serão exibidas aqui."
        )
        self.integration_placeholder.setAlignment(Qt.AlignCenter)
        self.integration_placeholder.setProperty("role", "helper")

        integracao_layout.addStretch()
        integracao_layout.addWidget(self.integration_placeholder)
        integracao_layout.addStretch()

        self.stackedWidget.addWidget(self.pageIntegracao)

        self.verticalLayout.addWidget(self.central_frame, 1)

        # Footer bar ------------------------------------------------------------
        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(8)

        footer_layout.addStretch()
        self.manage_connections_btn = QPushButton("Gerenciar conexões")
        self.manage_connections_btn.setProperty("variant", "secondary")
        self.manage_connections_btn.setVisible(False)
        footer_layout.addWidget(self.manage_connections_btn)

        self.footer_about_btn = QPushButton("Sobre")
        self.footer_about_btn.setProperty("variant", "secondary")
        footer_layout.addWidget(self.footer_about_btn)

        self.verticalLayout.addWidget(self.footer_bar)

        # Set default page
        self.stackedWidget.setCurrentWidget(self.pageResultados)
