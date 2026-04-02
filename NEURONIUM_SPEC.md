# NEURONIUM AI — SPEC Document

**Repository:** https://github.com/dataism-lab/neuronium
**Version:** 0.1.0 (Alpha)
**License:** MIT (pyproject.toml) / Apache-2.0 (GitHub)
**Language:** Python 3.11+
**Date:** 2026-04-02

---

## 1. Feature Context

| Section | Fill In |
|---------|---------|
| **Feature** | Neuronium AI Super Agent |
| **Description (Goal / Scope)** | Commitment-aware AI Super Agent framework с Action Graph (DAG) планированием, гибридной памятью (GraphRAG + agentic retrieval), verification critics, типизированными контрактами и audit/replay trace. Цель — надёжное решение долгосрочных, высокоэнтропийных задач через структурированную контрольную архитектуру вместо использования LLM как standalone reasoning engine. |
| **Client** | Python-разработчики / AI-инженеры / DevOps-команды, строящие автономные AI-агенты для автоматизации сложных многошаговых задач |
| **Problem** | Обычные prompted-агенты страдают от: линейной хрупкости планов, каскадных ошибок, неявного состояния, слабой самопроверки, несовместимости форматов инструментов. Нет гарантий детерминизма, воспроизводимости и аудита. |
| **Solution** | Фреймворк с формальным lifecycle (COMMIT → EXECUTE → CONTROL → ADAPT), DAG-планированием через HTN-декомпозицию, детерминированным исполнением, иммутабельными артефактами с lineage, встроенными critics для верификации, и полным replay из audit trace. |
| **Metrics** | Детерминизм: идентичные входы → идентичные traces. Replay fidelity: 100% воспроизводимость из trace. Artifact integrity: SHA-256 content-addressed, append-only. Coverage: 52 test-файла, ~150 Python source файлов. |

---

## 2. User Stories and Use Cases

### User Story 1 — Запуск AI-агента для решения задачи

| Field | Fill In |
|-------|---------|
| **Role** | AI-инженер / Python-разработчик |
| **User Story ID** | US-1 |
| **User Story** | As a Python-разработчик, I want to запустить AI-агента с текстовым описанием задачи, so that агент автономно спланирует и выполнит многошаговое решение с верификацией результата. |
| **UX / User Flow** | 1) Установка `pip install -e .` → 2) Настройка `neuronium.toml` + env `NEURONIUM_OPENAI_API_KEY` → 3) CLI: `neuronium-agent run -o "Write a fibonacci function"` → 4) Агент планирует DAG, исполняет ноды, запускает critics → 5) Результат + trace export |

#### Use Case (+ Edges) BDD 1 — Batch-режим CLI

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-1.1 |
| **Given** | Установлен neuronium-agent, настроен API ключ OpenAI, существует neuronium.toml |
| **When** | Пользователь запускает `neuronium-agent run --objective "Write fibonacci" --trace-export ./trace.jsonl` |
| **Then** | Агент: 1) Выбирает runbook (default: super_agent_v0), 2) HTN-планировщик создаёт ActionGraph (DAG), 3) DAGExecutor исполняет ноды (ModelNode → CodeNode → Critic), 4) Результат сохраняется как артефакт, 5) Trace экспортируется в JSONL |
| **Input** | `RunRequest(objective="Write fibonacci", mode="batch")` |
| **Output** | `RunHandle(trace_id, execution_id, created_at)` → `RunStatus(state="COMPLETED")` + trace.jsonl файл |
| **State** | PENDING → RUNNING → COMPLETED (или FAILED с recovery) |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-1 | Система должна принимать objective (текст задачи) и создавать RunRequest с валидацией через Pydantic v2 |
| FR-2 | HTN-планировщик должен декомпозировать objective в ActionGraph (DAG) с типизированными нодами (model/mcp/code/decision/aggregate) |
| FR-3 | DAGExecutor должен исполнять граф в топологическом порядке с детерминированным tie-breaking (priority → node_id) |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-1 | Детерминизм: одинаковые входы + seed → одинаковые traces и outputs (canonical JSON, sorted keys, seeded RNG) |
| NFR-2 | Параллелизм: до `max_parallel_nodes` (default: 4) независимых нод одновременно |
| NFR-3 | Совместимость: работа без Postgres/Redis в базовой установке (SQLite + FS CAS) |

