# CI/CD и деплой

## Что делает workflow

`.github/workflows/ci-cd.yml` запускается на `push` и `pull_request` в `main`, а также вручную через `workflow_dispatch`.

Порядок:

- `checks` ставит зависимости, выполняет `python -m compileall mcp_server.py app` и `python -m pytest -q`.
- `deploy` запускается только после успешных проверок, только для `push` в `main`, и только если в GitHub задана переменная `POE2_DEPLOY_ENABLED=true`.
- Деплой идет по SSH и выполняет `scripts/deploy_server.sh` на сервере.

Отдельная VM под self-hosted runner не обязательна для первого этапа. Ее стоит поднимать, если сервер закрыт для SSH из GitHub Actions, если нужны локальные сетевые ресурсы Proxmox/VPN или если деплой должен выполняться полностью внутри своей инфраструктуры.

## GitHub secrets

Для включения деплоя нужны repository secrets:

- `POE2_DEPLOY_HOST` - адрес сервера.
- `POE2_DEPLOY_USER` - SSH-пользователь для деплоя.
- `POE2_DEPLOY_SSH_KEY` - приватный ключ этого пользователя.
- `POE2_DEPLOY_KNOWN_HOSTS` - строка из `known_hosts` для сервера.

Repository variables:

- `POE2_DEPLOY_ENABLED=true` - включает deploy job.
- `POE2_DEPLOY_PORT` - SSH-порт, по умолчанию `22`.
- `POE2_DEPLOY_APP_DIR` - путь к checkout на сервере, по умолчанию `/srv/poe2tradehelper/repo`.
- `POE2_DEPLOY_SERVICE` - systemd unit, по умолчанию `poe2tradehelper.service`. Значение `none` пропускает restart.
- `POE2_DEPLOY_HEALTH_URL` - необязательный URL health-check после рестарта.

## Ожидаемый серверный запуск

Скрипт деплоя ожидает, что на сервере есть `git`, `python3`, `python3-venv`, `pip`, `curl` и systemd service для приложения.

Пример unit-файла:

```ini
[Unit]
Description=PoE2 Trade Helper
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/srv/poe2tradehelper/repo
EnvironmentFile=-/srv/poe2tradehelper/.env
Environment=DATA_DIR=/srv/poe2tradehelper/state/data
Environment=STORAGE_DIR=/srv/poe2tradehelper/state/storage
Environment=SQLITE_PATH=/srv/poe2tradehelper/state/data/poe2_ninja.sqlite
ExecStart=/srv/poe2tradehelper/repo/.venv/bin/python -m app.cli run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`.env` с секретами остается на сервере и не хранится в git.
