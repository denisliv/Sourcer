# AlfaHRSourcer

HR-приложение для поиска кандидатов из HeadHunter и LinkedIn.

## Стек

- **Backend**: FastAPI, SQLAlchemy (async), Alembic, Playwright
- **Database**: PostgreSQL 16
- **Frontend**: Jinja2 + vanilla JS
- **Deploy**: Docker Compose, Nginx

## База данных

### Таблицы

#### 1. **users** (Пользователи)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Уникальный идентификатор (генерируется БД) |
| `email` | String(255) | Нет | Email для входа (уникальный) |
| `password_hash` | String(255) | bcrypt | Хеш пароля (12 раундов bcrypt) |
| `full_name` | String(255) | Нет | Имя пользователя |
| `is_admin` | Boolean | — | Администратор или нет |
| `must_change_password` | Boolean | — | Требуется смена пароля при первом входе |
| `created_at` | DateTime(TZ) | — | Дата создания записи |
| `updated_at` | DateTime(TZ) | — | Дата обновления записи |

#### 2. **sessions** (Сессии)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор сессии |
| `user_id` | UUID | — | Ссылка на пользователя (CASCADE) |
| `token` | String(255) | Нет | UUID v4, уникальный токен сессии |
| `ip_address` | String(45) | Нет | IP клиента при создании сессии |
| `user_agent` | Text | Нет | User-Agent браузера |
| `created_at` | DateTime(TZ) | — | Дата создания |
| `expires_at` | DateTime(TZ) | — | Дата истечения (обычно +7 дней) |

#### 3. **credentials** (Учётные данные)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор записи |
| `user_id` | UUID | — | Ссылка на пользователя (CASCADE) |
| `provider` | String(20) | Нет | `'hh'` или `'linkedin'` |
| `status` | String(20) | Нет | `'active'` или `'expired'` |
| `encrypted_data` | LargeBinary | AES-256-GCM | Зашифрованные учётные данные |
| `updated_at` | DateTime(TZ) | — | Дата обновления |

**Ограничение:** один credential на `(user_id, provider)`.

**Содержимое `encrypted_data` (после расшифровки):**

- **HH.ru:** `access_token`, `refresh_token`, `expires_at`, `user_agent`
- **LinkedIn:** `username`, `password`, `cookies` (сессионные cookies после headless-login через Playwright)

Шифрование: AES-256-GCM, ключ из `ENCRYPTION_KEY`, формат: 12 байт nonce + ciphertext+tag.

#### 4. **audit_logs** (Журнал аудита)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | BigInteger | — | Идентификатор записи (auto-increment) |
| `user_id` | UUID | — | Кто совершил действие (может быть NULL) |
| `action` | String(50) | Нет | Тип действия |
| `ip_address` | String(45) | Нет | IP при совершении действия |
| `details` | JSONB | Нет | Дополнительные данные события |
| `created_at` | DateTime(TZ) | — | Дата события |

**Типы `action`:** `login`, `logout`, `password_change`, `credential_update`, `credential_delete`, `search`, `export_csv`, `admin_create_user`, `admin_delete_user`.  
**Примеры `details`:** `{"provider": "hh"}`, `{"query": "...", "sources": "both", "results": 42}`.

#### 5. **searches** (Поиски)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор поиска |
| `user_id` | UUID | — | Ссылка на пользователя (CASCADE) |
| `query_text` | String(500) | Нет | Текст поискового запроса |
| `query_params` | JSONB | Нет | Параметры поиска |
| `sources` | String(20) | Нет | Источники: `'hh'`, `'linkedin'` или `'both'` |
| `status` | String(20) | Нет | `'pending'`, `'running'`, `'done'`, `'failed'` |
| `total_results` | Integer | — | Количество найденных кандидатов |
| `error_message` | Text | Нет | Сообщение об ошибке при `failed` |
| `created_at` | DateTime(TZ) | — | Время начала поиска |
| `completed_at` | DateTime(TZ) | — | Время завершения поиска |