#### Use Case (+ Edges) BDD 2 — Interactive-режим с pause/stop

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-1.2 |
| **Given** | Агент запущен в interactive-режиме (`--mode interactive`) |
| **When** | Пользователь нажимает Enter/p (pause) или q (stop) во время исполнения |
| **Then** | Агент: 1) Устанавливает interrupt flag, 2) Ждёт grace period (default: 30s для pause, 5s для stop), 3) Создаёт checkpoint на phase boundary, 4) Переходит в PAUSED/CANCELLED |
| **Input** | Stdin input (Enter/p = pause, q = stop) |
| **Output** | `RunStatus(state="PAUSED")` с checkpoint для resume |
| **State** | RUNNING → PAUSED (или RUNNING → CANCELLED) |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-4 | Система должна поддерживать non-blocking stdin мониторинг (select на Unix, msvcrt на Windows) |
| FR-5 | При pause — checkpoint на phase boundary, при resume — восстановление из checkpoint с продолжением DAG |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-4 | Grace period: активные ноды получают время для cooperative completion перед принудительным завершением |
| NFR-5 | Checkpoint должен быть достаточным для полного восстановления состояния без потери выполненной работы |

---

### User Story 2 — Управление и контроль запущенного агента

| Field | Fill In |
|-------|---------|
| **Role** | AI-инженер / оператор |
| **User Story ID** | US-2 |
| **User Story** | As a оператор, I want to управлять агентом через control-команды (continue/pause/revise/replan/stop/escalate), so that я могу корректировать поведение агента в реальном времени без потери прогресса. |
| **UX / User Flow** | 1) Агент работает → 2) Оператор видит статус → 3) Отправляет control-команду через CLI или Python API → 4) Агент переходит в соответствующее состояние (ADAPT/PAUSED/CANCELLED) → 5) Revise/replan сохраняет valid results |

#### Use Case BDD 1 — Revise (модификация intention)

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-2.1 |
| **Given** | Агент в состоянии RUNNING или PAUSED с активным intention |
| **When** | Оператор отправляет `ControlCommand(type="revise", payload={"constraints": ["use async"]})` |
| **Then** | 1) Агент переходит в ADAPT, 2) NL feedback парсится в RFC6902 patch, 3) Intention обновляется с сохранением valid node outputs, 4) Replan только затронутых ветвей DAG |
| **Input** | `ControlCommand` с type="revise" и payload с модификациями |
| **Output** | `RunStatus` с обновлённым состоянием, сохранённые артефакты valid branches |
| **State** | RUNNING/PAUSED → ADAPT → EXECUTE (с модифицированным планом) |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-6 | Система должна поддерживать 6 типов control-команд: continue, pause, revise, replan, stop, escalate |
| FR-7 | Revise должен сохранять completed node outputs в valid branches (partial invalidation по scope) |
| FR-8 | NL feedback должен конвертироваться в structured patch через classification intent → extraction scope |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-6 | Все control-команды должны быть idempotent (multiple continues без промежуточных изменений = no-op) |
| NFR-7 | Каждая control-команда записывается как decision record в trace для аудита |

#### Use Case (+ Edges) BDD 2 — Escalation к пользователю

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-2.2 |
| **Given** | Агент столкнулся с неразрешимой проблемой (repeated failure 3+ раз, confidence collapse, constraint unsatisfiability) |
| **When** | Recovery policy возвращает ESCALATE (или пользователь явно запросил escalation) |
| **Then** | 1) Execution pause, 2) Checkpoint сохраняется, 3) Формируется context package (state + decisions + obstacles), 4) Пользователь получает уведомление с рекомендациями |
| **Input** | Автоматический trigger (failure pattern) или явная команда escalate |
| **Output** | Suspension point с полным контекстом; варианты: continue / revise / replan / stop |
| **State** | RUNNING → PAUSED (escalation) с ожиданием user resolution |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-9 | Escalation triggers: repeated rollback (3+), resource exhaustion, constraint unsatisfiability, confidence < threshold, safety concern |
| FR-10 | Escalation package должен содержать: AgentState snapshot, decision history, failure analysis, recommended options |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-8 | Escalation не должна терять state — полный checkpoint для resume после user resolution |
| NFR-9 | Asynchronous escalation: поддержка длительного deliberation с state preservation |

---

### User Story 3 — Replay и аудит выполнения

| Field | Fill In |
|-------|---------|
| **Role** | QA-инженер / аудитор |
| **User Story ID** | US-3 |
| **User Story** | As a QA-инженер, I want to воспроизвести выполнение агента из trace файла, so that я могу отлаживать проблемы и подтверждать корректность без обращения к внешним системам. |
| **UX / User Flow** | 1) Получить trace.jsonl из предыдущего run → 2) `neuronium-agent replay --trace-id <id>` → 3) Система инжектирует recorded responses в ноды → 4) Идентичный execution без внешних вызовов → 5) Валидация: computed artifact IDs == recorded artifact IDs |

#### Use Case (+ Edges) BDD 1 — Offline replay из trace

