# Streamlit Pipeline Console Design

## 1. Goal

Integrate the entity-extraction pipeline into the existing Streamlit dashboard so the user starts only Streamlit, configures one experiment in the browser, runs or safely cancels it, and observes its progress and persisted outputs in real time.

The feature must:

- accept a local document folder path and preview selectable `.md` and `.txt` files;
- support Zhipu, DeepSeek, Ollama, Alibaba Model Studio/Qwen, ModelScope, Hugging Face, and a custom OpenAI-compatible endpoint;
- read provider credentials from `.env` first and allow a session-only override;
- never persist API keys in MySQL, experiment snapshots, logs, events, or error messages;
- use the current Markdown-heading-aware chunking strategy with a configurable maximum length of `2000` by default;
- run the pipeline inside the Streamlit process in a background thread;
- show structured progress, counts, current work, errors, and final status;
- support cooperative cancellation while preserving all data already written;
- keep the existing experiment history and inspection pages.

## 2. Non-goals

- Supporting multiple simultaneous experiments in one Streamlit process.
- Adding alternative chunking strategies in the first version.
- Uploading or copying source documents through the browser.
- Persisting API keys from the UI.
- Building a distributed job queue or a separate backend service.
- Replacing MySQL, Milvus, SentenceTransformer, or the current extraction prompts.

## 3. Chosen Architecture

The application will use a typed run configuration, a structured event callback, a cooperative cancellation token, and a process-local run registry.

```text
Streamlit configuration form
          |
          v
  validate PipelineConfig
          |
          v
 Background PipelineWorker -----> CancellationToken
          |
          +---- run_pipeline(config, emit, token)
          |               |
          |               +---- MySQL experiment records
          |               +---- Milvus segment vectors
          |               +---- existing debug artifacts
          |
          v
 thread-safe PipelineEvent queue
          |
          v
 Streamlit status fragment (poll every second)
```

Only one worker may be active at a time. The registry survives Streamlit script reruns and holds the worker thread, event queue, cancellation token, immutable sanitized configuration, and accumulated public status. It does not hold API keys after the worker finishes.

## 4. Component Boundaries

### 4.1 Run configuration

Create a focused configuration module containing:

- `PipelineConfig`: immutable values for one experiment;
- `LLMConfig`: provider id, display name, API key, base URL, and model;
- `ChunkingConfig`: strategy id and maximum characters;
- validation helpers;
- a `sanitized_snapshot()` method that omits credentials.

The pipeline will receive `PipelineConfig` explicitly. Existing environment-backed settings remain the source of defaults for CLI compatibility, MySQL, Milvus, schema paths, embedding model paths, and debug directories.

### 4.2 Provider registry

Create a provider registry with these stable ids:

| Provider | Default base URL | Credential environment variable |
|---|---|---|
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4/` | `ZAI_API_KEY`, then legacy `LLM_API_KEY` |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY`, then legacy `LLM_API_KEY` |
| `ollama` | `http://localhost:11434/v1/` | no secret required; use internal placeholder |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| `modelscope` | editable deployment endpoint | `MODELSCOPE_API_TOKEN` |
| `huggingface` | `https://router.huggingface.co/v1` | `HF_TOKEN` |
| `custom` | current `LLM_BASE_URL` value | `LLM_API_KEY` |

Provider selection fills the default base URL but never locks it. Model names remain editable because availability changes independently of the application. ModelScope uses a user-editable endpoint because online inference deployments can expose different URLs.

All listed providers are called through the existing OpenAI Python client and its chat-completions interface. A clear compatibility error is shown when a selected endpoint does not implement that interface.

### 4.3 Document discovery

Document discovery is a pure function that:

1. expands and resolves the entered local path;
2. verifies that it is a readable directory;
3. scans only its immediate children, matching current pipeline behavior;
4. returns sorted `.md` and `.txt` file metadata;
5. never creates a missing input directory.

The UI displays file name, extension, byte size, and selection state. The selected relative file names are copied into `PipelineConfig`; the worker revalidates them before reading to protect against stale UI state.

### 4.4 Chunking

The existing Markdown-heading-aware algorithm remains the only strategy in this release. `LongDocLLMEntityExtractor` receives `max_chunk_size` from `ChunkingConfig` instead of setting `2000` internally.

The UI labels the strategy as “Markdown 标题感知（当前默认）” and exposes maximum characters with:

- default: `2000`;
- minimum: `200`;
- maximum: `20000`;
- step: `100`.

The selected value is stored in the sanitized experiment configuration snapshot and all produced chunks continue to be recorded in MySQL.

### 4.5 Pipeline events and cancellation

`PipelineEvent` contains:

- timestamp;
- level: `info`, `success`, `warning`, or `error`;
- type;
- pipeline stage;
- human-readable message;
- optional run id, document name, completed count, total count, and numeric metrics.

Event types cover run start, document scan, document start/end, chunking, entity extraction, alignment, retrieval, triplet generation, persistence, cancellation, failure, and run completion.

`CancellationToken` wraps a thread-safe event. The pipeline checks it:

- before each document;
- before and after each extraction chunk request;
- before each entity-alignment group request;
- before each entity retrieval/triplet request;
- before final correction and persistence boundaries.

An in-flight HTTP request is not forcibly interrupted. Cancellation takes effect at the next safe boundary, prevents new LLM calls, closes storage clients, and sets the experiment and active document to `cancelled`.

### 4.6 Run registry

The process-local registry exposes:

