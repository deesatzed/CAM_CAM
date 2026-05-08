# CAM-RAG Integration Contract

CAM-RAG remains a separate specialist package for grounded retrieval, citations,
corpus strategy, reranking, and RAG benchmarking. CAM_CAM integrates it through a
thin optional adapter instead of copying the whole codebase.

## Install For Local Integration

```bash
pip install -e ../CAM-RAG
```

or:

```bash
PYTHONPATH=../CAM-RAG/src:$PYTHONPATH python -m pytest tests/test_cam_rag_adapter.py -q
```

## CAM_CAM Contract

The bridge lives at `src/claw/memory/cam_rag_bridge.py` and exposes:

- `ingest_documents()` for normalized text payloads
- `ingest_folder()` for conservative `.md`, `.txt`, and `.rst` folder ingestion
- `retrieve()` for grounded chunks with citations and confidence
- `receipt_for()` for machine-readable evidence CAM can store with task output

CAM_CAM tests pass without CAM-RAG installed. When CAM-RAG is available, the same
adapter can call `cam_rag.DeterministicRetriever` and normalize results back into
CAM_CAM receipts.

## Physical Merge Rule

Do not physically merge CAM-RAG into `src/claw` until:

1. The adapter has been used by at least one CAM_CAM showpiece.
2. CAM-RAG's local dirty changes are reconciled.
3. CAM-RAG benchmarks and tests are green.
4. The default CAM_CAM install genuinely requires RAG behavior.
