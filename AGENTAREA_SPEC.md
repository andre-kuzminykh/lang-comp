# AgentArea — SPEC Documentation

> Source: https://github.com/agentarea/agentarea
> Date: 2026-04-02

---

## 1. Feature Context

| Section | Fill In |
|---------|---------|
| **Feature** | AgentArea — Cloud-native AI Agents Orchestration Platform |
| **Description (Goal / Scope)** | Open-core платформа для построения управляемых мульти-агентных AI-систем. Позволяет создавать сети агентов через no-code интерфейс, подключать собственных агентов или интегрировать внешних через A2A и MCP протоколы. Поддерживает self-hosted и cloud-hosted деплой. |
| **Client** | DevOps-инженеры, AI/ML-разработчики, Enterprise-команды, которым нужна оркестрация множества AI-агентов с governance и compliance |
| **Problem** | Существующие фреймворки ориентированы на одиночных агентов. Нет инфраструктуры для управления сетями агентов с изоляцией, контролем доступа, аудитом и масштабированием в production. |
| **Solution** | VPC-подобная сетевая архитектура агентов с granular permissions, A2A-протокол для межагентного взаимодействия, встроенный governance (tool approvals, ReBAC, audit trails), Temporal-based workflow orchestration, Kubernetes-native деплой |
| **Metrics** | 26 GitHub stars, 242 коммита, 6 релизов (v0.0.8 latest), 5 форков, Apache 2.0 лицензия |

### Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Backend API | Python 3.x, FastAPI, Alembic, UV |
| Web UI | TypeScript, Next.js 14+, React, Tailwind CSS, NextAuth.js |
| MCP Manager | Go, Kubernetes API, Gateway API |
| CLI | Node.js, Ink (React CLI), TypeScript |
| Orchestration | Temporal (distributed workflows) |
| Database | PostgreSQL |
| Cache/Events | Redis |
| LLM Proxy | LiteLLM (100+ моделей) |
| Auth | NextAuth.js, OIDC, WorkOS, Keycloak, Keto (ReBAC) |
| Secrets | Infisical, AWS, Database backend |
| Infrastructure | Docker, Docker Compose, Kubernetes, Helm Charts |

### Языки (% кодовой базы)

- Python — 63.6%
- TypeScript — 29.3%
- Go — 4.5%
- Shell, CSS, Go Template — остальное

---

## 2. User Stories and Use Cases

### User Story 1 — Создание и управление AI-агентами

| Field | Fill In |
|-------|---------|
| **Role** | AI/ML-разработчик |
| **User Story ID** | US-1 |
| **User Story** | As a AI/ML-разработчик, I want to создавать и настраивать AI-агентов через веб-интерфейс с кастомными инструкциями и инструментами, so that я могу быстро прототипировать и деплоить агентов без написания инфраструктурного кода |
| **UX / User Flow** | Логин → Dashboard → Create Agent → Настройка (имя, инструкции, LLM модель, инструменты, MCP серверы) → Deploy → Мониторинг через UI/CLI |

#### Use Case (+ Edges) BDD 1 — Создание агента через Web UI

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-1.1 |
| **Given** | Пользователь авторизован в Web UI, имеет доступ к workspace |
| **When** | Пользователь заполняет форму создания агента (имя, инструкции, выбор LLM модели, набор инструментов) и нажимает "Create" |
| **Then** | Агент создается в системе, появляется в списке агентов, получает статус "online", доступен для получения задач |
| **Input** | Имя агента, system prompt/инструкции, LLM модель (provider_type/model_name), список инструментов, MCP серверы |
| **Output** | Agent ID (UUID), статус агента, URL для взаимодействия |
| **State** | Агент зарегистрирован в PostgreSQL, доступен через API `/api/v1/agents/` |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-1 | Система должна поддерживать CRUD операции для агентов через REST API (`/api/v1/agents/`) |
| FR-2 | Агент должен поддерживать конфигурацию LLM модели в формате `provider_type/model_name` через LiteLLM (100+ моделей: OpenAI, Anthropic, Ollama и др.) |
| FR-3 | Система должна поддерживать назначение инструментов агенту (BaseTool, MCPTool, CalculateTool, CompletionTool, TasksToolset) |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-1 | Web UI должен быть responsive, построен на Next.js 14+ с Tailwind CSS |
| NFR-2 | Аутентификация через NextAuth.js с поддержкой OIDC, WorkOS, Keycloak |
| NFR-3 | JWT токены хранятся в HTTP-only cookies, middleware защищает authenticated routes |