| Field | Fill In |
|-------|---------|
| **Use Case ID** | UC-3.1 |
| **Given** | Существует completed trace с записанными LLM-ответами, tool outputs, и всеми недетерминированными входами |
| **When** | Пользователь запускает `neuronium-agent replay --trace-id <id>` |
| **Then** | 1) ReplayProvider загружает recorded responses, 2) Ноды получают pre-recorded данные вместо live calls, 3) Execution воспроизводится детерминированно, 4) При divergence — ошибка с диагностикой |
| **Input** | trace_id, полный trace из IndexStore |
| **Output** | Воспроизведённый execution с валидацией идентичности artifacts |
| **State** | Replay mode: read-only execution с injection recorded responses |

**Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| FR-11 | ReplayProvider должен инжектировать recorded responses в ModelNode, CodeNode, McpToolNode через set_replay_responses() |
| FR-12 | При divergence (computed artifact ID != recorded) — система должна выбросить ReplayError с диагностикой |

**Non-Functional Requirements**

| Req ID | Requirement |
|--------|-------------|
| NFR-10 | Replay не требует внешних систем (OpenAI API, Docker, MCP servers) — все данные из trace |
| NFR-11 | Trace completeness validation перед началом replay — explicit error если trace неполный |

---

## 3. Architecture / Solution

### 3.1 Client Side

| Area | Fill In |
|------|---------|
| **Client Type** | CLI (`neuronium-agent`) + Python API (`neuronium_agent.api`) |
| **User Entry Points** | 1) CLI команда `neuronium-agent run -o "..."` 2) Python: `create_runner() → AgentRunner.start(RunRequest)` |
| **Main Screens / Commands** | `run` (запуск/resume), `status` (статус), `control` (управление), `replay` (воспроизведение), `schema` (экспорт JSON Schema), `worker` (Redis+RQ worker) |
| **Input / Output Format** | Input: текстовый objective + optional constraints (list[str]) + mode (batch/supervised/interactive). Output: RunStatus (JSON), trace (JSONL/JSON/ZIP), артефакты (content-addressed blobs) |

### 3.2 Backend Services

#### Service 1: AgentRunner (Public Facade)

| Area | Fill In |
|------|---------|
| **Service Name** | `AgentRunner` (`neuronium_agent/api.py`) |
| **Responsibility** | Публичный фасад — единая точка входа для внешних приложений. Оркестрирует запуск, управление и экспорт. |
| **Business Logic** | Создание Orchestrator, BlobStore, IndexStore. Делегирует execution в Orchestrator. Управляет lifecycle run. |
| **API / Contract** | `start(RunRequest) → RunHandle`, `get_status(RunHandle) → RunStatus`, `control(RunHandle, ControlCommand) → RunStatus`, `export_trace(RunHandle, format, path)`, `resume_run(RunHandle)`, `replay(trace_id)` |
| **Request Schema** | `RunRequest { objective: str, constraints: list[str], mode: "batch"/"supervised"/"interactive", metadata: dict }` |
| **Response Schema** | `RunHandle { trace_id: str, execution_id: str, created_at: datetime }`, `RunStatus { state: enum, progress: float, current_node_ref: str, message: str }` |
| **Error Handling** | Иерархия: `NeuroniumError` → `ConfigError`, `ValidationError`, `StorageError`, `McpError`, `SandboxError`, `ReplayError`. Все ошибки детерминированно сериализуемы в trace. |

#### Service 2: Orchestrator (Cognitive Core)

| Area | Fill In |
|------|---------|
| **Service Name** | `Orchestrator` (`neuronium_agent/core/orchestrator.py`, ~1400 строк) |
| **Responsibility** | Главный цикл COMMIT → EXECUTE → CONTROL → ADAPT. Управление N-stage runbook execution с recovery, checkpointing и user control. |
| **Business Logic** | Цикл: 1) COMMIT — выбор runbook, intent extraction, missing slot detection, вызов planner backend → ActionGraph. 2) EXECUTE — делегация в DAGExecutor. 3) CONTROL — success gate evaluation, critic verdict. 4) ADAPT — recovery decision (retry/replan/escalate/fail). Для multi-stage runbooks — продвижение по стадиям. |
| **API / Contract** | Internal: `__call__(run_request, on_status_change) → RunStatus`. Взаимодействует с DAGExecutor, TraceRecorder, HTNPlanner, BlobStore, IndexStore. |

#### Service 3: DAGExecutor (Deterministic Execution)

