"""
Document processing, in the order a file meets it.

    pipeline.py     orchestrates one upload end to end (also export.py for the downloadable JSON, usage_tracker.py for token use)
    reading/        PDF to page text: pdf_pages, tess (text layer for scans), ocr (two-reader transcription), router, locate, table_extractor
    extraction/     page text to values: form_extractor (templates), discover (no template), digital (code reads digital pages),
                    kv, remainder, checkboxes, adjudicate, normalize, labels
    documents/      what a document is: classify, template_draft, suggest, workspace_types
    quality/        validation (per-document rules), cross (consistency across documents)

How scanned pages are read, and by which engine or model, lives in app/engines.
"""
