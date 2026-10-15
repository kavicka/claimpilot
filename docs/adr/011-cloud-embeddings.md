# ADR-011: Cohere Embed Multilingual v3 for retrieval in the cloud

Status: accepted, 2026-10-15

## Decision
The AWS deployment embeds policy clauses and queries with `cohere.embed-multilingual-v3` on
Bedrock, in-Region in eu-central-1. Documents use `input_type: search_document`, queries
`search_query`. The reranker (bge-reranker-v2-m3) keeps running inside the worker.

## Why
- 1024 dimensions, the size of bge-m3's vectors, so the pgvector column and index stay as they
  are.
- It runs in-Region in Frankfurt; Cohere Embed v4 needs the `eu.` profile.
- It covers the claim languages (sk, cs, de, it, hr, en). Titan Text Embeddings V2 lists them as
  preview and warns about cross-language queries, which this corpus has (Slovak terms, German and
  Italian invoices).
- The embedded text is the synthetic policy terms and redacted queries, so no personal data
  reaches it.

## Consequences
- Switching embedding models means rebuilding the clause index (`build_index`), not migrating
  the schema. Vectors from bge-m3 and Cohere must never be mixed in one index.
- Retrieval numbers (recall@5 45/53 on dev) are for bge-m3; the Cohere numbers come with the
  first eval run on a Bedrock account.