| Area | Fill In |
|------|---------|
| **Service Name** | `DAGExecutor` (`neuronium_agent/execution/executor.py`) |
| **Responsibility** | Детерминированное исполнение ActionGraph (DAG) с параллелизмом, retry, conditional branching. |
| **Business Logic** | Алгоритм Кана (topological sort) с deterministic tie-breaking (priority → node_id). Batch execution: выбирает ready nodes → исполняет до max_parallel → commit results в порядке node_id → update ready set. Retry с exponential backoff для transient failures. Conditional branch pruning для decision nodes. Interrupt handling для graceful pause. |
| **API / Contract** | `execute(graph: ActionGraph, nodes: dict, ...) → ExecutionOutcome { results, pending, interrupted }` |

#### Service 4: Planning System (HTN + DAG)

| Area | Fill In |
|------|---------|
| **Service Name** | Planning subsystem (`neuronium_agent/planning/`) |
| **Responsibility** | HTN-декомпозиция objective → ActionGraph (DAG). Поддержка нескольких planner backends через PlannerBackend protocol. |
| **Business Logic** | 1) `htn_recursive_v0` — рекурсивная HTN-декомпозиция: extraction pipeline → input resolution → missing field computation → method selection (rule-based + model-assisted) → subgoal expansion. 2) `legacy_dynamic_v1` — runtime graph generation через LLM. 3) Фиксированные templates (autofix demo: generate → execute → critic → fix → execute_fix → critic_fix). |
| **API / Contract** | `PlannerBackend.plan(request: PlannerRequest) → PlannerResult { graph: ActionGraph, trace: PlannerDecisionTrace }` |

#### Service 5: Node System (Typed Execution Units)

| Area | Fill In |
|------|---------|
| **Service Name** | Node subsystem (`neuronium_agent/nodes/`) |
| **Responsibility** | Типизированные исполнительные единицы DAG. Unified contract: `BaseNode.execute(NodeInput) → NodeOutput`. |
| **Business Logic** | 5 типов нод: **ModelNode** — LLM inference через OpenAI API (replay recording, structured output, temperature=0.0). **CodeNode** — Python execution в Docker sandbox (network off, timeout 120s, fallback на local). **McpToolNode** — MCP tool invocation через local transport с policy gates. **DecisionNode** — conditional branching evaluator. **AggregateNode** — merge upstream outputs. |
| **API / Contract** | Input: `NodeInput { inputs: dict, parameters: dict, context: NodeContext { execution_id, trace_id, retry_count, random_seed } }`. Output: `NodeOutput { outputs: dict, quality_signals: QualitySignals { confidence, tokens_used, latency_ms }, status: COMPLETED/FAILED/TIMEOUT, error, failure_class: TRANSIENT/PERSISTENT/SYSTEMIC/CRITICAL }` |

#### Service 6: Verification (Critics)

| Area | Fill In |
|------|---------|
| **Service Name** | Verification subsystem (`neuronium_agent/verification/`) |
| **Responsibility** | Оценка качества outputs нод. Critics assess but don't execute — report verdicts for system decisions. |
| **Business Logic** | v1: SimulatedCritic (stub, auto-PASS). Контракт готов для LLM-based evaluation. Critic types: demo_critic (autofix), business_critic (web/reports), generic_critic (general tasks), memory_critic (memory-augmented). |
| **API / Contract** | Input: `CriticInput { node_id, node_type, outputs, quality_signals, criteria }`. Output: `CriticVerdict { verdict: PASS/CONDITIONAL_PASS/FAIL/UNCERTAIN, confidence: float, reasoning: str, evidence: list, gaps: list }` |

#### Service 7: Memory (GraphRAG)

| Area | Fill In |
|------|---------|
| **Service Name** | Memory subsystem (`neuronium_agent/memory/`) |
| **Responsibility** | Персистентная память с GraphRAG: entity/relation graph + keyword/semantic search + provenance tracking. |
| **Business Logic** | MemoryStore ABC с SQLite и Postgres реализациями. Operations: upsert_chunk, get_chunk, list_chunks, search_keyword_topk, count_chunks. Tools: ingest_files (read → chunk → store), query (keyword + optional semantic → filter → evidence refs). Entity/relation model: MemoryEntity, MemoryRelation с GraphRAG-style traversal. |
| **API / Contract** | `MemoryStore.upsert_chunk(chunk_id, source_artifact_id, text, metadata, created_at)`, `search_keyword_topk(query, top_k) → list[dict]`, `MemoryQuery { query, mode: structured/hybrid/semantic/iterative, top_k, constraints }` |

#### Service 8: Recovery

| Area | Fill In |
|------|---------|
| **Service Name** | Recovery subsystem (`neuronium_agent/recovery/`) |
| **Responsibility** | Классификация ошибок и принятие решений о восстановлении. |
| **Business Logic** | Classifier: TRANSIENT (retry) / PERSISTENT (escalate) / SYSTEMIC (replan) / CRITICAL (halt). Policy: `decide_recovery()` — decision tree с retry limits (max_node_retries=3, max_stage_retries=2), escalation thresholds (repeated_rollback_threshold=3), verdict fix attempts. Rollback scope computation из DAG topology. |
| **API / Contract** | `decide_recovery(failure, history, config) → RecoveryDecision { action: RETRY_STAGE/REPLAN/ESCALATE/FAIL, scope: RollbackScope }` |

