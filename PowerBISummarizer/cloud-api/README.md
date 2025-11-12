# Power BI Summarizer Cloud API

API em FastAPI com autenticacao JWT e PostgreSQL para expor login, dados do usuario autenticado e catalogo de camadas georreferenciadas. Pensada para deploy no Railway com o comando `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Estrutura
```
cloud-api/
|-- app/
|   |-- auth.py        # utilitarios de JWT/bcrypt e dependencias de auth
|   |-- db.py          # conexao SQLAlchemy com PostgreSQL
|   |-- main.py        # FastAPI + rotas /api/v1
|   |-- models.py      # ORM (users, layers)
|   |-- schemas.py     # Pydantic (login/token/user/layer)
|   `-- seed.sql       # criacao e carga inicial (admin + 3 camadas)
|-- Dockerfile
`-- requirements.txt
```

## Variaveis de ambiente
Defina no Railway (ou `.env` local) os valores fornecidos:

| Variavel | Descricao |
| --- | --- |
| `DATABASE_URL` | URL completa do Postgres (ex.: `postgresql://...`) |
| `JWT_SECRET` | Segredo para assinar tokens JWT |
| `JWT_EXPIRES` | Expiracao em segundos (ex.: `3600`) |
| `API_BASEPATH` | Prefixo dos endpoints (padrao `/api/v1`) |
| `CORS_ALLOW_ORIGINS` | Lista separada por virgula de origens permitidas (opcional) |

> Em producao (Railway) usamos `psycopg2-binary`. Se preferir `psycopg2` normal, sera preciso instalar `libpq-dev` e compiladores no container.

## Execucao local
```bash
cd cloud-api
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
A documentacao interativa ficara em `http://localhost:8000/api/v1/docs`.

## Docker / Railway
1. Faca push do diretorio `cloud-api` para o repositorio https://github.com/jeandsonmarques/cloud.git.
2. No Railway, crie um novo servico a partir do repositorio, selecione `cloud-api` como *Root Directory* (sem incluir o nome do repositorio no caminho) e mantenha o comando padrao do Dockerfile.
3. Configure as variaveis em *Settings -> Variables* com: `DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRES=3600` e `API_BASEPATH=/api/v1` (demais variaveis conforme necessidade).
4. Railway fornecera a URL final (`https://<app>.up.railway.app`). Os endpoints ficarao disponiveis em `https://<app>.up.railway.app/api/v1/*`.

## Seed do banco
O arquivo `app/seed.sql` cria as tabelas e popula:
- Usuario: `admin@demo.dev` / senha `demo123` (bcrypt via `pgcrypto`).
- Camadas: `redes_esgoto`, `pocos_bombeamento`, `bairros`.

Rodar no Railway (ou local com psql):
```bash
psql "$DATABASE_URL" -f app/seed.sql
```
> O script habilita `pgcrypto` automaticamente para usar `crypt('demo123', gen_salt('bf'))`.

## Testes rapidos com curl
Autenticar:
```bash
curl -X POST "$BASE_URL/api/v1/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.dev","password":"demo123"}'
```
Resposta esperada:
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```
Usar o token:
```bash
curl "$BASE_URL/api/v1/me" -H "Authorization: Bearer <jwt>"
curl "$BASE_URL/api/v1/layers" -H "Authorization: Bearer <jwt>"
```
Retorno de `/layers`:
```json
[
  {"id":1,"name":"redes_esgoto","schema":"public","srid":31984,"geom_type":"LINESTRING"},
  {"id":2,"name":"pocos_bombeamento","schema":"public","srid":31984,"geom_type":"POINT"},
  {"id":3,"name":"bairros","schema":"public","srid":31984,"geom_type":"MULTIPOLYGON"}
]
```

## Proximos passos sugeridos
- Ajustar politicas de CORS (`CORS_ALLOW_ORIGINS`).
- Adicionar mais camadas/tabelas conforme necessidade do Power BI.
- Criar testes automatizados (pytest) se desejar evoluir a API.
