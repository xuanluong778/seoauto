"""
Semantic internal linking subsystem.

High-level flow:
- Sync WordPress content into local DB (articles + chunks)
- Generate embeddings for chunks (sentence-transformers)
- Suggest semantically related links + anchor variations
- Apply contextual injection into HTML safely
"""

from __future__ import annotations

