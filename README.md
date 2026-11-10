# Personal AI Brain

**A local-first, privacy-preserving memory and context infrastructure for personal AI.**

[![CI](https://github.com/raphael2025/personal-ai-brain/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/raphael2025/personal-ai-brain/actions/workflows/ci.yml) [![CodeQL](https://github.com/raphael2025/personal-ai-brain/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/raphael2025/personal-ai-brain/actions/workflows/codeql.yml) [![Secret Scanning](https://github.com/raphael2025/personal-ai-brain/actions/workflows/secret-scan.yml/badge.svg?branch=main)](https://github.com/raphael2025/personal-ai-brain/actions/workflows/secret-scan.yml)

Personal AI Brain aims to make a person's digital knowledge usable across multiple AI assistants without uploading an entire archive or placing every memory into a model context window.

The system is designed around four principles:
1. **Local-first:** original files and derived indexes remain under the user's control.
2. **Progressive retrieval:** retrieve concise summaries first, then load deeper evidence only when needed.
3. **Provenance by default:** every extracted fact should be traceable to its source and version.
4. **Explicit permissions:** external models and tools receive only the context a user authorizes.

> **Project status: pre-alpha / Phase 2 foundations.** The Asset Registry, local worker/extraction path, bounded BM25 search over extracted artifacts, and initial memory lifecycle foundation are implemented. Policy enforcement, authenticated clients, multi-node operations, and broad format support remain under development. Do not use it as a production personal archive.

## 项目说明

这是一个本地优先的个人数字资产与 AI 记忆基础设施项目。目标不是把所有文件上传给某个模型，而是先登记和理解用户自己的数字资产，再按需向不同 AI 提供经过授权、可追溯的上下文。

核心原则：
- 原始文件留在用户自己的设备或存储中，默认只读。
- 热知识可快速调用，冷知识保留索引、按需激活。
- 摘要、向量和知识图谱都是派生数据，不能替代原始证据。
- 多个 AI 客户端共享同一套受权限控制的记忆接口。
- 当前仍处于早期开发阶段，不应承载生产环境的个人敏感档案。

## 从这里开始

- **[系统总蓝图 v1](docs/architecture/system-blueprint.md)**：系统边界、组件、数据流、状态机、API、安全、部署拓扑。
- **[模块接口契约](docs/architecture/module-contracts.md)**：模块依赖方向、核心端口、错误码和测试约定。
- **[数据生命周期](docs/architecture/data-lifecycle.md)**：资产、版本、派生数据、记忆与删除规则。
- **[权限与上下文安全](docs/architecture/context-and-policy.md)**：身份、授权、外部模型数据出口。
- **[实施地图](docs/development/implementation-map.md)**：P0–P3 工作包、依赖顺序和验收标准。
- **[Asset Registry CLI 使用说明](docs/development/registry-service.md)**：数据库迁移、根目录登记、扫描命令及当前限制。
- **[Durable Jobs 与 Worker Lease](docs/development/durable-jobs.md)**：任务幂等、能力匹配、租约、fencing、重试和取消。
- **[Extraction Foundation](docs/development/extraction.md)**：首个受限 UTF-8 文本/Markdown 提取器及当前安全边界。
- **[Local Worker Operations](docs/development/worker-operations.md)**：Worker 注册、根目录授权、任务入队、挂载配置和本地运行。
- **[Persisted Lexical Search](docs/development/persisted-search.md)**：基于已提取文本的本地 BM25 搜索与限制。
- **[Explicit Memory Lifecycle v1](docs/development/memory-lifecycle.md)**：记忆来源、状态、证据引用、确认和审计语义。
- [项目状态](PROJECT_STATUS.md) · [完整文档索引](docs/README.md) · [路线图](ROADMAP.md)

## Goals

- Inventory files across computers, NAS devices, and removable storage.
- Identify files consistently and track changes without modifying originals.
- Extract searchable text and metadata from documents, code, images, audio, and video.
- Support hybrid retrieval across lexical, semantic, temporal, and relationship signals.
- Maintain long-term memory with progressive disclosure and evidence links.
- Expose a controlled API and MCP interface to multiple AI clients.
- Run workers across a low-power always-on node and higher-performance compute nodes.

## Non-goals

- Replacing the user's filesystem or becoming the canonical store for original files.
- Sending an entire personal archive to a cloud model.
- Treating generated summaries or embeddings as unquestionable facts.
- Automatically modifying, deleting, or reorganizing original user files.

## Architecture direction

The initial design is a modular monolith with independently runnable workers:
- Asset Registry: discovery, stable identity, metadata, versions, locations.
- Ingestion Workers: parsing, OCR, transcription, code analysis, extraction.
- Memory Manager: summaries, importance, activation, decay, lifecycle.
- Context Manager: query planning, permission checks, context budgeting, progressive loading.
- Retrieval: lexical, vector, metadata, temporal retrieval, evidence ranking.
- Provenance & Audit: source references, transformation history, model/version metadata, access logs.
- Connectors: local filesystems, NAS, AI clients, optional model gateways.

## Development principles

- Original files are read-only by default.
- Derived data must be rebuildable from source files and recorded processing versions.
- Every worker must be idempotent and resumable.
- Every extracted claim must retain provenance.
- No secrets, personal archives, customer data, or machine-specific paths belong in this public repository.
- Integrations must be validated against pinned versions; proposals must be labelled as proposals.

## Quick start

The initial developer CLI requires PostgreSQL and manually applied migrations:

    python -m pip install -e ".[postgres,dev]"
    read -rsp "PAB_DATABASE_URL: " PAB_DATABASE_URL; echo; export PAB_DATABASE_URL
    for migration in infrastructure/postgres/migrations/000*.sql; do
        psql "$PAB_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
    done

For SMB/NFS roots, pass a local mount path with pab scan <root-uuid> --path /mnt/share. See [Registry Service and CLI](docs/development/registry-service.md) and [Local Worker Operations](docs/development/worker-operations.md).

Example registry operations:

    pab root add --name "Documents" --uri "file:///home/user/Documents" --kind local --case-sensitive yes
    pab root list
    pab scan <root-uuid>

Example worker operations:

    pab worker register --worker-id <worker-uuid> --name "text worker" --capability text
    pab worker grant-root --worker-id <worker-uuid> --root-id <root-uuid> --actor operator
    pab extract enqueue --asset-version-id <version-uuid> --root-id <root-uuid>
    pab worker run --worker-id <worker-uuid> --mounts-config /etc/pab/worker-mounts.toml --once

Example local search:

    pab search "project release owner" --limit 10
    pab search "project release owner" --document-type md

Run the synthetic lexical retrieval benchmark (no database required):

    python -m personal_ai_brain.evaluation.benchmark evaluation/datasets/synthetic-v1 --output benchmark-results/bm25-synthetic-v1.json

This is a developer preview, not a supported general-purpose installer. Actor strings are audit metadata, not authentication; do not expose local search or memory confirmation through an unauthenticated API/MCP endpoint.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), then start with the [Implementation Map](docs/development/implementation-map.md). Work packages are ordered by dependency: Asset Registry and durable jobs first, extraction/retrieval next, then memory/policy, and finally API/MCP/UI and multi-node operations.

Do not build against undocumented assumptions. If an interface needs to change, update the contract and tests in the same PR. Never include personal data, secrets, or real user archives.

## License

Apache License 2.0. See [LICENSE](LICENSE).
