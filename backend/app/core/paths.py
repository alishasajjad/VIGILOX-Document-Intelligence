from pathlib import Path


# ==========================================================
# PROJECT PATHS
# PHASE 8.1
# ==========================================================
#
# WHY THIS MODULE EXISTS
# ----------------------------------------------------------
#
# Before Phase 8, path resolution was inconsistent:
#
#     the dashboard directory was resolved relative to
#     src/api/main.py
#
#     the managed storage root defaulted to the
#     CWD-relative Path("storage") / "documents"
#
# A CWD-relative default silently changes meaning depending
# on where the process was launched from. That is acceptable
# by accident when every runner happens to start in the
# project root, and wrong as soon as one does not.
#
# This module provides a single deterministic anchor so every
# project-relative path resolves identically regardless of
# the current working directory.
#
#
# ANCHOR
# ----------------------------------------------------------
#
#     backend/app/core/paths.py
#       parents[0] -> backend/app/core
#       parents[1] -> backend/app
#       parents[2] -> backend
#       parents[3] -> <project root>
# ==========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[3]
)


# ==========================================================
# FRONTEND
# ==========================================================
#
# Frontend assets are no longer inside the backend Python
# package. FastAPI still serves them, but they are owned by
# the frontend/ directory.
# ==========================================================

FRONTEND_DIRECTORY = (
    PROJECT_ROOT
    / "frontend"
)


FRONTEND_PAGES_DIRECTORY = (
    FRONTEND_DIRECTORY
    / "pages"
)


FRONTEND_STATIC_DIRECTORY = (
    FRONTEND_DIRECTORY
    / "static"
)


# ==========================================================
# MANAGED DOCUMENT STORAGE
# ==========================================================
#
# This is only the DEFAULT.
#
# DOCUMENT_STORAGE_DIR still overrides it, and tests still
# inject isolated temporary storage roots explicitly.
# ==========================================================

DEFAULT_STORAGE_ROOT = (
    PROJECT_ROOT
    / "storage"
    / "documents"
)