### 3.3 Data Architecture and Flows

| Area | Fill In |
|------|---------|
| **Main Entities (ER)** | **Run** (trace_id PK, execution_id, state, objective), **Artifact** (artifact_id PK, type, produced_by_node_ref, blob_key, quality_signals), **LineageEdge** (parent→child, kind), **TraceEvent** (event_id PK, trace_id, ts, kind, payload), **NodeExecution** (node_execution_id PK, trace_id, node_ref, attempt, status, inputs, outputs), **CriticEvaluation** (id PK, trace_id, input, verdict), **MemoryChunk** (chunk_id PK, source_artifact_id, text, metadata), **MemoryEmbedding** (chunk_id PK, vector, model) |
| **Relationships (ER)** | Run 1:N TraceEvent, Run 1:N NodeExecution, Run 1:N Artifact. Artifact N:N Artifact через LineageEdge (DAG). Artifact 1:N MemoryChunk. NodeExecution 1:N CriticEvaluation. MemoryChunk 1:1 MemoryEmbedding (optional). |
| **Data Flow (DFD)** | `User objective` → `Orchestrator (COMMIT)` → `PlannerBackend` → `ActionGraph (DAG)` → `DAGExecutor (EXECUTE)` → `Node execution (Model/Code/MCP)` → `NodeOutput artifacts` → `BlobStore (SHA-256 CAS)` + `IndexStore (metadata)` → `Critic evaluation (CONTROL)` → `CriticVerdict` → `RecoveryPolicy (ADAPT)` → `next stage or completion` → `TraceExporter` → `JSONL/JSON/ZIP` |
| **Input Sources** | 1) User objective (CLI/API), 2) OpenAI API (LLM responses), 3) Docker containers (code execution), 4) MCP tools (local transport), 5) Web (httpx + trafilatura), 6) Local filesystem (file ingestion) |

#### Storage Architecture (Dual-Layer)

**Blob Store (Content-Addressed, Immutable)**
- Default: Filesystem CAS (`FsCasStore`)
- Layout: `<root>/sha256/<p1p2>/<p3p4>/<artifact_id>.blob` + `.meta.json`
- Операции: create/read only (no update/delete)
- Integrity: SHA-256 content hash verification

**Index Store (Metadata, Searchable)**
- Default: SQLite (`SqliteStore`) — 9 таблиц: schema_version, runs, artifacts, lineage_edges, trace_events, node_executions, critic_evaluations, memory_chunks, memory_embeddings
- Production: PostgreSQL (`PostgresStore`) — структурно эквивалентен, JSON→JSONB, TEXT→TIMESTAMPTZ
- Migrations: встроенный мигратор, SQL-файлы, idempotent, auto-apply при старте

### 3.4 Infrastructure

| Area | Fill In |
|------|---------|
| **Minimum (Local Dev)** | Python 3.11+, OpenAI API key, ~50MB disk. Без Docker, Redis, Postgres. |
| **Docker Sandbox** | Docker daemon для CodeNode. Image: python:3.11-slim. Network off by default. CPU/RAM/timeout limits. `pip install -e ".[docker]"` |
| **Production** | PostgreSQL (index store + pgvector). Redis + RQ (async queue, worker processes). `pip install -e ".[postgres,redis]"` |
| **Semantic Search** | Option A: pgvector extension (HNSW/IVFFlat). Option B: local sentence-transformers (all-MiniLM-L6-v2) + bruteforce cosine в SQLite. `pip install -e ".[pgvector]"` или `".[embeddings]"` |
| **Configuration** | TOML file (`neuronium.toml`) + env vars (prefix `NEURONIUM_`) + CLI flags. Priority: CLI > env > TOML > defaults. Pydantic v2 validation. |
| **Security** | FS allowlists для tools, Docker network isolation, MCP policy gates (approval for destructive/exfiltration/high-cost), path traversal prevention, content-addressed immutable storage |
| **Observability** | Structured JSON logs (`{data_dir}/logs/neuronium.jsonl`), append-only trace events, decision records с outcome correlation, trace export (JSONL/JSON/ZIP) |
| **CI / Testing** | pytest >= 8.0, 52 test files, coverage >= 7.0. Determinism tests, replay tests, contract tests, integration tests. `pip install -e ".[dev]"` |

---

## 4. Work Plan

### Mapping: Use Case → Tasks

