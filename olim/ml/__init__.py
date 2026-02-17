"""
ML Models Management System

This package provides a comprehensive ML models management system with dedicated database tables for
models, versions, and predictions (decoupled from Labels)
"""

from .models import MLModel, MLModelPrediction, MLModelVersion, MLTrainingJob
from .services import MLModelService

__all__ = ["MLModel", "MLModelPrediction", "MLModelService", "MLModelVersion", "MLTrainingJob"]