#### Use Case (+ Edges) BDD 2 — Управление агентом через CLI

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-1.2 |
| **Given** | Пользователь авторизован через CLI (credentials в OS keychain) |
| **When** | Пользователь выполняет команды просмотра/фильтрации агентов, просмотра деталей агента |
| **Then** | Отображается список агентов с фильтрацией по статусу и capabilities, детальная информация по выбранному агенту |
| **Input** | Клавиатурная навигация (↑/↓, Enter, Escape, q), фильтры статуса (online/offline/busy) |
| **Output** | Список агентов, детали агента, capabilities |
| **State** | Данные получены через API endpoints GET `/agents`, GET `/agents/{id}`, GET `/agents/{id}/capabilities` |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-4 | CLI должен хранить credentials в OS keychain (macOS Keychain, Linux Secret Service, Windows Credential Manager) |
| FR-5 | CLI должен поддерживать автоматическое обновление токенов (POST `/auth/login`, `/auth/refresh`, `/auth/logout`) |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-4 | CLI построен на Ink (React для терминала) с интерактивной клавиатурной навигацией |
| NFR-5 | Конфигурация через `.env` файл: `API_URL`, `API_TIMEOUT`, `MAX_RETRIES`, `LOG_LEVEL`, `THEME` |

---

### User Story 2 — Оркестрация мульти-агентных систем и A2A-коммуникация

| Field | Fill In |
|-------|---------|
| **Role** | Platform Engineer / DevOps |
| **User Story ID** | US-2 |
| **User Story** | As a Platform Engineer, I want to строить сети агентов с изолированными группами и контролируемыми коммуникациями между ними, so that агенты могут безопасно взаимодействовать друг с другом, делегировать задачи и работать в иерархических командах |
| **UX / User Flow** | Настройка Network → Определение agent groups (VPC-подобная изоляция) → Настройка permissions между группами → Включение A2A протокола → Мониторинг коммуникаций через audit trail |

#### Use Case BDD 1 — Настройка сети агентов с VPC-изоляцией

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-2.1 |
| **Given** | Существуют несколько агентов в разных рабочих группах |
| **When** | Администратор настраивает network permissions между группами агентов, определяет правила A2A-коммуникации |
| **Then** | Агенты могут общаться только в рамках разрешенных связей, все коммуникации логируются в audit trail |
| **Input** | Agent group IDs, permission rules (allow/deny), A2A routing configuration |
| **Output** | Network topology, active connections, audit logs |
| **State** | Permissions хранятся в Keto (ReBAC), workflows управляются через Temporal |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-6 | Система должна реализовывать VPC-подобную изоляцию агентов с granular network permissions |
| FR-7 | A2A (Agent-to-Agent) Protocol должен обеспечивать нативную межагентную коммуникацию с поддержкой team hierarchies и task delegation |
| FR-8 | Все межагентные коммуникации должны логироваться для compliance (audit trails) |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-6 | Workflows оркестрируются через Temporal для надежного distributed execution |
| NFR-7 | Система должна поддерживать Kubernetes-native деплой с Helm Charts |

