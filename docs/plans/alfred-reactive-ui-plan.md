# Alfred Reactive UI — Implementation Plan

**Status:** Draft for attorney/engineering review. Not approved for implementation.
**Date:** 2026-06-10
**Author:** Alfred Implementation Planner

---

## 1. Curated Idea

Replace `web/index.html` (2,170-line vanilla JS monolith) and `web/static/style.css` (1,790 lines) with a React + Vite SPA, preserving all four workspaces (Chat, Skills Navigator, Case Files, Activity Log), all API contracts, and the existing design system. The rebuild targets component and state reuse for a future React Native/Expo mobile client. The backend (FastAPI, Railway) is untouched.

**Mobile recommendation: React Native with Expo.** A PWA is simpler to build but cannot access native push notifications, biometrics, or offline storage patterns that a future client-facing app will need. Expo's managed workflow also lets the same React component logic (hooks, state, API service layer) be reused in a web target via `expo-router` web support. Decision does not need to be finalized in Phase 1; what matters is that the web SPA is structured as if it will be consumed by a cross-platform shell.

---

## 2. Assumptions

1. The backend API contract (endpoints, request/response shapes, SSE protocol) is frozen for this rebuild. No backend changes are in scope.
2. The design-recommendation MCP server will supply design tokens and component guidance before visual work begins in Phase 2. Phase 1 treats the design system as a swappable layer and wires up a local token file that the MCP output will replace.
3. The Vite build output replaces `web/index.html` as the static files served by FastAPI (`main.py:399–419`). No separate Railway service is added.
4. The current `web/static/style.css` is retired; all styles move into the React component tree.
5. The `KLG_SKILLS` registry stays in the repo as a TypeScript data file (not a backend endpoint) for Phase 1. A backend endpoint is a Phase 2 consideration.
6. Auth is not upgraded in this rebuild—see auth migration path below. The localStorage Basic-auth pattern is preserved functionally but isolated behind a single abstraction so it can be swapped without touching every component.
7. The `tests/` directory currently contains only Python backend tests. Frontend tests are net-new.
8. "Design-system as swappable layer" means: all color tokens, spacing, and typography live in one `tokens.ts` file and one CSS custom-property injection point. Components reference tokens, not hard-coded hex values.

---

## 3. Risk and Issue Analysis

### 3.1 SSE Streaming Through a React Data Layer

**Risk:** The existing stream uses `fetch` + `ReadableStream` (not `EventSource`) because `EventSource` does not support POST or custom `Authorization` headers. React component re-renders on every token delta will cause visible jank if the streaming message is managed as component state naively (`useState` on a 2,000-token string triggers 2,000 re-renders).

**Mitigation (instruction to coder):** Accumulate streaming deltas in a `useRef` (mutable, no re-render) and flush to a `useState` on an animation-frame throttle (e.g., `requestAnimationFrame` or a 50 ms debounce). Only the final `done` event triggers the full state update that commits the message to history. The existing SSE protocol (`data: {"delta":"..."}`, `data: {"done":true,"tools_used":[...],"history":[...]}`) is unchanged—parse identically to the current reader loop at `index.html:1266–1308`.

### 3.2 Preserving the pydantic-ai chatHistory Contract

**Risk:** `ChatRequest.history` is a `list[Any]` of serialized pydantic-ai `ModelMessage` objects. The backend deserializes them via `ModelMessagesTypeAdapter.validate_python`. If the frontend ever mutates, re-orders, or re-serializes this list, the backend will silently drop history or throw a 400.

**Mitigation:** Store history as an opaque `unknown[]` in React state. Never parse, transform, or display its contents. Pass it back verbatim as received from the `done` event. Document this contract explicitly in the `useChat` hook as a code comment. Add a TypeScript type alias `type OpaqueHistory = unknown[]` to make intentionality visible.

### 3.3 Auth Migration Path

**The localStorage Basic-auth pattern (finding H1 in SECURITY_AUDIT.md) must not be deepened by this rebuild.**

**Current state:** password stored in `localStorage` (plaintext, no expiry), admin flags checked client-side from a hardcoded `KLG_USERS` array (finding C2: client-supplied identity).

