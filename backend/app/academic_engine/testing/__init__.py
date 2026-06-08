"""
academic_engine/testing/__init__.py
=====================================
Adversarial Academic Document Testing Framework.

Production hardening suite for the Layout Intelligence Engine.

Modules:
  adversarial_generator  — 14 degradation transforms on a clean source image
  degradation_pipeline   — Compose and batch degrade documents
  robustness_runner      — Run all variants through adaptive pipeline, collect metrics
  extraction_benchmark   — Field accuracy scoring + robustness score
  failure_clustering     — Group failures by degradation type and document region
  metrics_dashboard      — Report generation + auto-tuning recommendations
"""

__version__ = "1.0.0"
