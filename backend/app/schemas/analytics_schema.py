"""
app/schemas/analytics_schema.py — Pydantic schemas for analytics API
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class DashboardParams(BaseModel):
    period:     str = Field("week", description="today | week | month | all")
    trend_days: int = Field(14, ge=7, le=90)


class TrendParams(BaseModel):
    period:    str = Field("daily", description="daily | weekly | monthly")
    days:      int = Field(30, ge=7, le=365)


class AlertResolveRequest(BaseModel):
    alert_id: str
