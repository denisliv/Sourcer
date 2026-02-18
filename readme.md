# AlfaHRService

HR-сервис Альфа-Банка. Включает три модуля:

- **AlfaHRSourcer** — поиск кандидатов в HeadHunter и LinkedIn
- **AlfaHRBenchmark** — анализ рынка вакансий и бенчмаркинг зарплат
- **AlfaHRAssistent** — интеллектуальный HR-ассистент на базе LLM

## Стек

- **Backend**: FastAPI, SQLAlchemy (async), Alembic, Playwright, OpenAI API
- **Database**: PostgreSQL 16
- **Frontend**: Jinja2 + vanilla JS + Chart.js (графики Benchmark)
- **LLM**: OpenAI-совместимый API (gpt-4o-mini по умолчанию)
- **Deploy**: Docker Compose, Nginx

## Сервисы

### AlfaHRSourcer

Поиск кандидатов по базе резюме HeadHunter и LinkedIn. Поддерживает фильтрацию по навыкам, опыту, региону, исключение по названию/компании. Результаты сохраняются в БД с историей поиска и экспортом в CSV.

**Доступ:** требуется авторизация + личные credentials HH/LinkedIn.

### AlfaHRBenchmark

Анализ рынка вакансий с зарплатными данными. Получает вакансии из HH API (по вакансиям, не резюме), конвертирует зарплаты в BYN через API Belarusbank, фильтрует выбросы методом IQR, рассчитывает статистику (min/max/mean/median). Поддерживает интерактивную гистограмму распределения зарплат и экспорт в Excel.

**Возможности:**
- Поиск вакансий по ключевым словам с исключающими фильтрами
- Регионы: Беларусь, Москва, Санкт-Петербург, все вместе
- Фильтрация по опыту работы и периоду публикации (1–365 дней)
- Автоматическая конвертация валют (USD, EUR, RUR и др.) в BYN
- Конвертация Gross ↔ Net (НДФЛ 14%)
- Фильтрация выбросов: минимальный порог 500 BYN + метод IQR (Tukey)
- Гистограмма распределения зарплат (Chart.js)
- Экспорт в Excel (.xlsx)

**Доступ:** все авторизованные пользователи (без дополнительных credentials).

### AlfaHRAssistent

Интеллектуальный HR-ассистент на базе LLM (OpenAI-совместимый API). Работает в формате чата с поддержкой истории диалогов. Помогает HR-специалистам в повседневных задачах.

**Возможности:**
- Составление описаний вакансий
- Подготовка вопросов для интервью
- Консультации по трудовому законодательству
- Помощь в адаптации новых сотрудников
- Разработка HR-политик и процедур
- Анализ резюме и подготовка отчётов

**Функционал чата:**
- Создание, переименование и удаление чатов
- Поддержание истории сообщений в рамках одного чата
- Хранение всех чатов пользователя с возможностью продолжения диалога
- Стриминг ответов (SSE) — ответ отображается посимвольно в реальном времени
- Автоматическая генерация названия чата по первому сообщению
- Рендеринг Markdown (заголовки, списки, код, bold/italic)
- Разделение данных по пользователям

**Доступ:** все авторизованные пользователи (без дополнительных credentials).

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

**Типы `action`:** `login`, `logout`, `password_change`, `credential_update`, `credential_delete`, `search`, `export_csv`, `admin_create_user`, `admin_delete_user`, `benchmark_search`.  
**Примеры `details`:** `{"provider": "hh"}`, `{"query": "...", "sources": "both", "results": 42}`, `{"query": "python developer", "total": 150, "filtered": 120}`.

#### 5. **searches** (Поиски — AlfaHRSourcer)

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

#### 7. **benchmark_searches** (Поиски — AlfaHRBenchmark)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор поиска |
| `user_id` | UUID | — | Ссылка на пользователя (CASCADE) |
| `query_text` | String(500) | Нет | Название вакансии (поисковый запрос) |
| `query_params` | JSONB | Нет | Параметры поиска (exclude, area, experience, period) |
| `total_vacancies` | Integer | — | Количество вакансий до фильтрации |
| `filtered_count` | Integer | — | Количество вакансий после фильтрации выбросов |
| `stat_min` | Float | — | Минимальная ЗП (gross, BYN) |
| `stat_max` | Float | — | Максимальная ЗП (gross, BYN) |
| `stat_mean` | Float | — | Средняя ЗП (gross, BYN) |
| `stat_median` | Float | — | Медиана ЗП (gross, BYN) |
| `status` | String(20) | Нет | Статус: `'completed'` |
| `error_message` | Text | Нет | Сообщение об ошибке |
| `created_at` | DateTime(TZ) | — | Время поиска |