**Содержимое `query_params`:** `search_in_positions`, `search_skills`, `exclude_title`, `exclude_company`, `experience`, `area`, `period`, `count`, `sources`.

#### 6. **candidates** (Кандидаты)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор кандидата |
| `search_id` | UUID | — | Ссылка на поиск (CASCADE) |
| `source` | String(20) | Нет | Источник: `'hh'` или `'linkedin'` |
| `external_id` | String(255) | Нет | Внешний ID (HH resume ID или LinkedIn URN) |
| `full_name` | String(255) | Нет | ФИО кандидата |
| `current_title` | String(500) | Нет | Текущая должность |
| `location` | String(255) | Нет | Локация/регион |
| `profile_url` | String(1000) | Нет | Ссылка на профиль |
| `extra_data` | JSONB | Нет | Дополнительные поля |
| `created_at` | DateTime(TZ) | — | Дата добавления |

**Ограничение:** уникальная комбинация `(search_id, source, external_id)`.  
**Содержимое `extra_data`:** `photo`, `experience`, `salary`, `updated_at` (HH) / `fetched_at` (LinkedIn).

### Шифрование

| Данные | Метод | Формат |
|--------|-------|--------|
| Пароль пользователя | bcrypt (12 rounds) | Хеш (необратимый) |
| Токены HH (access, refresh) | AES-256-GCM | Шифрование |
| Логин и пароль LinkedIn | AES-256-GCM | Шифрование |
| Cookies LinkedIn | AES-256-GCM | Шифрование |

Токены сессий, email, параметры поиска, кандидаты и audit_logs хранятся **в открытом виде**; чувствительные данные — только в хешированном или зашифрованном виде.

## Локальная разработка

### Предусловия

- Python 3.11+
- PostgreSQL (можно через Docker, см. ниже)

### Установка

```bash
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### PostgreSQL через Docker (опционально)

```bash
docker run -d --name pg -p 5432:5432 \
  -e POSTGRES_DB=hrservice \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=admin \
  postgres:16-alpine
```

### Конфигурация

Скопируйте `.env.example` или создайте `.env` в корне проекта:

```env
DATABASE_URL=postgresql+asyncpg://admin:admin@localhost:5432/hrservice
ENCRYPTION_KEY=<random-64-hex-chars>
SECRET_KEY=<random-secret-string>

HH_APP_CLIENT_ID=<your-hh-client-id>
HH_APP_CLIENT_SECRET=<your-hh-client-secret>
HH_USER_AGENT=YourApp (contact@email.com)
HH_REDIRECT_URI=http://localhost:8000/api/account/hh/callback
```

### Запуск

```bash
# Применить миграции
python -m alembic upgrade head

# Создать admin-пользователя
python create_admin.py admin@example.com password123 "Admin Name"

# Запустить сервер (с hot reload)
python -m app
```

Приложение: http://localhost:8000

### Тесты

```bash
python -m pytest tests/ -v
```

## Production (Docker Compose)

### Запуск

```bash
# Настроить .env (см. раздел "Конфигурация")
# HH_REDIRECT_URI должен указывать на реальный домен

docker compose up -d --build

# Создать admin-пользователя
docker compose exec backend python create_admin.py admin@example.com password123 "Admin Name"
```

Приложение: http://localhost:3000

### Архитектура контейнеров

| Контейнер  | Порт | Описание                              |
|------------|------|---------------------------------------|
| `postgres` | 5432 | PostgreSQL 16                         |
| `backend`  | 8000 | FastAPI + миграции при старте         |
| `frontend` | 3000 | Nginx (статика + проксирование API)   |

Миграции запускаются автоматически при старте `backend`.

### Остановка

```bash
docker compose down        # остановить
docker compose down -v     # остановить и удалить данные БД
```