**Decision required (Blocker for auth scope, not for v1 build):** The plan below isolates auth behind an `AuthContext` and an `apiClient` module. v1 replicates current behavior (localStorage, Basic headers) but only in those two files. When the security remediation from SECURITY_AUDIT.md remediation step 3 (H1: session handling) is implemented, only `AuthContext` and `apiClient` change—no component touches auth directly.

**What the rebuild must NOT do:**
- Embed `btoa(user + ':' + pwd)` in more than one place.
- Add new client-side admin flag checks in component code.
- Use `localStorage` for anything other than the same two keys already used (`klg_user`, `klg_password`).

**What the rebuild must do:**
- Export a single `useAuth()` hook that all components call.
- Export a single `apiClient` that wraps `fetch`, injects the Authorization header, and handles 401 centrally.
- When the audit-driven upgrade arrives (short-lived httpOnly session token), only `apiClient` changes.

### 3.4 Serving Strategy: Vite Build Mounted in FastAPI

**Option A — Vite output mounted as FastAPI static files (recommended).**
Vite builds to `web/dist/`. `main.py` serves `web/dist/` as static assets and `web/dist/index.html` at `/`. No new Railway service. Same-origin requests; CORS is unchanged. CI step: `vite build` before the Docker image build.

**Option B — Separate Railway service for the frontend.**
Two Railway services, separate deploys. CORS must be configured (hitting finding C3 from the audit). Adds operational overhead. No benefit for an internal-only app that is already same-origin.

**Decision: Option A.** The coder must update `main.py:399–419` to point at `web/dist/` instead of `web/` and serve `web/dist/index.html` for the root and all non-API paths (SPA fallback route). The Dockerfile must include the `vite build` step or a pre-built `web/dist/` must be committed (prefer build step).

**Dockerfile change required:** Add a Node build stage to the existing Dockerfile (multi-stage build). Build artifacts are copied into the Python image. This keeps the production image lean.

### 3.5 Migration Sequencing: Strangler vs. Big-Bang

**Big-bang:** Rewrite all four workspaces, delete `index.html`, ship once. Risk: long development period with no shippable increments; hard to validate regressions.

**Strangler (workspace-by-workspace):** New SPA is the entry point from day 1; each workspace migrates one at a time while others fall back to the old code. Problem: the old code is a single HTML file with deeply interleaved global state—there is no clean seam to extract one workspace without taking all the globals with it. True strangler is impractical here.

**Recommended: Phased big-bang with a feature flag.** The new SPA replaces `index.html` entirely in one deploy. Development happens in `web/src/` behind a Railway environment variable (`NEXT_UI=true`). `main.py` conditionally serves `web/dist/index.html` (new) or `web/index.html` (old) based on that flag. This gives a production escape hatch during development without a strangler architecture that would require maintaining two codebases.

### 3.6 State Management

**Risk:** Over-engineering. The app has four mostly independent workspaces with limited cross-workspace state (the main shared state is: `currentUser`, `authToken`, `chatHistory`, `activeWorkspace`). Full Redux or Zustand for v1 is overkill.

**Recommendation:** React Context for auth (`AuthContext`) and workspace navigation (`WorkspaceContext`). `useReducer` inside `useChat` for chat state (streaming, history, loading). TanStack Query (React Query) for all data-fetching (matters, deadlines, activity, case files)—it gives caching, loading/error states, and refetch for free, which eliminates the current manual `isLoading` globals and `loadMatters()`/`loadDeadlines()` imperative calls.

**Mobile reuse note:** TanStack Query v5 has a React Native adapter. `AuthContext` and all custom hooks are framework-agnostic React. This is the reuse surface for Expo.

### 3.7 Skills Registry Maintainability

**Current state:** `KLG_SKILLS` is a 200-line JS array hardcoded in `index.html`. Adding a skill requires editing the HTML file.

**Recommendation for v1:** Extract to `web/src/data/skills.ts` as a typed TypeScript array. No backend endpoint needed yet—the data is static and firm-authored, not user-generated.

**Deferred (Phase 3 / roadmap):** Backend-managed skills via a Notion database endpoint, so Tim can add skills without a deployment. Out of scope for this rebuild.

### 3.8 Accessibility

The firm roadmap explicitly lists accessibility. The current HTML has no ARIA roles, no landmark regions, no keyboard navigation beyond native browser defaults, and no focus management on workspace switches.

