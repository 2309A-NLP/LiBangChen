# Milvus + Attu

## Start

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start-milvus.ps1
```

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\stop-milvus.ps1
```

## Endpoints

- Milvus gRPC: `localhost:19530`
- Milvus health: `http://localhost:9091/healthz`
- MinIO console: `http://localhost:9001`
- Attu UI: `http://localhost:8001`

## Attu Connection

- Address: `localhost:19530`
- Database: leave empty unless you set `MILVUS_DB_NAME`
- Token/User/Password: leave empty unless you enabled auth

## Notes

- This project uses `docker-compose.milvus.yml`.
- If startup fails with Docker daemon errors, start Docker Desktop first.
- If WSL is blocked on this machine, Docker Desktop must expose a working Windows daemon.
