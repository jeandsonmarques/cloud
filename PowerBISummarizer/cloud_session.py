from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QObject, QDateTime, QSettings, Qt, pyqtSignal


_HERE = os.path.dirname(__file__)
_CLOUD_SAMPLES_DIR = os.path.join(_HERE, "resources", "cloud_samples")


@dataclass
class CloudLayer:
    """Small descriptor used by the browser/provider mock."""

    id: str
    name: str
    description: str
    source: str
    geometry: str = ""
    provider: str = "ogr"
    tags: Optional[List[str]] = None
    mock_only: bool = True

    def as_dict(self) -> Dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "geometry": self.geometry,
            "provider": self.provider,
            "mock_only": self.mock_only,
        }
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


class PowerBICloudSession(QObject):
    """Keeps track of the fake Cloud session, config and layer catalog."""

    sessionChanged = pyqtSignal(dict)
    configChanged = pyqtSignal(dict)
    layersChanged = pyqtSignal(list)

    SESSION_KEY = "PowerBISummarizer/cloud/session"
    CONFIG_KEY = "PowerBISummarizer/cloud/config"

    def __init__(self):
        super().__init__()
        self._settings = QSettings()
        self._session = self._load_session()
        self._config = self._load_config()
        self._connections = self._load_mock_connections()

    # ------------------------------------------------------------------ Internal helpers
    def _session_path(self) -> str:
        return os.path.join(_CLOUD_SAMPLES_DIR, "mock_layers.json")

    def _load_session(self) -> Dict:
        raw = self._settings.value(self.SESSION_KEY, "")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("token"):
                return payload
        except Exception:
            pass
        return {}

    def _persist_session(self):
        if self._session:
            self._settings.setValue(self.SESSION_KEY, json.dumps(self._session))
        else:
            self._settings.remove(self.SESSION_KEY)

    def _default_config(self) -> Dict:
        return {
            "base_url": "https://cloud.powerbisummarizer.dev",
            "login_endpoint": "/api/v1/login",
            "layers_endpoint": "/api/v1/layers",
            "hosting_ready": False,
        }

    def _load_config(self) -> Dict:
        raw = self._settings.value(self.CONFIG_KEY, "")
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    merged = self._default_config()
                    merged.update(payload)
                    return merged
            except Exception:
                pass
        return self._default_config()

    def _persist_config(self):
        self._settings.setValue(self.CONFIG_KEY, json.dumps(self._config))

    def _load_mock_connections(self) -> List[Dict]:
        path = self._session_path()
        try:
            with open(path, "r", encoding="utf-8") as handler:
                payload = json.load(handler)
        except Exception as exc:
            print(f"[PowerBI Cloud] Falha ao carregar mock_layers.json: {exc}")
            payload = {}
        connections = payload.get("connections") if isinstance(payload, dict) else None
        if not isinstance(connections, list):
            connections = self._default_mock_connections()
        sanitized: List[Dict] = []
        for conn in connections:
            sanitized.append(self._sanitize_connection(conn))
        return sanitized

    def _default_mock_connections(self) -> List[Dict]:
        mock_layers_path = os.path.join(_HERE, "resources", "mock_cloud_layers")
        clientes = os.path.join(mock_layers_path, "clientes_sp.geojson")
        infra = os.path.join(mock_layers_path, "infra_linhas.geojson")
        return [
            {
                "id": "mock_corporativo",
                "name": "Painel corporativo (mock)",
                "description": "Coleção de camadas locais para testes.",
                "status": "online",
                "layers": [
                    CloudLayer(
                        id="clientes_sp",
                        name="Clientes SP (mock)",
                        description="Clientes georreferenciados em São Paulo.",
                        source=clientes,
                        geometry="Point",
                        tags=["clientes", "mock"],
                    ).as_dict(),
                    CloudLayer(
                        id="infra_linhas",
                        name="Linhas de infraestrutura (mock)",
                        description="Trechos de rede em teste.",
                        source=infra,
                        geometry="LineString",
                        tags=["infra"],
                    ).as_dict(),
                ],
            }
        ]

    def _sanitize_connection(self, raw: Dict) -> Dict:
        raw = dict(raw or {})
        raw.setdefault("id", f"conn_{uuid.uuid4().hex[:8]}")
        raw.setdefault("name", "Conexão sem nome")
        raw.setdefault("status", "offline")
        raw.setdefault("description", "")
        layers = []
        for item in raw.get("layers", []):
            sanitized = dict(item or {})
            rel_source = sanitized.get("source") or ""
            abs_source = rel_source
            if rel_source and not os.path.isabs(rel_source):
                abs_source = os.path.join(_HERE, rel_source.replace("/", os.sep))
            sanitized["source"] = abs_source
            sanitized.setdefault("provider", "ogr")
            sanitized.setdefault("geometry", "")
            sanitized.setdefault("description", sanitized.get("name", "Camada"))
            sanitized["mock_only"] = sanitized.get("mock_only", True)
            layers.append(sanitized)
        raw["layers"] = layers
        return raw

    # ------------------------------------------------------------------ Public API
    def is_authenticated(self) -> bool:
        return bool(self._session.get("token"))

    def session(self) -> Dict:
        return dict(self._session)

    def config(self) -> Dict:
        return dict(self._config)

    def cloud_connections(self) -> List[Dict]:
        return [dict(item) for item in self._connections]

    def login(self, username: str, password: str) -> Dict:
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("Usuário e senha são obrigatórios.")
        seed = f"{username}:{uuid.uuid4().hex}"
        token = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        issued = QDateTime.currentDateTime().toString(Qt.ISODate)
        self._session = {
            "username": username,
            "token": token[:48],
            "issued": issued,
        }
        self._persist_session()
        print(f"[PowerBI Cloud] Sessão autenticada para {username}.")
        self.sessionChanged.emit(dict(self._session))
        self.reload_mock_layers()
        return dict(self._session)

    def logout(self):
        if not self._session:
            return
        username = self._session.get("username") or "usuário"
        self._session = {}
        self._persist_session()
        print(f"[PowerBI Cloud] Sessão encerrada para {username}.")
        self.sessionChanged.emit({})

    def update_config(
        self,
        *,
        base_url: Optional[str] = None,
        login_endpoint: Optional[str] = None,
        layers_endpoint: Optional[str] = None,
        hosting_ready: Optional[bool] = None,
    ):
        updated = False
        if base_url is not None and base_url != self._config.get("base_url"):
            self._config["base_url"] = base_url.strip()
            updated = True
        if login_endpoint is not None and login_endpoint != self._config.get("login_endpoint"):
            self._config["login_endpoint"] = login_endpoint.strip()
            updated = True
        if layers_endpoint is not None and layers_endpoint != self._config.get("layers_endpoint"):
            self._config["layers_endpoint"] = layers_endpoint.strip()
            updated = True
        if hosting_ready is not None and bool(hosting_ready) != bool(self._config.get("hosting_ready")):
            self._config["hosting_ready"] = bool(hosting_ready)
            updated = True
        if updated:
            self._persist_config()
            print("[PowerBI Cloud] Configurações atualizadas.")
            self.configChanged.emit(dict(self._config))

    def reload_mock_layers(self):
        self._connections = self._load_mock_connections()
        print("[PowerBI Cloud] Catálogo mock atualizado.")
        self.layersChanged.emit(self.cloud_connections())

    def hosting_ready(self) -> bool:
        return bool(self._config.get("hosting_ready"))

    def status_payload(self) -> Dict:
        if not self.is_authenticated():
            return {"text": "Desconectado", "level": "offline"}
        username = self._session.get("username", "")
        issued = self._session.get("issued", "")
        return {
            "text": f"Conectado como {username}",
            "level": "online",
            "issued": issued,
        }


cloud_session = PowerBICloudSession()

__all__ = ["cloud_session", "PowerBICloudSession"]