**v1 must:** Use semantic HTML (`<main>`, `<nav>`, `<section>`, `<button>`). Add `aria-label` to icon-only buttons. Manage focus on modal open/close (the user modal is a focus trap risk today). Mark the active workspace tab with `aria-current="page"`.

**Deferred (Phase 2):** Full WCAG 2.1 AA audit, skip-nav link, chat message live region (`aria-live="polite"` for streaming tokens).

### 3.9 Bundle Size and Mobile Performance

A React + Vite SPA with TanStack Query, the router, and a markdown renderer will be roughly 150–200 KB gzipped before any component code. On a mobile connection that is acceptable but not free.

**Mitigations:**
- Code-split by workspace using React lazy + Suspense. The Chat workspace loads first; Skills, Case Files, and Activity are deferred bundles.
- The markdown renderer (for chat messages) is the largest single dependency. Use a lightweight option (`marked` + DOMPurify, ~30 KB gzipped) rather than `react-markdown` + `remark-*` plugins (~80 KB).
- Set Vite's `build.rollupOptions.output.manualChunks` to keep vendor chunks predictable.
- Preload the Chat workspace chunk. Other chunks are loaded on first navigation.

### 3.10 Testing Strategy

Current `tests/` contains only Python backend tests (pytest). Frontend tests are absent.

**v1 baseline:**
- Vitest (same config as Vite, no separate setup) for unit tests on hooks and pure functions: `useChat` state machine, `apiClient` header injection, `formatActivityTime`, `escapeHtml`.
- React Testing Library for component tests: auth modal submit flow, workspace switching, skill card launch-to-chat flow.
- No E2E tests in v1 (Playwright setup deferred to Phase 2).

**Coverage floor:** The SSE streaming logic and the `chatHistory` opaque pass-through are the highest-risk behaviors. Both must have unit tests before Phase 1 ships.

### 3.11 Security Findings That Directly Affect the Web Layer

From SECURITY_AUDIT.md:

| Finding | Impact on rebuild | Action |
|---|---|---|
| H1: localStorage plaintext password, no expiry | Rebuild must not worsen. Auth isolated in `AuthContext` + `apiClient`. `sessionStorage` migration deferred to audit remediation step 3. | Coder guidance |
| H2: XSS via unescaped Notion data in case file view (~line 1987) | React JSX escapes by default. The rebuild eliminates this class of bug structurally, provided the coder never uses `dangerouslySetInnerHTML` with unsanitized server data. | Coder guidance: ban `dangerouslySetInnerHTML` except in the chat markdown renderer, where it must be preceded by `DOMPurify.sanitize()`. |
| H3: No security headers | Not a frontend concern; fixed in `main.py` middleware separately. Note it as a dependency: CSP header must be set before the SPA ships (React bundles include inline scripts by default; CSP `script-src` must allow the nonce or use `script-src 'self'` with no inline scripts). | Blocker dependency on backend |
| C3: CORS wildcard | Same-origin serving (Option A) makes this moot for the internal app. | No action needed |
| M5: Client-held conversation history, no scoping or TTL | React rebuild preserves this. Acceptable for internal v1. History server-side is a Phase 3 prerequisite per the audit. | Deferred |
| C2: Client-supplied identity | `user` field still sent as free text. Not fixed in this rebuild; noted. | Deferred to auth upgrade |

**CSP is a coordination blocker.** Before the SPA ships, H3 must be remediated in `main.py` with a Content-Security-Policy header. A React SPA with `script-src 'self'` is achievable (Vite does not emit inline scripts by default), but the backend must set the header. Coder must confirm no `<script>` tags are inlined in the Vite HTML template.

---

## 4. Decision Framework

| Item | Category | Resolution |
|---|---|---|
| Vite output mounted in FastAPI (Option A) | **Decision made** | Option A |
| React Native/Expo as mobile target | **Decision made** | Expo |
| No separate Railway service | **Decision made** | Confirmed |
| Auth not upgraded in this rebuild | **Decision made** | Auth isolated, not upgraded |
| Feature flag for phased rollout | **Design decision** | `NEXT_UI` env var in Railway |
| CSP header must be set before SPA ships | **Blocker** | Backend remediation must precede prod deploy |
| State management: Context + useReducer + TanStack Query | **Decision made** | No Redux/Zustand in v1 |
| Skills registry stays as TypeScript data file | **Decision made** | Backend endpoint deferred |
| Markdown renderer: `marked` + DOMPurify | **Decision made** | Not `react-markdown` |
| WCAG 2.1 AA full audit | **Deferred** | Phase 2 |
| E2E tests (Playwright) | **Deferred** | Phase 2 |
| Server-side chat history | **Deferred** | Phase 3 prerequisite per audit |
| Backend-managed skills endpoint | **Deferred** | Phase 3 roadmap |

