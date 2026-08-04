# KLG AI OS — Backend Agent & Reactive UI Integration Specification

## Overview
This specification details how **Alfred** (the executive assistant agent) and **Bloodhound** (the surveillance engine agent) interact with the reactive web and mobile UI (`web-next`). It defines the workspace structure, mobile-responsive interaction patterns, dynamic metrics, and how agent tools map into front-end visual components.

---

## 1. Responsive & Mobile UI Capabilities

### **Mobile Navigation & Viewport Adaptations**
- **Mobile Viewports (`<= 768px`)**:
  - The application renders a fixed header and a **Mobile Bottom Navigation Bar** with direct access to primary workspaces (`Today`, `Matters`, `Chat`, `Deadlines`) and a slide-up "More" drawer for secondary workspaces (`Skills`, `Bloodhound`, `Accounting`, `Admin`).
  - **Matter Detail Panel**: Automatically adapts from a 50vw side drawer on desktop to a full-screen bottom sheet with close controls on mobile screens.
  - **Touch Target Standard**: All interactive buttons, chips, and list rows maintain a minimum 44px touch height (`--touch-target: 44px`) and safe-area inset padding (`--safe-area-bottom`).

---

## 2. Dynamic Dashboard & Workspace Specifications

### **Matters Workspace (`DashboardWorkspace.tsx`)**
- **Metric Summary Cards**:
  - `Total Matters`: Total count of matters fetched from Notion.
  - `Active Briefs`: Active matters currently in progress.
  - `Critical (<7 Days)`: Matters with upcoming court deadlines within 7 days.
  - `Pending Review`: Matters marked as pending or paused.
- **Multi-View Modes**:
  1. `Kanban`: Matters grouped by case stage (*Matter Intake & Setup*, *Pleadings & Notices*, *Brief Preparation & Drafting*, *Cites & Compliance*, *Review & Finalization*, *Contingency Tasks*).
  2. `Grid`: Visual matter cards displaying stage, urgency dot, assignee, and next deadline.
  3. `List`: Dense data table for quick scanning.
- **Global Search & Filter**: Real-time filtering by text query, case stage, and archived status toggle.

### **Surveillance Engine (`BloodhoundWorkspace.tsx`)**
- **Feed Scan Execution**:
  - Alfred & Bloodhound agent triggers surface RSS feeds and CourtListener docket alerts.
  - Urgency indicators highlight high-value appellate decisions and watch list matches.

### **Appellate Cases & Accounting Dashboards**
- **Cases Workspace (`CasesWorkspace.tsx`)**: Appellate record folders connected to Notion & SharePoint with active sync metrics.
- **Accounting Workspace (`AccountingWorkspace.tsx`)**: Real-time billing metrics, retainer trust balances, and invoice collection statuses.

---

## 3. Alfred & Bloodhound Tool Mapping

| Tool Name | Backend Agent | Visual UI Target & Response Mapping |
|---|---|---|
| `find_and_summarize_matter` | Alfred | Updates selected matter state in `useMatterStore`, opens `MatterDetailPanel` |
| `get_upcoming_deadlines` | Alfred | Highlights entries in `DeadlinesWorkspace` and metric strips |
| `update_matter_status` | Alfred | Optimistically updates matter status chips and moves card in Kanban stage view |
| `create_matter_task` | Alfred | Appends task under standard stage group in `MatterDetailPanel` |
| `run_bloodhound_scan` | Bloodhound | Refreshes feed cards in `BloodhoundWorkspace` with new triage signals |

---

## 4. Architectural Integration & SSE Streaming
- **SSE Chat Protocol**: Chat streaming endpoint (`POST /alfred/chat`) streams text deltas via `fetch` + `ReadableStream`.
- **Throttled Streaming**: React UI buffers streaming deltas in `useRef` and flushes updates to avoid frame drops.
- **Opaque History Contract**: `chatHistory` from `pydantic-ai` is preserved as an opaque data structure (`OpaqueHistory`) and passed verbatim on subsequent chat requests.