- `start(config)`;
- `request_cancel()`;
- `snapshot()`;
- `drain_events()`;
- `is_running`.

`start` is protected by a lock and rejects a second active experiment. The worker catches all top-level exceptions, emits a terminal event, and always clears sensitive values and releases the active-run lock.

The registry is created with Streamlit resource caching so normal script reruns do not lose the active thread. A full Streamlit process restart cannot resume the Python thread; persisted MySQL records remain available for diagnosis and are not claimed as resumable jobs.

## 5. Streamlit Information Architecture

Add “运行实验” as the default navigation page and retain:

- 实验总览;
- 实验批次;
- 文档追踪;
- LLM 调用;
- 知识图谱.

The run page uses the approved layout:

### Left configuration column

- experiment name;
- local folder path;
- scan/refresh action;
- file preview and per-file selection;
- provider selector;
- model input;
- editable base URL;
- masked API key override and environment-configuration indicator;
- current chunking strategy and maximum size;
- expandable advanced settings for retrieval count, breakpoint filtering, and cache reuse;
- start and stop controls.

MySQL and Milvus operational configuration remains environment-based. Existing read-only MySQL controls may remain on history pages, but credentials are not copied into experiment events.

### Right monitoring column

- terminal status banner;
- overall document progress;
- current document and current stage;
- metrics for processed documents, chunks, raw/aligned entities, LLM calls, and final triplets;
- stage timeline;
- bounded real-time event log showing the newest events first;
- on completion, the run id and a direct action to inspect the persisted experiment.

The monitoring fragment refreshes once per second only while a run is active. Static history pages do not continuously rerun.

## 6. Execution and Persistence Flow

1. The user enters a path and scans it.
2. The UI previews eligible files and the user selects the experiment input.
3. The user chooses provider, endpoint, model, and chunk size.
4. Start performs local validation and verifies that MySQL and Milvus can initialize when enabled.
5. The registry starts one background worker.
6. The worker creates a MySQL experiment run using only the sanitized configuration.
7. Each selected document runs through loading, chunking, entity extraction, entity alignment, retrieval, triplet generation, correction, and persistence.
8. Each stage emits structured events and updates counters.
9. Per-document failures are recorded and processing continues with the next selected document.
10. The run ends as `completed`, `completed_with_errors`, `cancelled`, or `failed`.
11. Storage clients close in `finally`, the API key is cleared from worker state, and the UI links to the persisted run.

The existing command-line entry point remains functional by constructing `PipelineConfig` from environment-backed defaults and calling the same pipeline core.

## 7. Error Handling and Security

### Validation errors

Before starting, reject:

- missing, unreadable, or non-directory input paths;
- no eligible or no selected files;
- selected files outside the resolved input directory;
- missing provider credentials, except for Ollama;
- blank model names or base URLs;
- chunk sizes outside the supported range.

### Runtime errors

- Infrastructure initialization failures are fatal and produce a `failed` run when a run id exists.
- A document failure marks that document `failed`, emits a sanitized message, and allows later documents to continue.
- LLM request failures continue to use the existing recorder path so prompt and response metadata remain available when safe.
- UI errors include the failed stage and a practical next action without exposing secrets.

### Secret handling

- Password inputs use Streamlit password fields.
- Environment values are represented as “configured” rather than rendered.
- `PipelineConfig.sanitized_snapshot()` maintains an explicit allowlist of persisted fields.
- Event payloads do not accept arbitrary configuration dictionaries.
- Exception rendering passes through a redactor for known credential values and common authorization-header patterns.
- API keys are not written to MySQL, Milvus, debug JSON, logs, or the browser.

## 8. Testing Strategy

Use test-driven development for each behavior.

### Unit tests

- provider defaults and environment fallback order;
- Ollama placeholder behavior;
- configuration validation;
- secret redaction and sanitized snapshots;
- document discovery, sorting, extension filtering, and path containment;
- current chunking behavior at the default and a custom maximum size;
- event construction and metric accumulation;
- cancellation-token checks;
- registry single-run locking and cleanup.

### Pipeline tests

Use in-memory persistence, a null vector store, deterministic fake LLM clients, and temporary documents to verify:

- expected stage event order;
- selected-file filtering;
- completed and completed-with-errors status;
- cancellation before a document and between LLM operations;
- partial data remains available after cancellation;
- no credential appears in snapshots or events.

### UI logic tests

Keep scanning, provider resolution, form-to-config conversion, event reduction, and status presentation outside Streamlit widget code so they can be tested without a browser.

### Verification

- run the full test suite in `env_agent`;
- compile the package;
- run `git diff --check`;
- start Streamlit headlessly and confirm the server reaches its ready state;
- when a chat-capable Ollama model or online-provider credential is available, perform a manual local smoke run with one small document; otherwise report that live-provider verification was not run.

## 9. Acceptance Criteria

The feature is accepted when:

1. `streamlit run kg_extract_build/dashboard.py` is the only application command required.
2. A user can scan a local folder, preview eligible files, and select a subset.
3. The approved providers appear with editable model and endpoint fields.
4. Credentials load from `.env` or a session-only password input and never appear in persisted or displayed diagnostic data.
5. The default heading-aware chunker produces the same output at size `2000` as before the change.
6. Starting an experiment runs the existing pipeline and updates progress without starting a second command.
7. Stop prevents subsequent work at the next safe boundary and persists `cancelled`.
8. Existing experiment history and knowledge-graph pages continue to work.
9. Automated tests, compilation, diff checks, and the Streamlit startup smoke test pass.