---

## 5. Plan of Action

### Phase 0 — Foundation (do before writing any component)

**Goal:** Scaffold is running, design tokens are wired, auth abstraction exists, streaming is proven.

**Steps:**

0.1. **Scaffold the Vite + React project.**
- `npm create vite@latest web/src -- --template react-ts` (output into `web/src/`; Vite config points `root` to `web/src/` and `build.outDir` to `../../dist` relative to `web/src/`, resolving to `web/dist/`).
- Install: `react`, `react-dom`, `@tanstack/react-query`, `marked`, `dompurify`, `@types/dompurify`.
- Configure `vite.config.ts`: `server.proxy` for all `/alfred`, `/bloodhound`, `/auth`, `/cases`, `/slack` paths to `http://localhost:8000` during dev. This avoids CORS in dev without changing backend.
- Add `.npmrc` if needed; add `web/node_modules/` and `web/dist/` to `.gitignore`.

0.2. **Create `web/src/tokens.ts`.**
- Export the full set of CSS custom properties from `style.css` as TypeScript constants and inject them as a `:root {}` block via a `GlobalStyles` component. This is the swappable layer—when the design MCP server provides tokens, only this file changes.
- Include: `--accent: #5b8af0`, `--accent-amber: #f0a040`, `--bg-*`, `--text-*`, `--border`, `--radius`, `--font-sans: 'Inter'`, `--font-mono: 'JetBrains Mono'`, all breakpoints.

0.3. **Create `web/src/lib/apiClient.ts`.**
- Single `apiFetch(url, options)` function that reads `klg_user` and `klg_password` from `localStorage`, constructs the Basic Auth header identically to the current `getAuthHeaders()`, and handles 401 by clearing the password and emitting an event that `AuthContext` listens to.
- Export typed wrappers: `alfredChat(body)`, `alfredChatStream(body, onDelta, onDone, onError)`, `getMatters()`, `getDeadlines()`, `getActivity(days)`, `triggerDeadlineWatch()`, `bloodhoundScan(body)`, `authCheck(user, pwd)`, `getCaseFile(pageId)`.
- `alfredChatStream` implements the `fetch` + `ReadableStream` loop from `index.html:1265–1308`, with the `requestAnimationFrame` delta-batching described in §3.1.

0.4. **Create `web/src/contexts/AuthContext.tsx`.**
- State: `{ user: string | null, isAuthenticated: boolean, isAdmin: boolean }`.
- `KLG_USERS` array moved here (or into `web/src/data/users.ts` and imported).
- Exposes `login(user, pwd)` (calls `authCheck`, stores to localStorage), `logout()`, `switchUser()`.
- On mount, checks if `localStorage` has both keys and validates against `/auth/check`. If 401, clears and presents the auth modal.
- The `isAdmin` flag is still derived client-side from `KLG_USERS` (unchanged from today, matches finding C2 deferral).

0.5. **Prove the SSE streaming path works in isolation.**
- Write a standalone `StreamTest` component (not shipped, dev-only) that sends a hardcoded message to `/alfred/chat/stream` and logs deltas to the console.
- Confirm: (a) proxy works in dev, (b) streaming reader accumulates correctly, (c) `done` event carries `history` array that round-trips correctly on a second call.
- This test component is deleted before Phase 1 ships.

0.6. **Update `main.py` to add the feature flag.**
- Add `NEXT_UI` to `config.py` `Settings` model (default `False`).
- In `main.py` static file section: if `NEXT_UI=true`, serve `web/dist/` as static and `web/dist/index.html` at `/` and as SPA fallback for all non-API routes. Else serve `web/index.html` as today.
- SPA fallback: any GET that is not an API route and not a static file returns `web/dist/index.html`. This enables client-side routing.