#### Use Case (+ Edges) BDD 2 — Выполнение long-running задач с event-driven триггерами

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-2.2 |
| **Given** | Агент настроен на выполнение long-running задачи с event-driven триггерами |
| **When** | Срабатывает триггер (таймер, webhook, событие от третьей стороны) |
| **Then** | Агент запускает задачу, прогресс отслеживается в реальном времени через SSE, задача завершается по достижении цели / бюджета / таймаута |
| **Input** | Trigger event (timer/webhook/third-party), task parameters, termination criteria (goal achievement, budget limits, timeouts) |
| **Output** | Task ID, real-time stdout/stderr stream (SSE), execution result, goal progress |
| **State** | Task управляется через Temporal workflow, результат сохраняется в PostgreSQL, стрим через Redis |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-9 | Система должна поддерживать event-driven триггеры: таймеры, webhooks, события третьих сторон |
| FR-10 | Long-running задачи должны поддерживать гибкие критерии завершения: goal achievement, budget limits, timeouts |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-8 | Real-time мониторинг через SSE (Server-Sent Events) endpoint GET `/sse/tasks/{id}` |
| NFR-9 | Task cancellation support через DELETE `/tasks/{id}` |

---

### User Story 3 — Governance, MCP-интеграция и безопасность

| Field | Fill In |
|-------|---------|
| **Role** | Security / Compliance Officer |
| **User Story ID** | US-3 |
| **User Story** | As a Security Officer, I want to контролировать какие инструменты доступны агентам, требовать human approval для критических операций и иметь полный audit trail, so that мульти-агентная система соответствует требованиям безопасности и compliance |
| **UX / User Flow** | Настройка Tool Approval Workflows → Определение ReBAC-политик → Подключение MCP серверов с hash verification → Мониторинг audit trail |

#### Use Case (+ Edges) BDD 1 — Tool approval и MCP-интеграция

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-3.1 |
| **Given** | Агент запрашивает выполнение инструмента, требующего human approval; MCP серверы подключены с hash verification |
| **When** | Агент вызывает tool, который настроен на mandatory approval |
| **Then** | Выполнение приостанавливается, отправляется запрос на approval ответственному лицу; после одобрения инструмент выполняется; результат и решение логируются в audit trail |
| **Input** | Tool call request, approval policy, MCP server configuration (template/Dockerfile/remote с hash) |
| **Output** | Approval decision (approve/deny), tool execution result, audit log entry |
| **State** | Policies хранятся в Keto (ReBAC), MCP серверы управляются через Go-based MCP Manager, audit в PostgreSQL |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-11 | Tool approval workflows должны требовать human authorization для критических операций |
| FR-12 | MCP серверы должны поддерживать создание из templates, custom Dockerfiles и remote MCP с hash verification; активация через warm pools (~1.3s vs 8-15s стандартно) |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-10 | Множественные secret backends: Database, Infisical, AWS |
| NFR-11 | ReBAC авторизация через Keto для fine-grained access control |

---

## 3. Architecture / Solution

### 3.1 Client Side

| Area | Fill In |
|------|---------|
| **Client Type** | Web UI (Next.js) + CLI (Ink/React) + Agents SDK (Python) |
| **User Entry Points** | 1) Web UI на `http://localhost:3000` — основной интерфейс; 2) CLI `agentarea-cli` — терминальное управление; 3) REST API `/api/v1/*` — программный доступ; 4) Agents SDK — встраивание агентов в собственный код |
| **Main Screens / Commands** | **Web UI:** Dashboard, Agent List, Agent Create/Edit, Task Monitor, MCP Servers, Network Config, Audit Logs. **CLI:** Login, Agent List/Filter, Task Submit, Task Stream, Task Cancel |
| **Input / Output Format** | **Input:** JSON (API), формы (Web UI), keyboard (CLI). **Output:** JSON (API), HTML/React (Web UI), SSE streams (real-time), Ink-rendered terminal (CLI) |

### 3.2 Backend Services

#### Service 1: agentarea-platform (Python/FastAPI)