| Use Case | Task ID | Task | Dependencies | DoD | Subtasks |
|----------|---------|------|-------------|-----|----------|
| UC-1.1 | T-1 | Реализация batch execution pipeline (objective → plan → execute → result) | — | Пользователь запускает `neuronium-agent run -o "..."` и получает результат + trace | ST-1, ST-2, ST-3 |
| UC-1.2 | T-2 | Реализация interactive mode с pause/stop/resume | T-1 | Interactive stdin control работает с checkpoint/resume | ST-4, ST-5 |
| UC-2.1 | T-3 | Реализация control protocol (continue/pause/revise/replan/stop/escalate) | T-1 | Все 6 control-команд работают через CLI и Python API | ST-6, ST-7, ST-8 |
| UC-2.2 | T-4 | Реализация recovery и escalation policy | T-1, T-3 | Автоматическая recovery с классификацией ошибок и escalation при исчерпании | ST-9, ST-10 |
| UC-3.1 | T-5 | Реализация replay из trace | T-1 | Offline replay воспроизводит execution без внешних систем | ST-11, ST-12 |

---

## 5. Detailed Task Breakdown

### Task 1 — Batch Execution Pipeline

| Field | Fill In |
|-------|---------|
| **Task ID** | T-1 |
| **Related Use Case** | UC-1.1 |
| **Task Description** | Реализация полного pipeline: приём objective → HTN planning → ActionGraph → DAG execution → critic evaluation → artifact persistence → trace export. Включает: AgentRunner facade, Orchestrator core loop, DAGExecutor, node system (Model/Code/MCP), storage layer, trace recording. |
| **Dependencies** | Нет (базовый pipeline) |
| **DoD** | `neuronium-agent run -o "Write fibonacci" --trace-export trace.jsonl` успешно создаёт артефакт и trace. Все determinism tests проходят. |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|-------------|---------------------|
| ST-1 | Реализация конфигурации (TOML + env + defaults), типов (Pydantic DTOs), ошибок, canonical JSON, artifact ID generation | — | `load_config()` читает neuronium.toml, env override работает, canonical JSON стабилен, artifact IDs детерминированы |
| ST-2 | Реализация storage layer (BlobStore FS CAS + IndexStore SQLite), migrations, AgentState + Intention lifecycle | ST-1 | Артефакты сохраняются immutable, lineage edges корректны, migrations auto-apply, state transitions валидируются |
| ST-3 | Реализация Orchestrator (COMMIT→EXECUTE→CONTROL→ADAPT), DAGExecutor, Node system (ModelNode/CodeNode/McpToolNode/DecisionNode/AggregateNode), HTN planner, Critic, CLI `run` command, trace recorder/exporter | ST-1, ST-2 | End-to-end: objective → plan → execute → verify → result. Trace exportируется в JSONL. Parallel node execution с deterministic ordering. |

### Task 2 — Interactive Mode

| Field | Fill In |
|-------|---------|
| **Task ID** | T-2 |
| **Related Use Case** | UC-1.2 |
| **Task Description** | Реализация interactive execution mode с non-blocking stdin monitoring, interrupt handling, phase-boundary checkpointing, resume from checkpoint. |
| **Dependencies** | T-1 |
| **DoD** | `neuronium-agent run -o "..." --mode interactive` позволяет pause (Enter/p) и stop (q). Resume из checkpoint восстанавливает полное состояние. |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|-------------|---------------------|
| ST-4 | Реализация InterruptRequest model, interrupt callback в DAGExecutor, checkpoint creation/loading (phase-boundary), CLI interactive loop с threading model и non-blocking IO (select/msvcrt) | ST-3 | Interrupt корректно останавливает batch execution, checkpoint сохраняет полное состояние |
| ST-5 | Реализация resume: `neuronium-agent run --trace-id <id>`, загрузка checkpoint → восстановление AgentState → продолжение DAG с initial_results (completed nodes) | ST-4 | Resume продолжает с точки паузы, не переисполняет completed nodes, trace continuous |

### Task 3 — Control Protocol

| Field | Fill In |
|-------|---------|
| **Task ID** | T-3 |
| **Related Use Case** | UC-2.1 |
| **Task Description** | Реализация полного control protocol: 6 типов команд с корректной маршрутизацией в state transitions, NL feedback parsing, RFC6902 patch application, partial invalidation. |
| **Dependencies** | T-1 |
| **DoD** | Все 6 control-команд работают через CLI (`neuronium-agent control`) и Python API (`runner.control()`). Decision records записываются в trace. |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|-------------|---------------------|
| ST-6 | Реализация ControlCommand routing в Orchestrator: continue (resume scheduling), pause (checkpoint + suspend), stop (graceful termination), escalate (context package) | ST-3 | State transitions корректны, idempotent, trace recorded |
| ST-7 | Реализация revise: NL feedback → intent classification → RFC6902 patch (state_patch.py) → intention update с сохранением valid outputs → partial replan | ST-6 | Revise сохраняет completed branches, patch применяется корректно |
| ST-8 | Реализация replan: full plan invalidation → new HTN decomposition from current state, CLI `control` command, clarification flow (missing slots → grouped questions → user answers → patch) | ST-6, ST-7 | Replan создаёт новый ActionGraph, сохраняя evidence и patterns. Clarification UX группирует вопросы. |