0.7. **Update Dockerfile with Node build stage.**
- Multi-stage: stage 1 is `node:20-slim`, installs deps in `web/src/`, runs `vite build`, copies `web/dist/` to a temp location. Stage 2 is the existing Python image, copies `web/dist/` from stage 1.
- Confirm `web/dist/` is not committed to git (it is a build artifact).

**Phase 0 acceptance criteria:**
- `npm run dev` in `web/src/` proxies all API calls to the local FastAPI server without CORS errors.
- `npm run build` produces `web/dist/` with no TypeScript errors.
- The `StreamTest` component demonstrates working SSE streaming and a correct second-turn history round-trip.
- `NEXT_UI=true` on Railway serves the (empty) React shell at `/`; `NEXT_UI=false` (or unset) serves the old `index.html` unchanged.

---

### Phase 1 — Chat Workspace (highest value, proves the hardest problems)

**Goal:** The Chat workspace is fully functional in React. All other workspaces show a "coming soon" placeholder. Old `index.html` is still the fallback.

**Files to create:**
```
web/src/
  App.tsx                     — root: AuthProvider, QueryClientProvider, WorkspaceProvider, router
  main.tsx                    — Vite entry
  components/
    auth/
      UserModal.tsx           — user picker + password step (mirrors current modal)
    layout/
      Header.tsx              — logo, user chip, workspace tabs, model selector
      WorkspaceShell.tsx      — routes to active workspace
    chat/
      ChatWorkspace.tsx       — outer layout (sidebar, main panel, deadlines panel)
      MattersSidebar.tsx      — matters list from /alfred/matters (TanStack Query)
      DeadlinesPanel.tsx      — upcoming deadlines from /alfred/deadlines (TanStack Query)
      ChatPanel.tsx           — message list + input
      ChatMessage.tsx         — single message bubble (user or agent)
      StreamingMessage.tsx    — in-progress streaming bubble
      AgentSelector.tsx       — Alfred / Bloodhound toggle
      AgentTriggers.tsx       — deadline-watch and bloodhound-scan buttons
    shared/
      ModelSelector.tsx       — model dropdown (used in chat)
  hooks/
    useChat.ts                — useReducer: chatHistory, messages, streaming state
    useMatters.ts             — TanStack Query wrapper for /alfred/matters
    useDeadlines.ts           — TanStack Query wrapper for /alfred/deadlines
  contexts/
    AuthContext.tsx           — (from Phase 0)
    WorkspaceContext.tsx      — activeWorkspace, setActiveWorkspace
  lib/
    apiClient.ts              — (from Phase 0)
    markdown.ts               — marked + DOMPurify renderer, identical output to formatMessageText()
  data/
    users.ts                  — KLG_USERS array
  tokens.ts                   — (from Phase 0)
```

**Key implementation notes for the coder:**

1.1. `useChat` state shape:
```typescript
type ChatState = {
  messages: DisplayMessage[];       // rendered messages (user + agent)
  history: OpaqueHistory;           // pydantic-ai history, opaque, never parsed
  streaming: { id: string; text: string } | null;  // active stream, null when idle
  isLoading: boolean;
  error: string | null;
};
```
Actions: `SEND`, `STREAM_START`, `STREAM_DELTA`, `STREAM_DONE`, `STREAM_ERROR`, `CLEAR`, `AGENT_SWITCH` (clears history, matching `index.html:1127`).

1.2. `StreamingMessage` uses `useRef` for the accumulating text and `requestAnimationFrame` to batch DOM updates. It renders the same lightweight escape-only format as `updateStreamingMessage()` during streaming, then switches to the `markdown.ts` renderer on `STREAM_DONE`.

1.3. `markdown.ts` must produce output visually identical to `formatMessageText()` (`index.html:1411` onward). Read that function before writing the replacement. It handles: code blocks with language class, bold, italic, headers, numbered/bulleted lists, horizontal rules.

1.4. `MattersSidebar` and `DeadlinesPanel` use TanStack Query with `staleTime: 5 * 60 * 1000` (5 minutes). On 401, the query error triggers `AuthContext.logout()`.

1.5. The model selector value is `useState` local to `ChatWorkspace` (or lifted to `WorkspaceContext` if it needs to persist across workspace switches—it does in the current app; lift it).

