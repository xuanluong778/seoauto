"""Types for the external API cost-control layer."""

from __future__ import annotations

from enum import Enum


class ExternalApiProvider(str, Enum):
  OPENAI = "openai"
  ANTHROPIC = "anthropic"
  DATAFORSEO = "dataforseo"
  GOOGLE_PLACES = "google_places"
  GOOGLE_CSE = "google_cse"
  CRAWL = "crawl"
  OPENROUTER_IMAGE = "openrouter_image"
  GOOGLE_INDEXING = "google_indexing"
  EMBEDDING = "embedding"
  EMAIL = "email"
  STORAGE = "storage"
  WORDPRESS = "wordpress"