### Task 4 — Recovery & Escalation

| Field | Fill In |
|-------|---------|
| **Task ID** | T-4 |
| **Related Use Case** | UC-2.2 |
| **Task Description** | Реализация failure classification, recovery policy, rollback scope computation, escalation triggers и verdict-driven local fix. |
| **Dependencies** | T-1, T-3 |
| **DoD** | Transient failures автоматически retry (до 3 раз). Persistent failures escalate. Repeated rollback (3+) triggers escalation. Verdict fix attempts (max 1) re-execute stage с critic feedback context. |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|-------------|---------------------|
| ST-9 | Реализация failure classifier (TRANSIENT/PERSISTENT/SYSTEMIC/CRITICAL), recovery policy (`decide_recovery()` decision tree), retry с exponential backoff, escalation thresholds | ST-3 | Classifier корректно категоризирует ошибки. Policy возвращает RETRY_STAGE/REPLAN/ESCALATE/FAIL по конфигурации. |
| ST-10 | Реализация rollback scope computation из DAG topology (affected node + transitive dependents), verdict local fix (re-execute stage с gaps/suggestions context), integration в Orchestrator ADAPT phase | ST-9 | Rollback scope вычисляется корректно (сохраняя independent branches). Verdict fix re-execute с контекстом critic feedback. |

### Task 5 — Replay from Trace

| Field | Fill In |
|-------|---------|
| **Task ID** | T-5 |
| **Related Use Case** | UC-3.1 |
| **Task Description** | Реализация offline replay: загрузка trace → injection recorded responses в ноды → детерминированное воспроизведение → валидация artifact identity. |
| **Dependencies** | T-1 |
| **DoD** | `neuronium-agent replay --trace-id <id>` воспроизводит execution без внешних вызовов. При divergence — explicit ReplayError. |

**Subtasks**

| Subtask ID | Description | Dependencies | Acceptance Criteria |
|------------|-------------|-------------|---------------------|
| ST-11 | Реализация ReplayProvider: парсинг trace events → extraction recorded responses по node_ref → `set_replay_responses()` для ModelNode/CodeNode/McpToolNode → node registry injection | ST-3 | Recorded responses корректно инжектируются в ноды по node_ref |
| ST-12 | Реализация replay execution: trace completeness validation → replay mode execution → artifact ID comparison (computed vs recorded) → divergence detection → ReplayError с диагностикой. CLI `replay` command. | ST-11 | Replay идентичен original execution. Divergence → explicit error. Incomplete trace → validation error before execution. |

---

## Appendix A: Configuration Reference

### neuronium.toml секции

| Section | Key Fields | Defaults |
|---------|-----------|----------|
| `[project]` | name, data_dir | "neuronium", ".neuronium" |
| `[determinism]` | canonical_json, default_random_seed, llm_temperature, strict | "neuronium-v1", 0, 0.0, false |
| `[runtime]` | mode, max_parallel_nodes, checkpoint_policy, pause_grace_period_seconds, stop_grace_period_seconds | "batch", 4, "on_transition", 30, 5 |
| `[storage]` | blob_backend, fs_cas_root, index_backend, sqlite_path, postgres_dsn | "fs_cas", ".neuronium/blobs", "sqlite", ".neuronium/index.sqlite3", null |
| `[queue]` | enabled, backend, redis_url, queue_name | false, "rq", null, "neuronium" |
| `[llm]` | provider, model, api_key_env, structured_output, timeout_seconds, max_retries | "openai", "gpt-4.1-mini", "NEURONIUM_OPENAI_API_KEY", true, 60, 2 |
| `[mcp]` | enabled, servers (name, url, timeout, policy) | true, [] |
| `[code_node]` | enabled, runtime, docker (enabled, image, network, limits) | true, "python", true, "python:3.11-slim", false |
| `[memory]` | enabled, graphrag_backend, semantic_search (backend, pgvector, local) | true, "sqlite", disabled |
| `[logging]` | level, json, path | "INFO", true, ".neuronium/logs/neuronium.jsonl" |
| `[recovery]` | max_node_retries, max_stage_retries, retry_backoff_base, allow_auto_replan, max_verdict_fix_attempts | 3, 2, 1.0, false, 1 |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `NEURONIUM_OPENAI_API_KEY` | API ключ OpenAI (обязательный для live execution) |
| `NEURONIUM_PROJECT_DATA_DIR` | Override data directory |
| `NEURONIUM_STORAGE_INDEX_BACKEND` | sqlite / postgres |
| `NEURONIUM_STORAGE_POSTGRES_DSN` | PostgreSQL connection string |
| `NEURONIUM_QUEUE_ENABLED` | true / false |
| `NEURONIUM_QUEUE_REDIS_URL` | Redis connection URL |
| `NEURONIUM_RUNTIME_MODE` | batch / supervised / interactive |
| `NEURONIUM_LLM_MODEL` | Override LLM model name |