1.6. `UserModal` is a focus trap. Use a `useEffect` to move focus to the first interactive element on open and restore focus on close.

1.7. `AgentSelector` switching calls `dispatch({ type: 'AGENT_SWITCH' })` to clear `chatHistory` and `messages`, matching current behavior.

**Phase 1 acceptance criteria:**
- Auth modal appears on first load, `login()` stores credentials, page reloads to authenticated state.
- Matters sidebar populates from `/alfred/matters`.
- Deadlines panel populates from `/alfred/deadlines`.
- Alfred streaming: first token appears within ~1 second of send, message builds token by token, tools-used badges appear on completion.
- Bloodhound non-streaming: response appears after full round-trip.
- Model selector change takes effect on next message.
- Agent switch clears chat history.
- Second-turn message sends previous `history` and Alfred demonstrates memory.
- Deadline-watch and bloodhound-scan trigger buttons POST to their endpoints and show a confirmation.
- No `dangerouslySetInnerHTML` used outside `markdown.ts`, where it is preceded by `DOMPurify.sanitize()`.
- Vitest: `useChat` reducer unit tests, `apiClient` header-injection tests, `markdown.ts` output tests, `StreamingMessage` delta-batching test all pass.
- No TypeScript errors at `tsc --noEmit`.

---

### Phase 2 — Remaining Workspaces + Design Polish

**Goal:** All four workspaces migrated. Design MCP tokens integrated. Responsive/mobile-ready. Accessibility baseline met.

**Files to create (additions to Phase 1 tree):**
```
web/src/components/
  skills/
    SkillsWorkspace.tsx
    SkillGrid.tsx
    SkillCard.tsx
    SkillDetailPanel.tsx
    SkillCategoryFilter.tsx
  casefiles/
    CaseFilesWorkspace.tsx
    CaseFilesSidebar.tsx       — matter picker
    CaseFileDetail.tsx         — Notion matter + Slack activity + image gallery
    ImageLightbox.tsx
  activity/
    ActivityWorkspace.tsx      — admin-only guard
    ActivityFeed.tsx
    ActivityEntry.tsx
    ActivityFilters.tsx
  hooks/
    useActivity.ts             — TanStack Query for /alfred/activity
    useCaseFile.ts             — TanStack Query for case file endpoints
  data/
    skills.ts                  — KLG_SKILLS extracted from index.html, typed
```

**Key implementation notes for the coder:**

2.1. `SkillsWorkspace`: `KLG_SKILLS` is imported from `data/skills.ts`. Category filter is local `useState`. "Launch Skill" calls `WorkspaceContext.setActiveWorkspace('chat')` and dispatches the skill prompt into `useChat`—this is the cross-workspace interaction. Use a `WorkspaceContext` action like `LAUNCH_SKILL(prompt: string)` that sets the workspace and pre-populates the pending input.

2.2. `CaseFileDetail` renders Notion-controlled data (matter name, fields). **Never use `dangerouslySetInnerHTML` for any server-provided string here.** This is the fix for audit finding H2. Use `textContent` assignment or JSX text interpolation (which React escapes automatically). The only `dangerouslySetInnerHTML` allowed in the entire codebase is in `markdown.ts` after `DOMPurify.sanitize()`.

2.3. `ActivityWorkspace` checks `useAuth().isAdmin`. If false, it renders nothing and calls `WorkspaceContext.setActiveWorkspace('chat')`. The tab itself is conditionally rendered in `Header.tsx` based on `isAdmin`.

2.4. `ImageLightbox` needs keyboard dismissal (Escape key) and focus trap.

2.5. **Design MCP integration.** When the design MCP server provides tokens, the coder replaces `web/src/tokens.ts` with the MCP output. Components reference only the token variables; no hex values appear in component files. CSS custom properties are injected via the `GlobalStyles` component at the root. If the MCP server provides full component designs, the coder adopts them as the visual implementation of the component interface defined in Phase 1—the logic does not change, only the rendered markup and styles.

2.6. **Responsive breakpoints.** The current breakpoints (`1100px`, `768px`, `480px`) are preserved. Sidebar drawers on mobile use the same open/close pattern, now driven by `useState` rather than direct DOM class manipulation.

