# Evaluation Plan

## Purpose

Compare memory/context approaches using the same local corpus and labelled questions. Do not choose a production architecture from feature lists alone.

## Candidate tracks

1. Conventional baseline: PostgreSQL metadata + lexical search + vector retrieval.
2. OpenViking: progressive context and retrieval experiment.
3. MemOS: long-term memory experiment.
4. Cognee: entity/relationship extraction experiment, evaluated as a complementary subsystem.

Each track must record exact versions, configuration, hardware, model identifiers, and data preparation steps.

## Corpus design

Build a synthetic or explicitly consented benchmark corpus before ingesting personal archives. A proposed 10,000-file mix:

- 2,500 PDF and office documents
- 1,500 code files/repositories
- 2,000 images
- 500 audio/video assets
- 1,000 web/HTML files
- 500 archives
- 1,500 Markdown/text files
- 500 other files

## Query set

Create 100 human-labelled questions covering:
- exact fact recall;
- temporal and historical recall;
- cross-file synthesis;
- entity and relationship lookup;
- source-span/evidence location;
- conflicting or superseded facts;
- cold-knowledge activation;
- permission-denied retrieval.

Each answer must include expected source IDs and evidence spans where applicable.

## Metrics

- Recall@5 and Recall@10
- MRR
- P50/P95 latency
- evidence attribution accuracy
- unsupported/false memory rate
- token and context size
- incremental update latency
- consistency after rename, move, disconnect, and reconnect
- recovery after worker/API restart
- external network egress under deny policy

## Reproducibility

Store benchmark definitions and anonymized fixtures in the repository. Never commit private personal files. Publish raw measurements alongside summary claims. A benchmark result is invalid without the tested commit, dependency lock, hardware, configuration, and run instructions.
