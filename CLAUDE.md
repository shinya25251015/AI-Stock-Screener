# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-Stock-Screener is an AI-powered Japanese stock screener. The repository is at a very early stage: it currently contains only this file and a README, with no source code, build system, or tooling yet.

## Current State

- No programming language, framework, or package manager has been chosen yet.
- There are no build, lint, or test commands to run.
- The default branch is `main`.

## Guidance for Future Work

- When code is first added, update this file with the chosen language/toolchain and the exact commands for installing dependencies, building, linting, and running tests (including how to run a single test).
- Once an architecture emerges (e.g., data ingestion for Japanese market data, screening/AI logic, and any UI or API layer), document the high-level structure here so future sessions can navigate it quickly.
- Note that the product domain is Japanese equities, so expect concerns like Tokyo Stock Exchange tickers/market data sources and possibly Japanese-language output when making design decisions.