| Area | Fill In |
|------|---------|
| **Service Name** | agentarea-platform |
| **Responsibility** | Core backend: управление агентами, чатами, LLM моделями, MCP серверами, задачами |
| **Business Logic** | Модули: `agentarea_agents` (CRUD агентов, execution), `agentarea_chat` (conversations), `agentarea_llm` (LLM abstraction через LiteLLM), `agentarea_mcp` (MCP orchestration), `agentarea_tasks` (workflow management), `agentarea_common` (shared DB models, utilities), `agentarea_secrets` (Infisical integration) |
| **API / Contract** | REST API v1 |
| **Request Schema** | JSON over HTTP |
| **Response Schema** | JSON responses, SSE для streaming |
| **Error Handling** | FastAPI exception handlers, HTTP status codes |

**API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/agents/` | GET, POST | Список / создание агентов |
| `/api/v1/agents/{id}` | GET, PUT, DELETE | Детали / обновление / удаление агента |
| `/api/v1/llm-models/` | GET, POST | Управление LLM моделями |
| `/api/v1/mcp-servers/` | GET, POST | Управление MCP серверами |
| `/api/v1/tasks/` | GET, POST | Список / создание задач |
| `/api/v1/tasks/{id}` | GET, DELETE | Детали / отмена задачи |
| `/api/v1/chat/` | GET, POST | Chat functionality |
| `/sse/tasks/{id}` | GET (SSE) | Real-time task streaming |
| `/auth/login` | POST | Аутентификация |
| `/auth/refresh` | POST | Обновление токена |
| `/auth/logout` | POST | Выход |

#### Service 2: agentarea-mcp-manager (Go)

| Area | Fill In |
|------|---------|
| **Service Name** | agentarea-mcp-manager |
| **Responsibility** | Управление жизненным циклом MCP серверов: создание, активация, мониторинг, удаление |
| **Business Logic** | Warm pool architecture (~1.3s activation vs 8-15s), Kubernetes-native pod management, Gateway API / Ingress routing, feature flags, container sandboxing |
| **API / Contract** | REST API |
| **Request Schema** | `POST /instances` — `{ instance_id, name, service_name, image, port, workspace_id }` |
| **Response Schema** | `{ id (UUID), name, url, status }` |
| **Error Handling** | HTTP status codes, Kubernetes event monitoring |

**Компоненты:**

| Component | Description |
|-----------|-------------|
| `cmd/mcp-manager/` | REST API для управления instances, Kubernetes backend, warm pool support |
| `cmd/activation-service/` | Запускается в warm pool pods, скачивает и активирует MCP container images |
| `internal/` | Core business logic |
| `k8s/` | Kubernetes manifests |

**Конфигурация:**

| Variable | Purpose | Default |
|----------|---------|---------|
| `MCP_FEATURES_ENABLED` | Feature flags (comma-separated) | `gateway_api,state_reconciler` |
| `WARM_POOL_ENABLED` | Warm pool fast start | `false` |
| `KUBERNETES_GATEWAY_NAME` | Gateway API resource name | `envoy-gateway` |

#### Service 3: agentarea-webapp (Next.js)

| Area | Fill In |
|------|---------|
| **Service Name** | agentarea-webapp |
| **Responsibility** | Web-интерфейс для управления платформой |
| **Business Logic** | NextAuth.js auth flow, openapi-fetch для type-safe API клиента, i18n, middleware route protection |
| **API / Contract** | Консьюмер REST API `/api/v1/*` от agentarea-platform |

#### Service 4: agentarea-cli (Node.js/Ink)

| Area | Fill In |
|------|---------|
| **Service Name** | agentarea-cli |
| **Responsibility** | Терминальный интерфейс для управления агентами и задачами |
| **Business Logic** | OS keychain auth, SSE streaming, interactive keyboard navigation, agent discovery и task submission |

### 3.3 Data Architecture and Flows

| Area | Fill In |
|------|---------|
| **Main Entities (ER)** | `Agent` (id, name, instructions, llm_model, tools, status, workspace_id), `Task` (id, agent_id, params, status, result, trigger_type), `LLMModel` (id, provider_type, model_name, api_key, endpoint_url), `MCPServer` (id, name, image, port, status, workspace_id), `Workspace` (id, name, permissions), `AuditLog` (id, agent_id, action, timestamp, details), `Chat/Conversation` (id, agent_id, messages), `User` (id, credentials, roles) |
| **Relationships (ER)** | `User` 1:N `Workspace`, `Workspace` 1:N `Agent`, `Agent` N:M `Tool`, `Agent` N:M `MCPServer`, `Agent` 1:N `Task`, `Agent` 1:N `Chat`, `Agent` N:N `Agent` (A2A connections через Network permissions), `Agent/Task` 1:N `AuditLog` |
| **Data Flow (DFD)** | User → Web UI/CLI → REST API (FastAPI) → Business Logic (agentarea_agents/chat/llm/mcp/tasks) → PostgreSQL (persistence) + Redis (cache/events) + Temporal (workflows) + MCP Manager (tool execution) + LiteLLM (LLM calls) → Response/SSE Stream → User |
| **Input Sources** | 1) Web UI forms, 2) CLI commands, 3) REST API calls, 4) Event triggers (timers, webhooks, third-party events), 5) A2A protocol messages от других агентов, 6) MCP tool responses |

**Data Flow Diagram (текстовый):**

```
┌─────────┐     ┌─────────┐     ┌──────────────────┐
│ Web UI  │────▶│         │     │   PostgreSQL      │
│ (Next.js)│    │         │────▶│   (persistence)   │
└─────────┘     │         │     └──────────────────┘
                │ FastAPI │
┌─────────┐     │ Backend │     ┌──────────────────┐
│  CLI    │────▶│         │────▶│   Redis           │
│ (Ink)   │     │         │     │   (cache/events)  │
└─────────┘     │         │     └──────────────────┘
                │         │
┌─────────┐     │         │     ┌──────────────────┐
│ SDK /   │────▶│         │────▶│   Temporal        │
│ API     │     │         │     │   (workflows)     │
└─────────┘     └────┬────┘     └──────────────────┘
                     │
              ┌──────┴──────┐
              │             │
        ┌─────▼─────┐ ┌────▼─────┐
        │ MCP       │ │ LiteLLM  │
        │ Manager   │ │ Proxy    │
        │ (Go)      │ │ (100+LLM)│
        └─────┬─────┘ └──────────┘
              │
        ┌─────▼─────┐
        │ MCP Server│
        │ Pods (K8s)│
        └───────────┘
```

### 3.4 Infrastructure

| Area | Fill In |
|------|---------|
| **Required Hardware / Resources** | Docker + Docker Compose (минимум для local dev) |
| **Production Deployment** | Kubernetes cluster с Helm Charts |
| **Compute** | K8s pods для каждого сервиса + warm pool pods для MCP серверов |
| **Storage** | PostgreSQL (persistent data), Redis (ephemeral cache/events) |
| **Networking** | Kubernetes Gateway API / Ingress, envoy-gateway для MCP routing |
| **Secrets** | Infisical (primary), AWS Secrets Manager, Database backend (fallback) |
| **Auth Infrastructure** | Keto (ReBAC), OIDC providers (WorkOS, Keycloak, Generic OIDC) |
| **Monitoring** | Temporal UI для workflows, audit logs, SSE streams |

**Quick Start (Local):**

```bash
git clone https://github.com/agentarea/agentarea.git
cd agentarea
make up
# Platform доступна на http://localhost:3000
```

**Production (Kubernetes + Helm):**

```bash
helm upgrade agentarea charts/agentarea -n agentarea \
  --set mcpManager.warmPool.enabled=true \
  --set mcpManager.features.enabled={warm_pool,gateway_api,state_reconciler}
```

**Environment Variables (Backend):**

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis instance |
| `INFISICAL_CLIENT_ID` / `INFISICAL_CLIENT_SECRET` | Secrets management |
| `MCP_MANAGER_URL` | MCP Manager service endpoint |
| `TEMPORAL_HOST` | Temporal workflow engine |

**Environment Variables (Web UI):**

| Variable | Purpose |
|----------|---------|
| `NEXTAUTH_URL` | NextAuth base URL |
| `NEXTAUTH_SECRET` | NextAuth secret key |
| `API_URL` | Backend API URL |
| Provider-specific | OIDC / WorkOS / Keycloak credentials |

---

## 4. Work Plan

### Mapping: Use Case → Tasks

| Use Case | Task ID | Task | Dependencies | DoD | Subtasks |
|----------|---------|------|--------------|-----|----------|
| UC-1.1 | T-1 | Создание агента через Web UI (CRUD + LLM + Tools) | — | Агент создается, настраивается и отображается в UI; API `/api/v1/agents/` работает | ST-1, ST-2, ST-3 |
| UC-1.2 | T-2 | Управление агентом через CLI | T-1 | CLI авторизуется, показывает список агентов, фильтрует по статусу | ST-4, ST-5 |
| UC-2.1 | T-3 | Настройка сети агентов с VPC-изоляцией и A2A | T-1 | Агенты изолированы по группам, A2A работает в рамках permissions, audit trail пишется | ST-6, ST-7, ST-8 |
| UC-2.2 | T-4 | Long-running задачи с event-driven триггерами | T-1, T-3 | Задачи запускаются по триггерам, SSE стрим работает, flexible termination | ST-9, ST-10 |
| UC-3.1 | T-5 | Tool approval workflows и MCP-интеграция | T-1, T-3 | Tool approvals блокируют выполнение до human approval, MCP серверы стартуют за ~1.3s | ST-11, ST-12 |

---

## 5. Detailed Task Breakdown

### Task 1

| Field | Fill In |
|-------|---------|
| **Task ID** | T-1 |
| **Related Use Case** | UC-1.1 |
| **Task Description** | Реализация полного CRUD для AI-агентов: backend API (FastAPI), database models (PostgreSQL + Alembic), LLM integration (LiteLLM), tool system, Web UI формы |
| **Dependencies** | — (базовая задача) |
| **DoD** | Агент создается через Web UI и API, сохраняется в БД, поддерживает выбор LLM модели и набора инструментов |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|--------------|---------------------|
| ST-1 | Backend: FastAPI endpoints `/api/v1/agents/` CRUD, Alembic миграции для таблицы Agent, Pydantic schemas | — | POST/GET/PUT/DELETE работают, миграции применяются, валидация входных данных |
| ST-2 | LLM Integration: подключение LiteLLM proxy, конфигурация моделей в формате `provider_type/model_name`, endpoint `/api/v1/llm-models/` | ST-1 | Поддержка OpenAI, Anthropic, Ollama; streaming и non-streaming режимы; token usage tracking |
| ST-3 | Web UI: React-формы создания/редактирования агента, отображение списка агентов, интеграция через openapi-fetch | ST-1 | Формы валидируются, агенты отображаются с статусами, type-safe API клиент |

### Task 2

| Field | Fill In |
|-------|---------|
| **Task ID** | T-2 |
| **Related Use Case** | UC-1.2 |
| **Task Description** | Реализация CLI интерфейса: авторизация через OS keychain, просмотр/фильтрация агентов, интерактивная навигация |
| **Dependencies** | T-1 (API endpoints должны существовать) |
| **DoD** | CLI авторизуется, отображает агентов с фильтрацией, поддерживает keyboard navigation |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|--------------|---------------------|
| ST-4 | Auth module: login/refresh/logout через OS keychain (macOS Keychain, Linux Secret Service, Windows Credential Manager) | T-1 | Токен сохраняется в keychain, автоматический refresh, работает на всех ОС |
| ST-5 | Agent management UI: Ink-компоненты для списка агентов, фильтрации по статусу (online/offline/busy), детального просмотра | ST-4 | Keyboard navigation (↑/↓, Enter, Escape, q), real-time обновление статусов |

### Task 3

| Field | Fill In |
|-------|---------|
| **Task ID** | T-3 |
| **Related Use Case** | UC-2.1 |
| **Task Description** | Реализация сетевой архитектуры агентов: VPC-подобная изоляция, A2A протокол, ReBAC permissions через Keto, audit logging |
| **Dependencies** | T-1 (агенты должны существовать) |
| **DoD** | Агенты изолированы по группам, A2A коммуникация работает только через разрешенные связи, все действия в audit trail |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|--------------|---------------------|
| ST-6 | Network model: DB schema для agent groups, network permissions (allow/deny rules), Alembic миграции | T-1 | CRUD для групп и permissions, валидация правил |
| ST-7 | A2A Protocol: межагентная коммуникация, agent discovery, team hierarchies, task delegation через Temporal workflows | ST-6 | Агент A может отправить задачу Агенту B (если разрешено), hierarchical routing работает |
| ST-8 | ReBAC + Audit: интеграция Keto для fine-grained access control, запись всех действий в audit log | ST-6 | Permissions проверяются перед каждой A2A операцией, audit log содержит timestamp, agent_id, action, details |

### Task 4

| Field | Fill In |
|-------|---------|
| **Task ID** | T-4 |
| **Related Use Case** | UC-2.2 |
| **Task Description** | Реализация long-running задач: event-driven триггеры (timer/webhook/third-party), Temporal workflows, SSE streaming, flexible termination criteria |
| **Dependencies** | T-1 (агенты), T-3 (network для multi-agent tasks) |
| **DoD** | Задачи запускаются по триггерам, прогресс стримится через SSE, задача завершается по цели/бюджету/таймауту |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|--------------|---------------------|
| ST-9 | Trigger system: timer-based, webhook-based, third-party event triggers; Temporal workflow definitions для каждого типа | T-1 | Все три типа триггеров запускают задачи, Temporal обеспечивает retry и fault tolerance |
| ST-10 | Execution engine: SSE streaming endpoint `/sse/tasks/{id}`, goal progress evaluation (GoalProgressEvaluator), termination criteria (goal/budget/timeout), task cancellation | ST-9 | Real-time stdout/stderr стрим, прогресс оценивается автоматически, отмена задачи работает через DELETE `/tasks/{id}` |

### Task 5

| Field | Fill In |
|-------|---------|
| **Task ID** | T-5 |
| **Related Use Case** | UC-3.1 |
| **Task Description** | Реализация governance: tool approval workflows, MCP server management через Go-based manager, warm pool activation, hash verification для remote MCP |
| **Dependencies** | T-1 (агенты и tools), T-3 (permissions infrastructure) |
| **DoD** | Tool approvals блокируют execution до human approval, MCP серверы активируются за ~1.3s через warm pools |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|--------------|---------------------|
| ST-11 | Tool approval system: конфигурация policies для tools, approval workflow (pause → notify → wait for decision → execute/deny), интеграция с audit trail | T-3 | Critical tools требуют approval, execution блокируется до решения, решение логируется |
| ST-12 | MCP Manager: Go-сервис для lifecycle management MCP серверов, warm pool architecture (pre-initialized pods), `POST /instances` API, hash verification для remote MCPs, Kubernetes Gateway API routing | T-1 | MCP сервер создается за ~1.3s (warm pool), поддерживает templates/Dockerfiles/remote, hash verification проходит |

---

## Appendix A: Agents SDK (agentarea-agents-sdk)

Standalone Python SDK, извлеченный из основной платформы. Zero dependencies на другие AgentArea библиотеки.

### Архитектура SDK

```
src/agentarea_agents_sdk/
├── agents/      # Agent class, create_agent() factory
├── models/      # LLMModel (LiteLLM), LLMRequest/Response, LLMUsage
├── tools/       # BaseTool, MCPTool, CalculateTool, CompletionTool, TasksToolset, ToolExecutor, ToolRegistry
├── runners/     # BaseAgentRunner — execution engines
├── services/    # GoalProgressEvaluator
├── context/     # ContextService, InMemoryContextService, ContextEvent
├── goal/        # Goal evaluation
├── tasks/       # Task management
└── prompts.py   # PromptBuilder (ReAct framework), MessageTemplates
```

### Пример использования

```python
import asyncio
from agentarea_agents_sdk.agents import create_agent

async def example():
    agent = create_agent(
        name="Math Assistant",
        instruction="You are a helpful math assistant.",
        model="ollama_chat/qwen2.5"  # format: provider_type/model_name
    )

    # Streaming
    async for content in agent.run_stream("Calculate 25 * 4 + 15"):
        print(content, end="")

    # Non-streaming
    result = await agent.run("What is 7 * 8?")
    print(result)

asyncio.run(example())
```

### Поддерживаемые LLM провайдеры

| Provider | Config |
|----------|--------|
| OpenAI | `provider_type="openai", model_name="gpt-4"` |
| Anthropic | `provider_type="anthropic", model_name="claude-3-opus-20240229"` |
| Ollama (local) | `provider_type="ollama_chat", model_name="qwen2.5", endpoint_url="http://localhost:11434"` |
| Google, Azure, Cohere | Через LiteLLM (100+ моделей) |

### Требования

- Python 3.11+ (3.12+ recommended)
- LiteLLM >= 1.74.15
- Pydantic >= 2.4.2
- httpx >= 0.25.0
- OpenAI >= 1.82.0

---

## Appendix B: Структура репозитория

```
agentarea/
├── agentarea-platform/          # Backend API (Python/FastAPI)
│   ├── agentarea_api/           #   FastAPI application
│   ├── apps/                    #   Standalone services (API, CLI, worker)
│   ├── libs/                    #   Domain libraries
│   │   ├── agentarea_agents/    #     Agent management
│   │   ├── agentarea_chat/      #     Chat/conversations
│   │   ├── agentarea_llm/       #     LLM abstraction
│   │   ├── agentarea_mcp/       #     MCP orchestration
│   │   ├── agentarea_tasks/     #     Task/workflow management
│   │   ├── agentarea_common/    #     Shared utilities, DB models
│   │   └── agentarea_secrets/   #     Secret management (Infisical)
│   ├── tests/                   #   Unit + integration tests
│   ├── temporal-config/         #   Temporal workflow config
│   └── docs/                    #   Documentation
├── agentarea-webapp/            # Web UI (Next.js 14+/React/TypeScript)
│   ├── src/app/                 #   App Router pages & API routes
│   ├── src/auth/                #   Authentication pages
│   ├── src/components/          #   React components
│   ├── src/lib/                 #   Utilities & API client
│   └── messages/                #   i18n translations
├── agentarea-mcp-manager/       # MCP Server Manager (Go)
│   ├── cmd/mcp-manager/         #   REST API + K8s backend
│   ├── cmd/activation-service/  #   Warm pool activation
│   ├── internal/                #   Core business logic
│   └── k8s/                     #   Kubernetes manifests
├── agentarea-cli/               # CLI (Node.js/Ink/TypeScript)
├── agentarea-operator/          # Kubernetes operator
├── agentarea-bootstrap/         # Initialization tools
└── charts/                      # Helm Charts for K8s deployment
```

---

## Appendix C: Ссылки

- **Repository:** https://github.com/agentarea/agentarea
- **Agents SDK:** https://github.com/agentarea/agentarea-agents-sdk
- **License:** Apache 2.0 (open-core)
- **Community:** Discord, GitHub Issues, GitHub Discussions
- **Twitter:** @agentarea_hq
