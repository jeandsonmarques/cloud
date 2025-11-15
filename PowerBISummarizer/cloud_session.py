from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QDateTime, QSettings, Qt, pyqtSignal

try:  # pragma: no cover - QGIS ships requests by default
    import requests
    from requests import RequestException
except ImportError:  # pragma: no cover - fallback when requests isn't available
    requests = None  # type: ignore

    class RequestException(Exception):
        """Fallback exception used when requests is missing."""
        pass


_HERE = os.path.dirname(__file__)
_CLOUD_SAMPLES_DIR = os.path.join(_HERE, "resources", "cloud_samples")
REQUEST_TIMEOUT = 15
ACTIVE_CONNECTION_KEY = "PowerBISummarizer/cloud/active_connection"


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

    def _build_url(self, endpoint: Optional[str]) -> str:
        endpoint = (endpoint or "").strip()
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        base_url = (self._config.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("Configure a Base URL valida nas configuracoes do Cloud.")
        if not endpoint:
            raise ValueError("Endpoint Cloud invalido.")
        base_url = base_url.rstrip("/")
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"{base_url}{endpoint}"

    def _request_json(
        self,
        method: str,
        endpoint: Optional[str],
        *,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        url = self._build_url(endpoint or "")
        try:
            response = requests.request(
                method.upper(),
                url,
                json=payload,
                headers=headers or {},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise RuntimeError(f"Falha ao conectar ao PowerBI Cloud ({url}): {exc}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Resposta invalida recebida do PowerBI Cloud.") from exc

    def _remote_login(self, username: str, password: str) -> Dict:
        payload = {"email": username, "password": password}
        data = self._request_json("POST", self._config.get("login_endpoint"), payload=payload)
        token = data.get("access_token")
        if not token:
            raise RuntimeError("A API nao retornou um token de acesso.")
        issued = QDateTime.currentDateTimeUtc()
        session = {
            "username": username,
            "token": token,
            "issued": issued.toString(Qt.ISODate),
            "mode": "remote",
            "token_type": (data.get("token_type") or "bearer").lower(),
        }
        expires_in = int(data.get("expires_in") or 0)
        if expires_in > 0:
            session["expires_in"] = expires_in
            session["expires_at"] = issued.addSecs(expires_in).toString(Qt.ISODate)
        return session

    def _mock_login(self, username: str) -> Dict:
        seed = f"{username}:{uuid.uuid4().hex}"
        token = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        issued = QDateTime.currentDateTime().toString(Qt.ISODate)
        return {
            "username": username,
            "token": token[:48],
            "issued": issued,
            "mode": "mock",
        }

    def _auth_headers(self) -> Dict[str, str]:
        token = self._session.get("token")
        if not token:
            raise RuntimeError("Sessao Cloud nao autenticada.")
        token_type = (self._session.get("token_type") or "bearer").lower()
        prefix = "Bearer" if token_type == "bearer" else token_type.capitalize()
        return {"Authorization": f"{prefix} {token}"}

    def create_cloud_user(self, *, email: str, password: str) -> Tuple[int, Dict]:
        """Dispara POST /api/v1/admin/create-user reaproveitando a configuracao atual."""
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        # Chamada direta para /api/v1/admin/create-user usando o token atual.
        url = self._build_url("/api/v1/admin/create-user")
        headers = dict(self._auth_headers())
        headers.setdefault("Content-Type", "application/json")
        payload = {"email": email, "password": password}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        except RequestException as exc:
            raise RuntimeError(f"Falha ao conectar ao PowerBI Cloud ({url}): {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data

    def _should_use_remote_layers(self) -> bool:
        if not self.hosting_ready():
            return False
        if self._session.get("mode") != "remote":
            return False
        return self.is_authenticated()

    def _fetch_remote_layers(self) -> List[Dict]:
        payload = self._request_json("GET", self._config.get("layers_endpoint"), headers=self._auth_headers())
        if not isinstance(payload, list):
            raise RuntimeError("Resposta invalida do endpoint de camadas.")
        layers: List[Dict] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            schema_name = item.get("schema") or item.get("schema_name") or "public"
            name = item.get("name") or f"camada_{item.get('id') or uuid.uuid4().hex[:4]}"
            srid = item.get("srid")
            layer = CloudLayer(
                id=str(item.get("id") or name),
                name=name,
                description=f"Schema {schema_name} / SRID {srid or '-'}",
                source=f"cloud://{schema_name}.{name}",
                geometry=str(item.get("geom_type") or ""),
                provider="postgres",
                mock_only=False,
                tags=["cloud", schema_name],
            ).as_dict()
            layer["schema"] = schema_name
            if srid:
                layer["srid"] = srid
            layers.append(layer)
        connection = {
            "id": "powerbi_cloud_remote",
            "name": "PowerBI Cloud",
            "status": "online" if layers else "offline",
            "description": (
                "Camadas disponibilizadas pelo banco configurado."
                if layers
                else "Nenhuma camada retornada pela API."
            ),
            "layers": layers,
            "mock_only": False,
        }
        return [connection]

    # ------------------------------------------------------------------ Public API
    def is_authenticated(self) -> bool:
        token = self._session.get("token")
        if not token:
            return False
        expires_at = self._session.get("expires_at")
        if expires_at:
            expiry = QDateTime.fromString(expires_at, Qt.ISODate)
            if expiry.isValid() and expiry < QDateTime.currentDateTimeUtc():
                return False
        return True

    def session(self) -> Dict:
        return dict(self._session)

    def config(self) -> Dict:
        return dict(self._config)

    def cloud_connections(self) -> List[Dict]:
        return [dict(item) for item in self._connections]

    def login(self, username: str, password: str) -> Dict:
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("Usuario e senha sao obrigatorios.")
        if self.hosting_ready():
            session = self._remote_login(username, password)
        else:
            session = self._mock_login(username)
        self._session = dict(session)
        self._persist_session()
        mode = self._session.get("mode") or "mock"
        if mode == "remote":
            print(f"[PowerBI Cloud] Sessao remota autenticada para {username}.")
        else:
            print(f"[PowerBI Cloud] Sessao mock autenticada para {username}.")
        self.sessionChanged.emit(dict(self._session))
        self.reload_mock_layers()
        return dict(self._session)

    def logout(self):
        if not self._session:
            return
        username = self._session.get("username") or "usuario"
        self._session = {}
        self._persist_session()
        self.reload_mock_layers()
        print(f"[PowerBI Cloud] Sessao encerrada para {username}.")
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
        try:
            if self._should_use_remote_layers():
                self._connections = self._fetch_remote_layers()
                print("[PowerBI Cloud] Catalogo remoto atualizado.")
            else:
                self._connections = self._load_mock_connections()
                print("[PowerBI Cloud] Catalogo mock atualizado.")
        except Exception as exc:  # pragma: no cover - runtime safeguard
            print(f"[PowerBI Cloud] Falha ao atualizar catalogo remoto: {exc}. Voltando ao mock.")
            self._connections = self._load_mock_connections()
        self.layersChanged.emit(self.cloud_connections())

    def hosting_ready(self) -> bool:
        return bool(self._config.get("hosting_ready"))

    def status_payload(self) -> Dict:
        if not self.is_authenticated():
            return {"text": "Desconectado", "level": "offline"}
        username = self._session.get("username", "")
        issued = self._session.get("issued", "")
        mode = self._session.get("mode") or "mock"
        if mode == "remote":
            text = f"Cloud conectado como {username}"
            level = "online"
        else:
            text = f"Modo demo ativo ({username})"
            level = "sync"
        return {"text": text, "level": level, "issued": issued}

    def active_connection_fingerprint(self) -> str:
        """Retorna o fingerprint da conexao marcada como atual para o Cloud."""
        value = self._settings.value(ACTIVE_CONNECTION_KEY, "")
        return str(value) if value else ""

    def set_active_connection_fingerprint(self, fingerprint: Optional[str]):
        """Atualiza a conexao atual usada para preencher o login padrão."""
        if fingerprint:
            self._settings.setValue(ACTIVE_CONNECTION_KEY, fingerprint)
        else:
            self._settings.remove(ACTIVE_CONNECTION_KEY)


cloud_session = PowerBICloudSession()

__all__ = ["cloud_session", "PowerBICloudSession"]
