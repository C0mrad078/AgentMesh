"""Orquestrador core package.

This package implements the autonomous orchestration engine that will
eventually coordinate multiple AI providers (Claude, Gemini, Codex/OpenAI,
and others). In this stage, all AI-facing behavior is backed by mocked
providers and agents so that the surrounding architecture (planning,
routing, execution, verification, persistence, and the desktop bridge)
can be built and hardened first.
"""

__version__ = "0.1.0"