---

## Appendix B: Built-in Runbooks

| Runbook ID | Description | Stages |
|------------|-------------|--------|
| `super_agent_v0` | Multi-stage pipeline с HTN recursive backend (default) | HTN decomposition → DAG execution → critic → adapt |
| `autofix_demo` | Two-iteration generate/fix loop | generate → execute → critic → fix → execute_fix → critic_fix |
| `docs_report_v1` | Read local docs → draft report with critic | read docs → generate report → critic evaluation |
| `dynamic_planner_demo_v1` | Legacy dynamic planner demo | LLM-generated plan → execute → verify |
| `htn_recursive_demo_v0` | HTN recursive planner demo | Recursive decomposition → execute → verify |
| `hybrid_memory_report_v1` | Memory-augmented report generation | ingest files → query memory → generate report |

---

## Appendix C: CLI Command Reference

| Command | Description | Key Flags |
|---------|-------------|-----------|
| `neuronium-agent run -o "..."` | Запуск агента | `--mode`, `--runbook`, `--config`, `--trace-export`, `-v`, `--summary`, `--raw-logs` |
| `neuronium-agent run --trace-id <id>` | Resume из checkpoint | `--mode` |
| `neuronium-agent status --trace-id <id>` | Проверка статуса | — |
| `neuronium-agent control --trace-id <id>` | Управление | `--command` (continue/pause/revise/replan/stop/escalate), `--payload` (JSON) |
| `neuronium-agent replay --trace-id <id>` | Replay (experimental) | — |
| `neuronium-agent schema` | Экспорт JSON Schema | — |
| `neuronium-agent worker` | Redis+RQ worker | — |

---

## Appendix D: Database Schema (SQLite/PostgreSQL)

### Tables

| Table | PK | Key Columns | Purpose |
|-------|-----|-------------|---------|
| `schema_version` | version (INT) | applied_at | Migration tracking |
| `runs` | trace_id | execution_id, state, objective, config_snapshot_json | Run metadata |
| `artifacts` | artifact_id | artifact_type, produced_by_node_ref, blob_key, quality_signals_json, deprecated_at | Artifact index |
| `lineage_edges` | (parent, child, kind) | created_at | Provenance DAG |
| `trace_events` | event_id (AUTO) | trace_id, ts, kind, span_id, payload_json | Append-only execution log |
| `node_executions` | node_execution_id | trace_id, node_ref, attempt, status, inputs/outputs/error_json | Node-level tracking |
| `critic_evaluations` | critic_evaluation_id | trace_id, ts, input_json, verdict_json | Verification audit |
| `memory_chunks` | chunk_id | source_artifact_id, text, metadata_json | GraphRAG chunks |
| `memory_embeddings` | chunk_id (FK) | vector_json, vector_dim, embedding_model | Semantic search vectors |

---

## Appendix E: Roadmap (Post-Current State → Full IBS)

| Phase | Focus | Key Deliverables |
|-------|-------|-----------------|
| **A** | Invariants Hardening | Canonical JSON policy, replay completeness audit, strict determinism tests |
| **B** | Domain & Contract Completion | Schema versioning, reference payload tests, backward compatibility suite |
| **C** | Planning & Execution Maturity | HTN method ranking, critical path scheduling, partial invalidation, conditional branching |
| **D** | Verification Layer 2.0 | Formal critic contracts, PASS/CONDITIONAL_PASS/FAIL/UNCERTAIN, deficiency severity, uncertainty handling |
| **E** | Memory Full Stack | Entity/relation graph model, unified query interface, retrieval loop state machine (PLAN→RETRIEVE→VALIDATE→SYNTHESIZE→DECIDE) |
| **F** | CLI Runtime & Operational Readiness | Batch/supervised/interactive parity, full pause/resume cycle, trace export/replay workflow, observability |

**Execution order:** A → B → C+D (parallel) → E → F

**Definition of Done:** All phase acceptance criteria met, strict replay stable, artifact lineage immutable and verifiable, verification layer works by formal contracts, memory works in all modes with provenance, CLI provides full managed execution cycle.
