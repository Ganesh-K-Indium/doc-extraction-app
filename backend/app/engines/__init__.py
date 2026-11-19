"""
How pages get read, and by whom.

    providers/   language and vision models: llm (one call to OpenAI, Anthropic, Gemini, Ollama or a custom server) and credentials
                 (the keys saved in the Settings page, encrypted)
    ocr/         local OCR engines: local (Tesseract, RapidOCR, PaddleOCR, docTR, and judging whether a reading is good enough), isolated
                 (runs the neural ones in a process of their own), prepare (model downloads), sample (the built-in test page)
    strategy/    plan (Economy / Balanced / Accuracy / Custom, per workspace) and ladder (read one page: local first, models only if doubtful)

Two command-line entry points stay at this level so their commands are stable:
    python -m app.engines.warmup    check the engines and download their models
    python -m app.engines.worker    the process a neural engine runs in (started by ocr/isolated.py, not run by hand)
"""
