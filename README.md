# Zenkai

Модульный Telegram userbot.

## Быстрый запуск

```bash
git clone https://github.com/elisartix/Zenkai
cd Zenkai
python3 -m Zenkai
```

Лаунчер сам создаст локальное окружение `.venv`, установит зависимости из `requirements.txt` и запустит веб-панель авторизации.

Если виртуальное окружение на сервере недоступно, Zenkai попробует поставить зависимости текущим Python.

## Web Tunnel

В Telegram используй:

```text
.web
```

Zenkai сам скачает/обновит `cloudflared`, поднимет временный Cloudflare Quick Tunnel без авторизации и пришлёт публичную ссылку на веб-панель.

Дополнительно:

```text
.web restart
.web stop
```
