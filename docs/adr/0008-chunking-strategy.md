# ADR 0008: Heading-aware chunking

- Status: Accepted
- Date: 2026-11-09

## Context

Retrieval quality depends on how documents are split. Two strategies were built and measured on
the 75-item golden set against the 34 synthetic demo documents (see
[evaluation report](../evaluation-report.md)): fixed windows of 512 tokens with 50 overlap, and
heading-aware chunks.

## Decision

The default chunker is **heading-aware**: target about 400 tokens, 50 overlap, hard maximum 600,
minimum 60. Blocks are grouped under their heading path, long sections are split on paragraph and
sentence boundaries, and each table row is a block packed with the rest of its section. The heading path (for example
`Kebijakan Keluhan > Prosedur`) is prepended to the chunk text, so the embedding and the
full-text index both see the section a passage belongs to, and the citation can show it.
The fixed chunker stays available (`chunker_name="fixed"`) for experiments.

## Evidence

| Chunker | Recall@5 | Faithfulness | Answerable questions answered at threshold 0.60 |
|---|---|---|---|
| fixed 512 | 1.000 | 1.000 | 50 of 60 |
| heading | 0.983 | 0.996 | 57 of 60 |

The Recall@5 and faithfulness gaps are one question of 60 and do not show that either chunker
retrieves better. They do not support the choice by themselves. The reasons for heading-aware
chunking are structural: citations carry a section path, procedures stay together under their
heading, and cosine similarity of heading chunks sat above the calibrated relevance threshold more
often (57 versus 50 answered). The relevance threshold was calibrated on heading chunks; another
chunker needs its own calibration.

## Consequences

- Chunk text includes the section path, which costs a few tokens per chunk.
- Weak spots: PDF headings are guessed from short lines (under 60 characters) and plain-text ones
  by a similar heuristic, so a PDF without clear headings ends up as one large section split by
  size, close to fixed chunking; DOCX tables become one block per row, so a split table loses its
  header row; the token count is an estimate, not the embedding model's tokenizer.
- Changing the chunker or its sizes changes every chunk, so it needs a re-ingest of all documents.