2.7. **Accessibility minimum for Phase 2:**
- All four workspaces wrapped in `<main>` with `aria-label`.
- Workspace tabs use `role="tablist"` / `role="tab"` / `aria-selected`.
- Chat message list uses `role="log"` and `aria-live="polite"`.
- Icon-only buttons have `aria-label`.
- Modals use `role="dialog"` and `aria-modal="true"`.

**Phase 2 acceptance criteria:**
- All four workspaces render correctly and match the current visual design (or the MCP-supplied design if delivered).
- Skills filter, detail panel, and "Launch Skill" → chat flow work end-to-end.
- Case Files sidebar, matter detail, Slack activity, and lightbox work.
- Activity Log shows only for Tim and Stu; hides for all other users.
- No server-provided strings passed to `dangerouslySetInnerHTML`.
- Lighthouse accessibility score ≥ 80 on the Chat workspace.
- `NEXT_UI=true` deploy on Railway passes a manual smoke test of all four workspaces.
- Old `index.html` still loads correctly when `NEXT_UI` is unset.

---

### Phase 3 — Cut Over and Cleanup

**Goal:** Old `index.html` removed from production. Feature flag retired. Frontend tests expanded.

**Steps:**

3.1. Set `NEXT_UI=true` as the Railway default. Remove the feature flag conditional from `main.py` (or leave it for emergency rollback—engineer's call).

3.2. Delete `web/index.html` and `web/static/style.css` after a 2-week observation period with the SPA live.

3.3. Update `main.py` static file section to unconditionally serve `web/dist/`.

3.4. Add Playwright E2E tests for the critical path: login → send Alfred message → receive streaming response → verify history round-trip on second turn.

3.5. Add a `npm run test:coverage` check to CI (Railway build or a separate CI step).

3.6. Update `CLAUDE.md` (or create `web/src/CLAUDE.md`) documenting the component tree, the `apiClient` contract, the `OpaqueHistory` constraint, and the `dangerouslySetInnerHTML` rule.

**Phase 3 acceptance criteria:**
- `web/index.html` is deleted and no reference to it remains in `main.py` or the Dockerfile.
- E2E smoke test passes in CI.
- No regression in the Python backend tests (`pytest tests/`).

---

## 6. Known Risks and Mitigations (Summary for Coder)

| Risk | Mitigation |
|---|---|
| SSE streaming causes 2,000 React re-renders per response | `useRef` accumulation + `requestAnimationFrame` throttle in `StreamingMessage`. See §3.1. |
| `chatHistory` mutation breaks pydantic-ai deserialization | `OpaqueHistory = unknown[]`, never parsed, passed verbatim from `done` event. See §3.2. |
| `dangerouslySetInnerHTML` re-introduces H2 XSS | Banned everywhere except `markdown.ts` after `DOMPurify.sanitize()`. See §3.3 and §3.10. |
| CSP header blocks React bundle | H3 backend fix must land before SPA ships to prod. Coordinate with backend. See §3.10. |
| Skills "Launch Skill" requires cross-workspace state | `WorkspaceContext` `LAUNCH_SKILL` action. See 2.1. |
| Node build stage bloats Docker image | Multi-stage Dockerfile; only `web/dist/` copied to Python stage. See §3.4. |
| Auth admin check trivially bypassed (client-side) | Known, deferred per audit finding C2. Do not add new client-side auth gates. See §3.3. |
| `marked` output differs from current `formatMessageText()` | Read `index.html:1411–1480` before writing `markdown.ts`. Write unit tests comparing output on the same fixtures. |

---

## 7. Open Questions

**Require answer before Phase 0 starts:**

Q1. Does the H3 security headers fix (backend middleware in `main.py`) land before the SPA is deployed to production? If yes, confirm the CSP policy will allow `script-src 'self'` with no inline script exceptions. (CSP is a blocker for prod deploy of the SPA.)

Q2. Will the design MCP server be available before Phase 2 visual work begins, or should Phase 1 use the current token values as the permanent design system?

Q3. Should the `NEXT_UI` feature flag be a Railway environment variable (prefer) or a Python `config.py` setting? (Affects how quickly it can be toggled without a redeploy.)

**Require answer before Phase 2 starts:**

Q4. The Skills registry (`KLG_SKILLS`) currently has 11 skills. Is Tim planning to add more before Phase 2 ships? If yes, a backend endpoint may be worth doing earlier than Phase 3.

Q5. The Case Files workspace calls case-file endpoints not fully read during this review (only `api/routes/cases.py` was identified). The coder should read `api/routes/cases.py` in full before implementing `CaseFilesWorkspace` to confirm all endpoints and their shapes.

---

## 8. Acceptance Criteria (v1 = Phases 0 + 1 + 2, NEXT_UI=true in production)

1. All four workspaces are functional and visually match the current design (or MCP-supplied design).
2. Alfred streaming delivers first token within ~1 second; no visible jank during streaming.
3. Second-turn messages demonstrate Alfred memory (history round-trip confirmed).
4. Auth modal works identically to today: user pick → password → `/auth/check` → localStorage store.
5. Activity Log is invisible to non-admin users.
6. No `dangerouslySetInnerHTML` with unsanitized server data anywhere in the codebase.
7. Vitest unit tests for `useChat`, `apiClient`, `markdown.ts`, and streaming path all pass.
8. TypeScript strict mode: `tsc --noEmit` exits 0.
9. Lighthouse performance score ≥ 70 on mobile simulation for the Chat workspace.
10. Lighthouse accessibility score ≥ 80 on the Chat workspace.
11. `npm run build` completes in Railway's build environment (confirmed in staging before production cut-over).
12. Old `index.html` still served correctly when `NEXT_UI` is unset (escape hatch confirmed).

---

## 9. What Stays Untouched on the Backend

The following backend files and behaviors are out of scope for this rebuild. The coder must not modify them:

- `alfred/agent.py` and all tool definitions
- `api/routes/alfred.py`, `api/routes/bloodhound.py`, `api/routes/cases.py`, `api/routes/slack.py`
- `notion_bridge/`, `bloodhound/`, `agents/`
- `main.py` middleware stack, auth middleware, rate limiting—except the two additions in Step 0.6 (feature flag) and the CSP header (pre-condition, tracked separately)
- `Dockerfile` Python stage—the coder adds a Node build stage but does not change the Python stage
- Railway Cron Jobs configuration
- Any `.env` or Railway environment variables other than `NEXT_UI`

---

## 10. File Structure Delivered at Phase 2 Complete

```
web/
  src/                        ← Vite project root
    App.tsx
    main.tsx
    tokens.ts
    vite.config.ts
    tsconfig.json
    package.json
    components/
      auth/UserModal.tsx
      layout/Header.tsx
      layout/WorkspaceShell.tsx
      chat/ChatWorkspace.tsx
      chat/MattersSidebar.tsx
      chat/DeadlinesPanel.tsx
      chat/ChatPanel.tsx
      chat/ChatMessage.tsx
      chat/StreamingMessage.tsx
      chat/AgentSelector.tsx
      chat/AgentTriggers.tsx
      shared/ModelSelector.tsx
      skills/SkillsWorkspace.tsx
      skills/SkillGrid.tsx
      skills/SkillCard.tsx
      skills/SkillDetailPanel.tsx
      skills/SkillCategoryFilter.tsx
      casefiles/CaseFilesWorkspace.tsx
      casefiles/CaseFilesSidebar.tsx
      casefiles/CaseFileDetail.tsx
      casefiles/ImageLightbox.tsx
      activity/ActivityWorkspace.tsx
      activity/ActivityFeed.tsx
      activity/ActivityEntry.tsx
      activity/ActivityFilters.tsx
    hooks/
      useChat.ts
      useMatters.ts
      useDeadlines.ts
      useActivity.ts
      useCaseFile.ts
    contexts/
      AuthContext.tsx
      WorkspaceContext.tsx
    lib/
      apiClient.ts
      markdown.ts
    data/
      users.ts
      skills.ts
    __tests__/
      useChat.test.ts
      apiClient.test.ts
      markdown.test.ts
      StreamingMessage.test.tsx
  dist/                       ← Vite build output (gitignored)
  index.html                  ← Old file, kept until Phase 3 cutover
  static/style.css            ← Old file, kept until Phase 3 cutover
```

---

*This plan is a proposal. Attorney and engineering review required. The coder may not begin Phase 0 until the user confirms or adjusts this document.*
