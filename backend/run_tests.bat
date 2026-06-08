@echo off
echo ============================================================
echo   DOC-VALIDATOR — STAGE ISOLATION TESTS
echo ============================================================
echo.
echo Running: Validation Stage Tests
"z:\doc-validator 2\doc-validator\backend\venv\Scripts\python.exe" -m pytest tests/test_validation.py -v --tb=short
echo.
echo Running: Semantic Stage Tests
"z:\doc-validator 2\doc-validator\backend\venv\Scripts\python.exe" -m pytest tests/test_semantic.py -v --tb=short
echo.
echo ============================================================
echo   To run ALL tests (including OCR/Vision - needs images):
echo   python -m pytest tests/ -v
echo ============================================================
pause
