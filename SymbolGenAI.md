# Symbol Library AI Copilot for EDA

## Overview
Build an Electron-based AI copilot for managing electronic component symbols (schematic and PCB). The system generates schematic symbols from datasheets, stores them in a library, allows placement in an EDA editor, and includes AI chat for symbol/library interaction.

## Core Features
1. Symbol Generation: Parse component datasheets and auto-generate schematic symbols while preserving standard shapes (resistor, capacitor, inductor, transformer, diode, transistor, etc.)
2. Symbol Library: Store, organize, and version-control generated symbols with metadata (part number, datasheet ref, parameters)
3. EDA Editor MVP: Minimal schematic canvas built with Electron where users can place and route symbols
4. AI Chat Interface: Conversational AI to query, modify, and manage symbols/library; recommend standard formats
5. Symbol Details Management: Update symbol properties from datasheet content and apply formatting standards (pin naming, size constraints, etc.)

## Technology Stack
- Electron (main app shell)
- React/TypeScript (UI)
- Claude AI API (symbol generation and chat)
- SQLite or similar (local symbol library storage)
- Canvas/SVG (symbol rendering)

## Project Structure
- electron/ (main process, IPC handlers)
- src/ (React UI components: editor, library viewer, chat, symbol form)
- services/ (datasheet parser, symbol generator, AI integration)
- db/ (library schema, queries)
- types/ (shared TypeScript definitions for symbols, library)

## MVP Scope
- Parse basic datasheets (PDF text extraction)
- Generate 5-10 common symbol types
- Basic symbol canvas (place, select, delete)
- SQLite library storage
- Claude chat for symbol queries and recommendations
- Symbol property editor

## Output Provide complete project structure, file organization, key module interfaces, and setup instructions.