# Personal AI Brain

**A local-first, privacy-preserving memory and context infrastructure for personal AI.**

Personal AI Brain aims to make a person's digital knowledge usable across multiple AI assistants without uploading an entire archive or placing every memory into a model context window.

The system is designed around four principles:

1. **Local-first:** original files and derived indexes remain under the user's control.
2. **Progressive retrieval:** retrieve concise summaries first, then load deeper evidence only when needed.
3. **Provenance by default:** every extracted fact should be traceable to its source and version.
4. **Explicit permissions:** external models and tools receive only the context a user authorizes.

> **Project status: early design / Phase 0.** This repository is being initialized. Architecture proposals and integrations are not production-ready until implemented and tested.

## 项目说明（中文）

这是一个本地优先的个人数字资产与 AI 记忆基础设施项目。目标不是把所有文件上传给某个模型，而是先登记和理解用户自己的数字资产，再按需向不同 AI 提供经过授权、可追溯的上下文。

核心原则：
- 原始文件留在用户自己的设备或存储中，默认只读。
- 热知识可快速调用，冷知识保留索引、按需激活。
- 摘要、向量和知识图谱都是派生数据，不能替代原始证据。
- 多个 AI 客户端共享同一套受权限控制的记忆接口。
- 项目目前处于 Phase 0，尚未达到可用于真实个人档案的生产状态。

文档入口：[中文/英文架构文档](docs/README.md) · [开发路线图](ROADMAP.md) · [参与贡献](CONTRIBUTING.md)

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

- **Asset Registry:** source discovery, stable identity, metadata, versions, storage locations.
- **Ingestion Workers:** format-specific parsing, OCR, transcription, code analysis, and extraction.
- **Memory Manager:** summaries, importance, activation, decay, and memory lifecycle.
- **Context Manager:** query planning, permission checks, context budgeting, and progressive loading.
- **Retrieval:** lexical + vector + metadata + temporal retrieval, with evidence ranking.
- **Provenance & Audit:** source references, transformation history, model/version metadata, and access logs.
- **Connectors:** local filesystems, NAS, AI clients, and optional external model gateways.

See [the architecture overview](docs/architecture/overview.md) and [the roadmap](ROADMAP.md).

## Development principles

- Original files are read-only by default.
- Derived data must be rebuildable from source files and recorded processing versions.
- Every worker must be idempotent and resumable.
- Every extracted claim must retain provenance.
- No secrets, personal archives, customer data, or machine-specific paths belong in this public repository.
- Integrations must be validated against pinned versions; proposed integrations must be labelled as proposals.

## Quick start

There is no supported installation yet. Phase 0 will establish the repository structure, local development environment, asset registry, and evaluation baseline before publishing deployment instructions.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), check the roadmap, and open an issue before making large architectural changes.

Good starting points:
- [Define StorageRoot and AssetLocation models](https://github.com/raphael2025/personal-ai-brain/issues/1)
- [Implement safe directory discovery](https://github.com/raphael2025/personal-ai-brain/issues/2)
- [Expand file identity tests](https://github.com/raphael2025/personal-ai-brain/issues/3)
- [Create a synthetic evaluation corpus](https://github.com/raphael2025/personal-ai-brain/issues/4)
- [Review memory/retrieval technology choices](https://github.com/raphael2025/personal-ai-brain/issues/5)

Please keep contributions evidence-based. Proposed integrations must not be described as working until tested. See [DEVELOPMENT.md](DEVELOPMENT.md) for contributor setup and [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md) for the Chinese contribution guide.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