**Индекс:** `ix_benchmark_searches_user_id` по `user_id`.  
**Содержимое `query_params`:** `{"exclude": "...", "area": "16", "experience": "between1And3", "period": 30}`.

#### 8. **assistant_chats** (Чаты — AlfaHRAssistent)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор чата |
| `user_id` | UUID | — | Ссылка на пользователя (CASCADE) |
| `title` | String(255) | Нет | Название чата (автогенерация или ручное) |
| `created_at` | DateTime(TZ) | — | Дата создания чата |
| `updated_at` | DateTime(TZ) | — | Дата последнего сообщения |

**Индекс:** `ix_assistant_chats_user_id` по `user_id`.

#### 9. **assistant_messages** (Сообщения — AlfaHRAssistent)

| Столбец | Тип | Шифрование | Содержимое и назначение |
|---------|-----|------------|--------------------------|
| `id` | UUID | — | Идентификатор сообщения |
| `chat_id` | UUID | — | Ссылка на чат (CASCADE) |
| `role` | String(20) | Нет | Роль: `'user'` или `'assistant'` |
| `content` | Text | Нет | Текст сообщения |
| `created_at` | DateTime(TZ) | — | Дата отправки |

**Индекс:** `ix_assistant_messages_chat_id` по `chat_id`.

### Шифрование

| Данные | Метод | Формат |
|--------|-------|--------|
| Пароль пользователя | bcrypt (12 rounds) | Хеш (необратимый) |
| Токены HH (access, refresh) | AES-256-GCM | Шифрование |
| Логин и пароль LinkedIn | AES-256-GCM | Шифрование |
| Cookies LinkedIn | AES-256-GCM | Шифрование |

Токены сессий, email, параметры поиска, кандидаты, benchmark-статистика и audit_logs хранятся **в открытом виде**; чувствительные данные — только в хешированном или зашифрованном виде.

## API

### Аутентификация

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/auth/login` | Вход (email + password) |
| POST | `/api/auth/logout` | Выход |
| GET | `/api/auth/me` | Текущий пользователь |

### AlfaHRSourcer

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/search` | Поиск кандидатов (HH/LinkedIn) |
| GET | `/api/search/history` | История поисков |
| GET | `/api/search/{id}` | Метаданные поиска |
| GET | `/api/search/{id}/results` | Результаты поиска |
| GET | `/api/export` | Экспорт CSV |

### AlfaHRBenchmark

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/benchmark/search` | Поиск вакансий + статистика ЗП |
| POST | `/api/benchmark/export-excel` | Экспорт в Excel (.xlsx) |
| GET | `/api/benchmark/rates` | Текущие курсы валют |

### AlfaHRAssistent

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/assistant/chats` | Список чатов пользователя |
| POST | `/api/assistant/chats` | Создать новый чат |
| PATCH | `/api/assistant/chats/{id}` | Переименовать чат |
| DELETE | `/api/assistant/chats/{id}` | Удалить чат |
| GET | `/api/assistant/chats/{id}/messages` | Сообщения чата |
| POST | `/api/assistant/chats/{id}/messages` | Отправить сообщение (SSE-стрим ответа) |

### Управление аккаунтом

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/account/status` | Статус credentials |
| POST | `/api/account/password` | Смена пароля |
| GET | `/api/account/hh/authorize` | HH OAuth редирект |
| GET | `/api/account/hh/callback` | HH OAuth callback |
| POST | `/api/account/credentials/linkedin` | Сохранить LinkedIn credentials |
| DELETE | `/api/account/credentials/hh` | Удалить HH credentials |
| DELETE | `/api/account/credentials/linkedin` | Удалить LinkedIn credentials |

### Администрирование

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/admin/users` | Создать пользователя |
| GET | `/api/admin/users` | Список пользователей |
| DELETE | `/api/admin/users/{id}` | Удалить пользователя |

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

Создайте `.env` в корне проекта:

```env
DATABASE_URL=postgresql+asyncpg://admin:admin@localhost:5432/hrservice
ENCRYPTION_KEY=<random-64-hex-chars>
SECRET_KEY=<random-secret-string>

# HH OAuth (для AlfaHRSourcer — поиск по резюме)
HH_APP_CLIENT_ID=<your-hh-client-id>
HH_APP_CLIENT_SECRET=<your-hh-client-secret>
HH_USER_AGENT=YourApp (contact@email.com)
HH_REDIRECT_URI=http://localhost:8000/api/account/hh/callback

# HH App Token (для AlfaHRBenchmark — поиск по вакансиям)
HH_APP_TOKEN=<your-hh-app-token>

# OpenAI-совместимый API (для AlfaHRAssistent)
OPENAI_API_KEY=<your-api-key>
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

**Различие токенов HH:**
- `HH_APP_CLIENT_ID` / `HH_APP_CLIENT_SECRET` — OAuth2 для доступа к резюме (требует авторизацию пользователя)
- `HH_APP_TOKEN` — токен приложения для публичного API вакансий (не требует авторизацию пользователя)
- `OPENAI_API_KEY` — ключ доступа к OpenAI-совместимому API
- `OPENAI_API_BASE` — базовый URL API (для прокси или самохостинга можно заменить)
- `OPENAI_MODEL` — модель LLM (по умолчанию `gpt-4o-mini`)

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

Тесты используют SQLite (in-memory) и не требуют PostgreSQL.

## Production (Docker Compose)

### Запуск

```bash
# Настроить .env (см. раздел "Конфигурация")
# HH_REDIRECT_URI должен указывать на реальный домен

docker compose up -d --build

# Создать admin-пользователя
docker compose exec backend python create_admin.py admin@example.com password123 "Admin Name"
```

Приложение: http://localhost:80 (Nginx)

### Архитектура контейнеров

| Контейнер  | Порт | Описание                              |
|------------|------|---------------------------------------|
| `postgres` | 5432 | PostgreSQL 16                         |
| `backend`  | 8000 | FastAPI + миграции при старте         |
| `frontend` | 80   | Nginx (статика + проксирование API)   |

Миграции запускаются автоматически при старте `backend`.

### Остановка

```bash
docker compose down        # остановить
docker compose down -v     # остановить и удалить данные БД
```

## Структура проекта

```
├── app/
│   ├── api/
│   │   ├── auth.py              # Аутентификация
│   │   ├── account.py           # Управление аккаунтом
│   │   ├── admin.py             # Администрирование
│   │   ├── search.py            # AlfaHRSourcer API
│   │   ├── benchmark.py         # AlfaHRBenchmark API
│   │   ├── assistant.py         # AlfaHRAssistent API
│   │   └── dependencies.py      # Auth dependencies
│   ├── core/
│   │   ├── config.py            # Конфигурация
│   │   ├── database.py          # SQLAlchemy async
│   │   └── security.py          # Пароли + шифрование
│   ├── models/
│   │   ├── user.py              # Пользователи
│   │   ├── session.py           # Сессии
│   │   ├── credential.py        # Credentials (HH/LinkedIn)
│   │   ├── audit_log.py         # Журнал аудита
│   │   ├── search.py            # Поиски (Sourcer)
│   │   ├── candidate.py         # Кандидаты (Sourcer)
│   │   ├── benchmark.py         # Поиски (Benchmark)
│   │   └── assistant.py         # Чаты и сообщения (Assistent)
│   ├── services/
│   │   ├── hh_service.py        # HH API (резюме)
│   │   ├── hh_oauth.py          # HH OAuth
│   │   ├── linkedin_service.py  # LinkedIn API
│   │   ├── linkedin_oauth.py    # LinkedIn auth
│   │   ├── benchmark_service.py # HH API (вакансии) + аналитика
│   │   ├── assistant_service.py # OpenAI LLM API
│   │   └── audit.py             # Audit logging
│   └── main.py                  # FastAPI app
├── linkedin_api/                # LinkedIn API package
├── alembic/                     # Миграции БД
├── templates/                   # Jinja2 шаблоны
├── static/                      # CSS, JS, favicon
├── tests/                       # Pytest тесты
├── docker-compose.yml
├── backend.Dockerfile
└── requirements.txt
```
