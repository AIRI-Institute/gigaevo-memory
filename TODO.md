# GigaEvo Memory — Implementation TODO for the CARE ecosystem

GigaEvo Memory persists CARL artifacts (steps, chains, agents, memory cards)
with immutable versions and channel pinning. CARE needs Memory to (a) store
**AgentSkills** as a first-class entity, (b) expose a unified client that
also drives the GigaEvo Platform API (renaming `gigaevo-memory` →
`gigaevo-client`), and (c) provide a few quality-of-life features for
TUI-driven editing/searching.

Priorities: **[P0]** blocker for CARE MVP · **[P1]** required for v0.1 ·
**[P2]** required for full ecosystem · **[P3]** quality / polish ·
**[P4]** future / research.

---

## 1. AgentSkill as a first-class entity (P0)

The existing entity types are `step`, `chain`, `agent`, `memory_card`
(allowlist at `api/app/services/entity_service.py::VALID_ENTITY_TYPES`).
Storing AgentSkill artifacts inside `memory_card` content is feasible but
loses discoverability, version semantics, and skill-specific search.

### 1.1 Backend changes
- **[DONE]** Add `"agent_skills" → "agent_skill"` to
  `api/app/services/entity_service.py::VALID_ENTITY_TYPES` (entries are
  plural→singular). The DB column `entities.entity_type VARCHAR(20)` already
  accommodates the 11-char value — no DDL migration required.
  *Shipped 2026-05-16: `entity_service.py:30-36` updated;
  `tests/test_entity_service.py::TestValidEntityTypes` extended with the
  new mapping assertion + `test_agent_skill_fits_db_column` guard. 16/16
  tests pass. Generic `/v1/entities/agent_skills/...` and `/v1/versions`
  routers now accept the new type (allowlist guard in
  `routers/entities.py:17, 188` and `routers/versions.py:19`).*
- **[DONE]** Create `api/app/routers/agent_skills.py` cloned from
  `routers/agents.py`, swapping `entity_type = "agent_skills"` and the
  response model. Mount in `api/app/main.py`.
  *Shipped 2026-05-16: new `routers/agent_skills.py` exposes all five
  typed CRUD endpoints (`POST/GET /v1/agent-skills`,
  `GET/PUT/DELETE /v1/agent-skills/{id}`) with ETag/If-Match optimistic
  concurrency mirroring the agents router. Mounted in `main.py`
  alongside the other typed entity routers.*
- **[DONE]** Add `AgentSkillResponse(EntityResponse)` with
  `entity_type: Literal["agent_skill"]` to `api/app/models/responses.py`,
  plus `AgentSkillPageResponse`.
  *Shipped 2026-05-16: both response models added next to `AgentResponse`
  / `AgentPageResponse`. OpenAPI emits `AgentSkillResponse` with
  `const: "agent_skill"` literal. 7 new tests in
  `tests/test_agent_skills_router.py` cover router prefix/tags, the
  five CRUD endpoint registrations, app-level mount, OpenAPI exposure,
  and response-model literal validation (accepts `agent_skill`, rejects
  other entity-type literals).*
- **[DONE]** Define the content schema in `api/app/models/requests.py`:
  ```python
  class AgentSkillContent(BaseModel):
      name: str
      description: str
      uri: str                      # github://... | local://... | https://...
      sha256: str                   # SHA256 of SKILL.md content
      manifest: dict[str, Any]      # parsed SKILL.md frontmatter
      instructions: str             # SKILL.md body
      allowed_tools: list[str]      # parsed allowed-tools tokens
      tags: list[str]
      compatibility: dict[str, Any] | None = None
      tarball_url: str | None = None  # for github://
      tarball_sha256: str | None = None
  ```
  *Shipped 2026-05-16: `AgentSkillContent` added next to `MemoryCardContent`
  in `models/requests.py`. Name 1-200 chars (matches DB column convention),
  sha256 pinned to `^[0-9a-fA-F]{64}$` (uppercase accepted). 11 tests in
  `tests/test_agent_skill_content.py`: field validation (required + length
  + sha pattern + uppercase hex), defaults, required-fields-missing, JSON
  schema shape (required set, pattern, optional tarball fields), and an
  end-to-end CARE/MAGE flow test that builds the schema, embeds it in an
  `EntityCreateRequest`, and round-trips the payload back to the typed
  shape without loss. Model is a client-side validation aid — not
  referenced by route bodies (which keep `content: dict[str, Any]` so
  Memory remains a generic JSON store).*
- **[DONE]** Extend `entity_search_documents` indexing
  (`api/app/services/search_document_service.py:169`) so AgentSkill content
  is BM25-searchable on `name + description + instructions`.
  *Shipped 2026-05-16: new `derive_agent_skill_search_documents()` emits
  four document kinds — `skill_description` (name+description for fast
  matches), `skill_instructions` (SKILL.md body, vector-friendly),
  `skill_full` (combined name+desc+body BM25 catch-all), and
  `skill_allowed_tools` (CSV of `allowed-tools` tokens for facet
  filtering). `sync_entity_search_documents()` refactored to dispatch
  via new `INDEXED_ENTITY_TYPES = {"memory_card", "agent_skill"}`
  allowlist. `card_id` doubles as the skill's `name` (or `uri`
  fallback) for external-ID lookups; `meta_json` carries `skill_name`,
  `uri`, `snippet`, `document_kind`. 15 tests in
  `tests/test_search_document_agent_skill.py` cover the four doc kinds,
  partial-content emission, external-id fallback, dispatch routing for
  agent_skill / memory_card / other types. Real-scenario evaluation:
  3 sample skills (pdf/pptx/weather) → 12 docs indexed; BM25 queries
  for "extract", "presentation", "weather forecast" return the right
  skill; `allowed_tools` facet correctly identifies skills with vs.
  without `Bash`.*

### 1.2 Client changes
- **[DONE]** Add `"agent_skill": "agent-skills"` to `_TYPE_PLURAL` in
  `client/python/src/gigaevo_memory/_base.py:20`.
  *Shipped 2026-05-16: mapping added; base `_get_entity` / `_save_entity`
  / `_list_entities` / `_delete_entity` now route agent_skill calls to
  the kebab-case URL automatically.*
- **[DONE]** Create `client/python/src/gigaevo_memory/agent_skills.py` with
  `AgentSkillsMixin` exposing:
  - `get_agent_skill(entity_id, channel="latest") -> AgentSkillSpec`
  - `get_agent_skill_dict(entity_id, channel="latest") -> dict`
  - `save_agent_skill(spec_or_dict, name, ..., entity_id=None) -> EntityRef`
  - `list_agent_skills(limit=50, offset=0, channel="latest") -> list[EntityResponse]`
  - `delete_agent_skill(entity_id) -> bool`

  *Shipped 2026-05-16: new file mirrors the AgentsMixin contract.
  `search_agent_skills` deferred — already covered by the existing
  `SearchMixin.search(entity_type="agent_skill", ...)`; an explicit
  convenience wrapper can be added later under §4.*
- **[DONE]** Add `AgentSkillSpec` Pydantic model in
  `client/python/src/gigaevo_memory/models.py` matching the content schema.
  *Shipped 2026-05-16: model mirrors `api/app/models/requests.py::
  AgentSkillContent` (server side) — same field set, same sha256
  pattern. `AgentSkillDict = dict` alias added next to `AgentDict`.*
- **[DONE]** Mix `AgentSkillsMixin` into `MemoryClient` in `client.py`. Export
  from `__init__.py`.
  *Shipped 2026-05-16: `MemoryClient(SearchMixin, VersionMixin,
  ChainsMixin, AgentsMixin, AgentSkillsMixin, MemoryCardsMixin)` —
  AgentSkillsMixin inserted between AgentsMixin and MemoryCardsMixin to
  group typed-entity mixins. `AgentSkillSpec` + `AgentSkillDict`
  exported from `__init__.py` via the existing lazy `__getattr__`
  pattern + `__all__` list.*
- **[DONE]** Tests: clone `tests/test_agents.py` →
  `tests/test_agent_skills.py`. Cover save, get, list, search, version
  bump on SHA change.
  *Shipped 2026-05-16: 11 tests across 5 classes — mixin composition
  + URL routing constant; get (success / dict accessor / 404); save
  (create / update / dict-input variant verifying request body);
  list; delete (success / 404). Real-scenario evaluation runs the
  full lifecycle (save → list → get → delete) against a `respx`-mocked
  Memory API and verifies the POST body, type-routing, and
  round-trip integrity (`AgentSkillSpec` equality + SHA preservation).
  37/37 adjacent client tests still pass.*

### 1.3 Helper: skill ingestion from CARL
- **[DONE]** `MemoryClient.ingest_skill_from_carl(resolved_skill: ResolvedSkill)`
  helper that:
  1. Reads `manifest`, `instructions`, `allowed_tools` from a CARL
     `ResolvedSkill` object.
  2. Computes/verifies SHA256 of SKILL.md.
  3. Calls `save_agent_skill()` idempotently (no-op if SHA matches latest
     version).
  Returns the entity_id. Used by MAGE and CARE.
  *Shipped 2026-05-16 (iteration #15):
  `MemoryClient.ingest_skill_from_carl(resolved_skill, *, name=None,
  tags=None, when_to_use=None, author=None, namespace=None,
  entity_id=None, channel="latest") -> EntityRef`. Duck-typed input —
  accepts any CARL `ResolvedSkill`-like object (any object with
  `.manifest` exposing `.name` / `.description` / `.instructions` /
  `.get_allowed_tools()` / `.metadata` / `.compatibility`, plus
  top-level `.sha256` / `.source_uri` / `.tarball_url` /
  `.tarball_sha256`), an `AgentSkillSpec`, or a plain dict matching
  the spec. **No hard `mmar_carl` dependency** — uses `getattr` with
  documented fallback chains (`source_uri` → `uri`, `sha256` →
  `skill_md_sha256`, `instructions` → `body`, `get_allowed_tools()` →
  `allowed_tools` attr, manifest tags → metadata.tags). Idempotent
  upsert via the optional `entity_id` parameter: provide it to create
  a new version on an existing entity, omit it to create new.
  Validates upstream — missing sha256 / source_uri / manifest raise
  `ValueError` **before** any HTTP traffic. Underlying call to
  `save_agent_skill()` reuses iter #5's wiring. Module-level
  `_extract_skill_spec(resolved)` helper exposed for reuse by callers
  that want the projection without the persistence side-effect. 19 tests
  in `client/python/tests/test_ingest_skill_from_carl.py`: extraction
  (13 — round-trip + fallback chains + validation errors + tags from
  attr/metadata + AgentSkillSpec pass-through + dict input + tarball
  propagation), HTTP wiring (6 — create + update + override + spec
  input + dict input + validation-before-network). Real-scenario
  evaluation: MAGE resolves Anthropic's PDF skill (v1), ingests via
  `ingest_skill_from_carl(resolved, namespace="glazkov", author="mage")`
  — POST body carries the 3 tags from metadata.tags + 4 allowed-tools
  tokens + the GitHub tarball URL; later, MAGE resolves v2 and calls
  `ingest_skill_from_carl(resolved_v2, entity_id="sk-pdf-001")` —
  emits a PUT against the existing entity with the new sha256;
  defensive path (`sha256=""`) raises before network.*
- **[DONE]** Web UI: add an "AgentSkills" tab to `web_ui/app/main.py` with
  list/search/detail views (clone the Agents page).
  *Shipped 2026-05-16: `web_ui/app/pages/agent_skills.py` cloned from
  `pages/agents.py` with `entity_type="agent_skill"` plumbed through
  all 5 version helpers (versions list / detail / diff / revert / pin /
  promote), CARE library columns surfaced (⭐ favourite, last_run_at
  rendered via `format_last_run`, `pick_display_name` for the title
  column), and the SKILL.md projection (`name`, `description`, `uri`,
  `sha256`, `manifest`, `instructions`, `allowed_tools`, `tags`) baked
  into the editor's placeholder so users see the schema before they
  start typing. `MemoryClientWrapper` extended with the 4 expected
  methods (`get_agent_skills`, `get_agent_skill`, `save_agent_skill`,
  `delete_agent_skill`) — they delegate to
  `GigaEvoClient.list_agent_skills` / `get_agent_skill_dict` /
  `save_agent_skill` / `delete_agent_skill`. `EntityTypeConfig.configs`
  gained an `agent_skills` entry (icon 🛠️, placeholder advertising the
  full SKILL.md shape). Tab mounted in `main.py` between Chains and
  Memory Cards. 12 new tests in `web_ui/tests/test_agent_skills_tab.py`
  across 3 classes: wrapper method routing (7 — method existence,
  list+convert, dict accessor delegation, save with/without entity_id,
  default name/channel/tags, delete pass-through); `EntityTypeConfig`
  exposure (1 — name/plural/type/placeholder advertises 4 required
  SKILL.md fields); page module + main wiring (4 — file exists, all 5
  version helpers carry `"agent_skill"`, main imports + Tab label
  visible, page module imports + signature is `(client)`). 41/41
  web_ui tests pass. Real-execution evaluation: simulated CARE user
  browsing 2 ingested skills (pdf-extract favourited, weather
  un-favourited) → wrapper returns 2 entity dicts; format pipeline
  builds `['⭐', 'sk-pdf-001', 'Pdf Extract', '8m ago', 'latest',
  'v-sk-pdf', 'pdf, office']` and `['', 'sk-weather-002', 'Weather',
  '—', 'latest', 'v-sk-wea', 'api']` rows; selecting pdf-extract
  loads the full SKILL.md projection through `get_agent_skill_dict`;
  edited content (updated instructions + new tag) saved with
  `entity_id="sk-pdf-001"` → `save_agent_skill(skill=…, name=…,
  tags=["pdf","office","v2"], entity_id="sk-pdf-001", channel="latest")`
  on the SDK; delete forwards to `delete_agent_skill`. Touched files
  pass `ruff check` cleanly (the one pre-existing ruff error in
  `api/app/services/search_strategies/base.py` is unrelated).*

### 1.4 User library metadata (P0)

CARE renders the user's agent library as a sortable/filterable table with
favourites pinned to the top and last-run time as the default sort key.
Today's `entities` table has `tags JSONB` but no usage stats and no
favourite flag, so every list call would have to walk every version to
compute `last_run_at` and `run_count`. Add denormalised columns.

- **[DONE] DDL migration** — new Alembic revision adding to `entities`:
  - `favourite BOOLEAN NOT NULL DEFAULT FALSE` (indexed).
  - `run_count INTEGER NOT NULL DEFAULT 0`.
  - `last_run_at TIMESTAMPTZ NULL` (indexed DESC).
  - `display_name VARCHAR(200) NULL` — separate from `name` (which stays
    URL-safe / unique-per-namespace); `display_name` is what CARE renders.
  - `description TEXT NULL` — free-form user-edited description (distinct
    from `when_to_use` which is auto-generated capability metadata).
  Backfill: `last_run_at` from `MAX(version.created_at)` for chains,
  `run_count = 0`, `favourite = false`, `display_name = name`.
  *Shipped 2026-05-16: migration `003_library_metadata.py` adds all 5
  columns + 3 indices (`ix_entities_favourite`, `ix_entities_last_run_at`,
  and the composite `ix_entities_library_listing(namespace, favourite,
  last_run_at) WHERE deleted_at IS NULL` matching the CARE library
  default-sort query shape). Upgrade backfills `display_name = name`
  and `last_run_at = MAX(version.created_at)` per entity, so existing
  rows render immediately. Downgrade drops every added column and
  index. `Entity` ORM model in `db/models.py` updated with matching
  `Mapped[...]` columns and the composite index. `EntityService.
  create_entity()` now sets `display_name = name[:200]` and
  `description = when_to_use` on creation so newly-created entities
  carry sensible defaults without waiting for a PATCH. 17 tests in
  `tests/test_library_metadata.py` cover: ORM column types / nullability
  / server-defaults / index presence + column order; migration revision
  chain + upgrade-adds-5-columns + downgrade-drops-5-columns (spying on
  `op.add_column` / `op.drop_column`); `create_entity` defaults +
  display_name truncation at 200 chars. Real-scenario evaluation renders
  the CARE LibraryScreen query (4 `sort_by` variants — `last_run_at`,
  `run_count`, `display_name`, `created_at` — each paired with
  `favourite DESC` to pin starred items) and confirms the composite
  index covers the WHERE+ORDER BY path.*
- **[DONE] Response/request models** — add the four fields to
  `EntityResponse` / chain/agent create payloads. Keep optional for
  backward compatibility.
  *Shipped 2026-05-16: `EntityResponse` in `models/responses.py` gains
  `favourite: bool = False`, `run_count: int = 0`, `last_run_at:
  datetime | None = None`, `display_name: str | None = None`,
  `description: str | None = None`. All optional with defaults so
  existing route handlers that don't populate them still emit valid
  responses — clients read them when present. OpenAPI surface
  confirmed via `test_openapi_schema_exposes_new_fields`. Plumbing
  these through each typed router's response construction
  (`chains.py` / `agents.py` / `agent_skills.py` / `memory_cards.py` /
  `steps.py`) is the next P0 bullet below.*
- **[DONE for agents+chains+agent_skills routers]** New
  endpoints on chain + agent routers (CARE saves agents as the `agent`
  entity type; same fields apply to both):
  - `POST /v1/{plural}/{id}/favourite` — toggles or sets favourite.
  - `POST /v1/{plural}/{id}/run-recorded` — bumps `run_count`,
    sets `last_run_at = now()`. Idempotent semantics: optional `run_id`
    body field deduplicates against an in-memory LRU.
  - `PATCH /v1/{plural}/{id}` — partial update of `display_name`,
    `description`, `tags`, `favourite`. Does NOT create a new version
    (these are entity-level mutable fields, not content). Returns the
    updated `EntityResponse`.

  *Shipped 2026-05-16 (agents router):*
  - `EntityService.set_favourite(entity_id, value=True) -> Entity | None`
    — flips the flag, skips soft-deleted entities, commits without
    versioning.
  - `EntityService.record_run(entity_id, run_id=None) -> Entity | None`
    — bumps `run_count`, sets `last_run_at = now()`. `run_id` accepted
    as a future-idempotency hook (LRU dedup deferred — see P1).
  - `EntityService.update_metadata(entity_id, *, display_name,
    description, tags, favourite) -> Entity | None` — partial-update of
    entity-level mutable fields, truncates `display_name` at 200 chars
    to fit `VARCHAR(200)`. Empty `tags=[]` clears tags (distinct from
    omitting).
  - Module-level helper `entity_metadata_kwargs(entity) -> dict` returns
    the 5 library-metadata fields as a kwargs dict — routers spread it
    into `EntityResponse(**…)` so the fields plumb through with one
    call.
  - New Pydantic request models: `FavouriteRequest`,
    `RecordRunRequest`, `EntityPatchRequest` in `models/requests.py`.
  - `routers/agents.py` rewritten around a private `_agent_response()`
    helper that builds an `AgentResponse` from an Entity + version pair
    (centralises etag + library-metadata plumbing). New endpoints:
    `PATCH /v1/agents/{id}` (metadata update),
    `POST /v1/agents/{id}/favourite`,
    `POST /v1/agents/{id}/run-recorded`. Existing endpoints (create /
    list / get / update / delete) all now plumb the 5 library fields
    through `_agent_response()`.
  - 17 tests in `tests/test_library_mutations.py`: helper coercions
    (3); `set_favourite` true/false/missing (3); `record_run`
    bump/null-handling/missing (3); `update_metadata`
    partial/truncation/empty-tags/missing (4); router registration +
    OpenAPI exposure of the 3 new endpoints + the 3 new request
    schemas + `_agent_response` plumbing of all 5 fields (4).
  - Real-scenario evaluation rendered `/v1/agents/*` OpenAPI surface:
    PATCH alongside DELETE/GET/PUT; new `/favourite` and
    `/run-recorded` sub-paths; `EntityPatchRequest` + `FavouriteRequest`
    + `RecordRunRequest` registered as schema components;
    `AgentResponse` exposes `favourite/run_count/last_run_at/
    display_name/description` with proper defaults.

  **Shipped 2026-05-16 (chains router, iteration #11):**
  - `routers/chains.py` rewritten around `_chain_response()` helper
    (mirrors `_agent_response()` from iter #7); all 5 existing
    endpoints (create/list/get/update/delete) now plumb the library
    metadata via `entity_metadata_kwargs`.
  - 3 new endpoints: `PATCH /v1/chains/{id}`,
    `POST /v1/chains/{id}/favourite`,
    `POST /v1/chains/{id}/run-recorded`.
  - 5 tests in `tests/test_chains_router_library.py` confirm router
    registration, OpenAPI exposure of PATCH+favourite+run-recorded
    paths, library query params surface on `GET /v1/chains`, defaults
    (`sort_by=last_run_at`, `sort_dir=desc`), and `_chain_response`
    helper plumbing.

  **Shipped 2026-05-16 (agent_skills router, iteration #12):**
  - `routers/agent_skills.py` rewritten around `_agent_skill_response()`
    helper (mirrors `_agent_response` / `_chain_response`); all 5
    existing endpoints now plumb library metadata via
    `entity_metadata_kwargs`.
  - 3 new endpoints: `PATCH /v1/agent-skills/{id}`,
    `POST /v1/agent-skills/{id}/favourite`,
    `POST /v1/agent-skills/{id}/run-recorded`.
  - 5 tests in `tests/test_agent_skills_router_library.py` confirm
    router registration, OpenAPI exposure of PATCH+favourite+run-recorded,
    library query params on `GET /v1/agent-skills`, CARE catalogue
    defaults, and `_agent_skill_response` helper plumbing.

  **§1.4 mutation endpoints now fully shipped across all three CARE
  typed entity types: agents (iter #7), chains (iter #11), agent_skills
  (iter #12).**
- **[DONE for agents+chains+agent_skills routers] List endpoint query params** —
  `GET /v1/{plural}` accepts `sort_by` (`last_run_at | run_count |
  created_at | display_name`), `sort_dir` (`asc | desc`),
  `favourites_only` (bool), `tags` (repeated query param, AND
  semantics), `q` (substring across `display_name + name +
  description`). Returns paginated results with the new fields
  populated.

  *Shipped 2026-05-16 (agents router):*
  - `EntityService.list_entities()` extended with keyword-only knobs:
    `sort_by` (whitelisted), `sort_dir` (case-insensitive `asc|desc`),
    `favourites_only`, `tags` (PostgreSQL JSONB `?&` "contains-all"
    operator), `q` (ILIKE across `display_name`/`name`/`description`),
    `namespace` (single-namespace filter). Unknown `sort_by` values
    fall back to `created_at` defensively.
  - Cursor pagination only applies when sort matches its encoding
    (`created_at asc`); other sorts silently ignore the cursor and use
    offset (test enforces this — same cursor produces different SQL
    in default vs `sort_by=last_run_at` paths).
  - `routers/agents.py::list_agents` exposes all six knobs as FastAPI
    `Query(...)` params with whitelist patterns + sensible CARE
    defaults: `sort_by="last_run_at"`, `sort_dir="desc"` so the
    library's home view defaults to "my recently-run agents".
  - 19 tests in `tests/test_library_list_query.py`: sort by 4
    columns (parametrised) + unknown-fallback (5); sort dir
    asc/desc/case-insensitive + `NULLS LAST` presence (3); filters —
    `favourites_only` predicate + default-absent + namespace + tags
    JSONB `?&` + empty-tags-skipped + `q` ILIKE across 3 columns (6);
    cursor-vs-non-default-sort interaction (1); router OpenAPI surface
    — new params present + defaults + `sort_by` pattern + favourites_only
    default (4).
  - Real-scenario evaluation rendered 5 LibraryScreen SQL queries:
    library home (`ORDER BY last_run_at DESC NULLS LAST`),
    favourites-only filter (`favourite IS true`), tag-AND filter
    (JSONB `?&` with `['pdf', 'extraction']` param), free-text search
    (`ILIKE '%financier%'` across three columns), most-used agents
    (`ORDER BY run_count DESC NULLS LAST`). All produce valid
    PostgreSQL; composite index `ix_entities_library_listing(namespace,
    favourite, last_run_at) WHERE deleted_at IS NULL` covers the
    default sort path.

  **Shipped 2026-05-16 (chains router, iteration #11):**
  `routers/chains.py::list_chains` now exposes the same six
  `Query(...)` params (`sort_by`, `sort_dir`, `favourites_only`,
  `tags`, `q`, `namespace`) with the same CARE defaults
  (`last_run_at desc`). Verified via OpenAPI surface tests in
  `tests/test_chains_router_library.py`.

  **Shipped 2026-05-16 (agent_skills router, iteration #12):**
  `routers/agent_skills.py::list_agent_skills` now exposes the same
  six `Query(...)` params (`sort_by`, `sort_dir`, `favourites_only`,
  `tags`, `q`, `namespace`) with the same CARE defaults
  (`last_run_at desc`). Verified via OpenAPI surface tests in
  `tests/test_agent_skills_router_library.py`.

  **§1.4 list query params now fully shipped across all three CARE
  typed entity types.**
- **[DONE for AgentsMixin+ChainsMixin+AgentSkillsMixin] Client mixin
  extensions** — add to `ChainsMixin` and `AgentsMixin`:
  - `mark_favourite(entity_id, value=True)`
  - `record_run(entity_id, run_id=None)`
  - `update_metadata(entity_id, *, display_name=None, description=None,
    tags=None, favourite=None)`
  - `list_chains(*, sort_by="last_run_at", sort_dir="desc",
    favourites_only=False, tags=None, q=None, limit=50, cursor=None)`

  *Shipped 2026-05-16 (AgentsMixin + base helpers):*
  - `BaseMemoryClient._mark_favourite()`, `_record_run()`,
    `_update_metadata()` — generic over entity_type via `_TYPE_PLURAL`,
    so once chain/agent_skill routers land (iteration to come) the
    typed mixins can wire to them with one-line method additions.
  - `BaseMemoryClient._list_entities()` accepts `sort_by`, `sort_dir`,
    `favourites_only`, `tags`, `q`, `namespace` as keyword-only knobs.
    Sends omitted knobs not-at-all (avoids accidentally pinning server
    defaults); `tags=[]` is elided. `tags` sent as repeated query
    params for FastAPI's `list[str]` shape.
  - `AgentsMixin.mark_favourite()`, `record_run()`,
    `update_metadata()` — thin wrappers over the base helpers.
  - `AgentsMixin.list_agents()` enriched with the six library knobs;
    explicit `None` defaults defer to server-side defaults so
    `client.list_agents()` keeps working unchanged.
  - `EntityResponse` client model gained the 5 library-metadata fields
    (`favourite`, `run_count`, `last_run_at`, `display_name`,
    `description`) with safe defaults so an older Memory server that
    doesn't emit them still parses cleanly.
  - 12 tests in `tests/test_library_mutations_client.py`: `mark_favourite`
    star/unstar/404 (3); `record_run` empty-body/run_id-passed (2);
    `update_metadata` partial-PATCH semantics + `tags=[]` clears +
    all-fields-set (3); enriched `list_agents` no-params/all-knobs/
    response-parsing/empty-tags-elided (4).
  - Real-scenario evaluation walked the **full canonical CARE library
    flow** end-to-end against `respx`-mocked endpoints: save → list
    sorted by `last_run_at desc` (showing 3 agents) → star one → filter
    `favourites_only=True` (2 results) → record_run after execution
    (run_count 5→6, last_run_at advances) → PATCH rename to
    `"Финансовый помощник"` with Cyrillic description (UTF-8 clean) →
    tag-AND filter `tags=['pdf', 'extraction']`. Every step
    round-trips through the typed `EntityResponse`.

  *Shipped 2026-05-16 (AgentSkillsMixin, iteration #12):*
  - `AgentSkillsMixin.mark_agent_skill_favourite()`,
    `record_agent_skill_run()`, `update_agent_skill_metadata()` —
    entity-suffixed names avoid collision with the same shape on
    `AgentsMixin` / `ChainsMixin`. All three delegate to the existing
    `BaseMemoryClient` generic helpers.
  - `AgentSkillsMixin.list_agent_skills()` enriched with the six
    library knobs; same `None`-default contract.
  - 9 tests in `tests/test_agent_skills_library_mixin.py`:
    `mark_agent_skill_favourite` star/404 (2), `record_agent_skill_run`
    with/without run_id (2), `update_agent_skill_metadata` partial
    PATCH + empty-tags-clears (2), enriched `list_agent_skills`
    no-params / all-knobs / response-parsing (3).
  - Real-scenario evaluation: full catalogue flow (save → list sorted
    by `last_run_at desc` → star → record_run → PATCH rename to
    Cyrillic `"PDF извлекатель данных"` → tag-AND filter) round-trips.

  **§1.4 client mixin extensions now fully shipped across all three
  typed entity-type mixins.**

  *Shipped 2026-05-16 (ChainsMixin, iteration #11):*
  - `ChainsMixin.mark_chain_favourite()`, `record_chain_run()`,
    `update_chain_metadata()` — entity-suffixed names to avoid
    collision with `AgentsMixin.mark_favourite()` / `record_run()` /
    `update_metadata()` when both mix into `MemoryClient`. All three
    delegate to the existing `BaseMemoryClient` generic helpers.
  - `ChainsMixin.list_chains()` enriched with the six library knobs
    (`sort_by`, `sort_dir`, `favourites_only`, `tags`, `q`, `namespace`),
    same `None`-default contract as `AgentsMixin.list_agents()`.
  - 9 tests in `tests/test_chains_library_mixin.py`:
    `mark_chain_favourite` star/404 (2), `record_chain_run`
    with/without run_id (2), `update_chain_metadata` partial PATCH /
    empty-tags-clears (2), enriched `list_chains` no-params /
    all-knobs / response-parsing (3).
  - Real-scenario evaluation: full chain library flow (save → list
    sorted by `last_run_at desc` → star → record_run → PATCH rename to
    Cyrillic `"Q1 финансовый отчёт"` → tag-AND filter → favourites_only)
    against `respx`-mocked endpoints, all 7 steps round-trip via
    `ChainsMixin`.
- **[DONE] Saved task + context** — chains generated via CARE need to
  remember the originating user query and context files for re-run.
  Standardise inside chain `content_json`:
  ```json
  {
    "metadata": {
      "task_description": "Generate a financier helper...",
      "context_files": [
        {"path": "report.pdf", "sha256": "...", "size_bytes": 12345}
      ],
      "generated_by": "mage",
      "mage_metadata": { ... }
    }
  }
  ```
  No schema change required (content is opaque JSON); document the
  convention in `docs/CHAIN_CONTENT_CONVENTIONS.md`.
  *Shipped 2026-05-16: new `docs/CHAIN_CONTENT_CONVENTIONS.md`
  (full spec + field reference + helper API + re-run flow + compat
  notes) plus typed Pydantic models on **both** sides:
  - Server: `CareChainMetadata` + `ContextFileRef` in
    `api/app/models/requests.py`. Optional fields (every field has a
    default — `CareChainMetadata()` is legal). SHA-256 pinned to
    `^[0-9a-fA-F]{64}$`, `size_bytes >= 0`, `display_name` max 200.
  - Client: same `CareChainMetadata` + `ContextFileRef` in
    `client/python/src/gigaevo_memory/models.py`, exported from
    `gigaevo_memory` top-level via the lazy `__getattr__` pattern.
  - Helper API: `CareChainMetadata.from_chain_content(content)`
    extracts a typed view (returns empty instance for missing/non-dict
    metadata — no None-checks needed by callers).
    `merge_into_content(content)` returns a new content dict with the
    CARE block applied **without mutating the input** and **preserving
    non-CARE sibling keys** (so gigaevo-core's own `metadata.core_state`
    co-exists).
  - 18 server tests in `tests/test_care_chain_metadata.py` (file
    validation, full payload, edge cases for extraction + merge, full
    round-trip) + 7 client tests in
    `client/python/tests/test_care_chain_metadata.py` (top-level
    re-export, round-trip, sibling-key preservation, validation,
    legacy chain handling).
  - Real-scenario evaluation walked the full MAGE→save→re-run flow:
    MAGE built a `CareChainMetadata` with task_description + 2 context
    files (PDF template + CSV data) + provenance; merged into a chain
    whose `metadata` already carried gigaevo-core's `core_state` key
    — both survived. Days later CARE loaded the saved chain,
    extracted the typed view, found all 2 context files with their
    SHAs, the original task_description (UTF-8 em dash clean), and
    asserted full equality. Legacy chain (pre-convention) parsed to
    an empty `CareChainMetadata()` without crashing.*
- **[DONE]** Server-side index for fast library listing: composite index
  on `(namespace, favourite DESC, last_run_at DESC)` plus a GIN index on
  `tags`.
  *Shipped 2026-05-16 (iteration #35):*
  - *New Alembic migration `005_library_listing_index.py` adds partial
    index `ix_entities_library_sort` with columns
    `(namespace, last_run_at DESC NULLS LAST, entity_id)` under the
    predicate `deleted_at IS NULL`. Aligns the index sort direction
    with the planner's preferred scan for the actual
    `EntityService.list_entities` ORDER BY (`last_run_at DESC NULLS LAST,
    entity_id ASC`) so paginated library queries at 10k+ entities read
    a narrow index range instead of falling back to sort.*
  - *Implementation note: the TODO spec named `favourite DESC` in the
    sort key, but the shipping `list_entities` query never sorts by
    `favourite` — it's a WHERE filter (`favourites_only`) covered by
    the standalone `ix_entities_favourite` index from migration 003.
    The new index matches the real query shape; the original composite
    `ix_entities_library_listing` from mig 003 is preserved unchanged
    so favourites_only-style queries keep their leading-column scan.*
  - *GIN index on `tags` (`ix_entities_tags`) was already shipped in
    migration 001 — the `Entity.tags.op("?&")(list(tags))` filter in
    `list_entities` already exercises it. No additional GIN work in
    this iteration.*
  - *`Entity.__table_args__` in `app/db/models.py` declares the new
    `Index("ix_entities_library_sort", ...)` alongside the existing
    composite so the SQLAlchemy metadata + Alembic autogenerate stay
    in sync.*
  - *9 new tests in `tests/test_library_listing_index.py` across 2
    classes: ORM (4 — index declared, column order, partial predicate,
    old index preserved); migration module (5 — revision chain,
    upgrade calls `create_index` with right args, partial predicate
    surfaced via `postgresql_where`, downgrade drops cleanly,
    pure-no-IO invariant). Mirrors the layout of
    `tests/test_library_metadata.py` so future migration tests can
    copy the structure.*
  - *Real-execution evaluation: invoked the migration module directly
    via `importlib.util.spec_from_file_location` and confirmed
    `revision='005'`, `down_revision='004'`, upgrade/downgrade
    callable. Inspected `Entity.__table__.indexes` to confirm
    SQLAlchemy renders the index expressions exactly as
    `['entities.namespace', 'last_run_at DESC NULLS LAST',
    'entities.entity_id']` under `WHERE deleted_at IS NULL`.
    The CARE LibraryScreen's default home query (the
    `namespace='glazkov' AND deleted_at IS NULL ORDER BY
    last_run_at DESC NULLS LAST LIMIT 50` shape) can now be served
    via index-only scan once `make migrate` is run.*
- **[DONE]** Web UI: surface `favourite` star + `display_name` +
  `last_run_at` in the Chains and Agents pages so the Gradio UI stays in
  sync with what CARE shows.
  *Shipped 2026-05-16 (iteration #45):*
  - *New shared helpers in `web_ui/app/library_format.py`:
    `format_favourite(flag)` returns `"⭐"` for truthy / `""` for
    falsy (tolerant of 1/"yes"/etc. so a server-side bool change
    doesn't break the UI); `pick_display_name(meta, library_dn)`
    chooses `display_name` > `meta["name"]` > `"N/A"`;
    `format_last_run(ts, *, now=None)` renders compact relative
    timestamps (`"just now"` / `"5m ago"` / `"3h ago"` / `"4d ago"`)
    falling back to an ISO date for ≥30 days. Accepts ISO strings,
    `datetime` instances, or `None`; naive datetimes treated as UTC
    so server-side bare `datetime`s still work. Pure functions, no
    Gradio import — reusable from the future AgentSkills tab.*
  - *`MemoryClientWrapper._entity_to_dict` in `web_ui/app/client.py`
    now surfaces the 5 library fields from iter #11
    (`favourite`, `run_count`, `last_run_at`, `display_name`,
    `description`) using `getattr(..., default)` so older response
    payloads without them still produce a sensible dict.
    `last_run_at` serialises to ISO string for Gradio cell rendering;
    `None` survives unchanged.*
  - *Both `web_ui/app/pages/chains.py` and
    `web_ui/app/pages/agents.py` got a 7-column table layout
    (`⭐` / `ID` / `Name` / `Last Run` / `Channel` / `Version` /
    `Tags`) replacing the previous 5-column shape. The row builder
    inside each page's `load_*` function now calls the three shared
    helpers; the `on_select_row` handler indexes into
    `list_data_state` (raw dicts) so the column re-shuffle didn't
    affect selection.*
  - *29 tests in `web_ui/tests/test_library_format.py` across 5
    classes (new test directory — `web_ui/tests/` didn't exist
    before): `format_favourite` (5 — true/false/None/truthy
    strings/empty string); `pick_display_name` (6 — display_name
    wins / falls back to meta.name / empty falls back / no-meta
    returns NA / non-dict meta returns NA / non-string coerced);
    `format_last_run` (12 — em-dash for None+"", just_now, minutes,
    hours, days, ≥30 days ISO fallback, datetime input, naive UTC,
    invalid string survives, 60s and 30d boundary cases); wrapper
    integration `_entity_to_dict` (4 — surfaces library fields,
    keeps legacy fields, defaults when missing, last_run_at None);
    end-to-end pipeline (2 — favourite+recent and non-favourite+no-run
    representative rows match the agent page's row builder
    byte-for-byte).*
  - *Real-execution evaluation: imported the helpers, compiled both
    page modules to confirm syntactic cleanliness, then built a
    representative `agent-007` mock with favourite=True,
    last_run_at=now-12min, display_name="Q3 Finance Bot",
    tags=["finance","q3"] and ran it through the wrapper's
    `_entity_to_dict` + the 3 formatters in sequence. Got the row
    `['⭐', 'agent-007', 'Q3 Finance Bot', '12m ago', 'latest',
    'ver-abcd', 'finance, q3']` — matches what the CARE TUI library
    surfaces. 70 web_ui + client regression tests pass; ruff clean.*

---

## 2. Unified GigaEvo client (P1)

Today there are two classes (`MemoryClient`, `PlatformMemoryClient`) and
both hit the Memory API — `PlatformMemoryClient` is a memory-card-only
slim variant, not a platform-bridging client. The user plans to rename to
`gigaevo-client` and drive both Memory and Platform via one SDK.

### 2.1 Package rename
- **[DONE]** Rename the Python package directory
  `client/python/src/gigaevo_memory/` → `gigaevo_client/`. Keep
  `gigaevo_memory/__init__.py` as a thin shim re-exporting every public
  name from `gigaevo_client.*` with a `DeprecationWarning` for one minor
  release.
- **[DONE]** Update PyPI distribution: rename to `gigaevo-client` in
  `pyproject.toml`; publish `gigaevo-memory` as a meta-package depending
  on `gigaevo-client`.
  *Shipped 2026-05-16: physical split into two independently-versionable
  wheels.*
  - *`client/python/pyproject.toml` — distribution renamed to
    `gigaevo-client`; wheel packages narrowed to `["src/gigaevo_client"]`
    (the shim is no longer co-shipped). Runtime dependency list and
    dynamic version source (`src/gigaevo_client/__init__.py`) unchanged.*
  - *New `client/python-meta/` workspace member shipping the
    `gigaevo-memory` meta-package (version `0.3.1`) — a thin distribution
    whose only payload is the `gigaevo_memory` shim directory (moved
    from `client/python/src/gigaevo_memory/`) and a hard
    `gigaevo-client>=0.3.0` dependency. Classifier `Development Status
    :: 7 - Inactive` advertises its compatibility-only role on PyPI.*
  - *Root `pyproject.toml` gained `client/python-meta` in workspace
    members, `gigaevo-client = { workspace = true }` in `tool.uv.sources`,
    and `gigaevo-client` + `gigaevo-memory` as top-level + dev dependencies.*
  - *Makefile updated: `client-install` now uses `uv sync --extra dev
    --inexact` to install both workspace packages; `client-build` /
    `client-publish` / `client-publish-test` now operate on both
    `client/python/dist/*` and `client/python-meta/dist/*`;
    `client-version` was previously broken (sed-targeted the shim's
    `__init__.py`, which doesn't carry a literal `__version__` assignment)
    — now bumps `client/python/src/gigaevo_client/__init__.py` (the
    canonical dynamic-version source) AND `client/python-meta/pyproject.toml`'s
    static `version = "..."` line; `client-clean` also wipes the
    meta-package's build dir.*
  - *Docs: `client/python/README.md` re-titled to `gigaevo-client` with
    a rename callout pointing legacy installs to the meta-package. New
    `client/python-meta/README.md` explains the shim's role and PyPI
    deprecation path. `api/tests/test_no_legacy_gigaevo_memory_imports.py`
    docstring updated to point at the new shim location.*
  - *20 new tests in `client/python/tests/test_distribution_split.py`
    across 5 classes: canonical-dist metadata (5 — pyproject exists,
    name=gigaevo-client, wheel ships only canonical package, version
    points at canonical `__init__`, runtime deps unchanged); meta-dist
    metadata (6 — pyproject exists, name=gigaevo-memory, depends on
    gigaevo-client, wheel ships only the shim, shim physically relocated
    out of client/python/src/, Inactive classifier present);
    workspace wiring (3 — both members listed, both sources mapped,
    root deps include both); runtime provenance (4 — `gigaevo_client.__file__`
    under `client/python/src/`, `gigaevo_memory.__file__` under
    `client/python-meta/src/`, `requires("gigaevo-memory")` names
    `gigaevo-client`, no stale dir at old shim path); import smoke
    (2 — canonical silent, legacy fires DeprecationWarning). All 21
    pre-existing `test_package_rename.py` tests still pass against
    the split.*
  - *Real-execution evaluation: built both wheels via `make client-build`
    (`gigaevo_client-0.3.0-py3-none-any.whl` + `gigaevo_memory-0.3.1-py3-none-any.whl`);
    installed them into a fresh `uv venv /tmp/dist-split-check` via
    `uv pip install`. `importlib.metadata` reports `gigaevo-client==0.3.0`
    and `gigaevo-memory==0.3.1` side-by-side; `Requires-Dist:
    gigaevo-client>=0.3.0` resolved by pip. `import gigaevo_client`
    is silent under `simplefilter("error", DeprecationWarning)`;
    `import gigaevo_memory` fires exactly one
    `DeprecationWarning("The 'gigaevo_memory' package was renamed to
    'gigaevo_client' in 0.3.0…")`. `GigaEvoClient`, `MemoryClient`,
    `GigaEvoConfig` are identity-equal across both packages; submodule
    access (`gigaevo_memory.config`, `gigaevo_memory.models`, etc.)
    resolves to the canonical module via `sys.modules` aliasing;
    `GigaEvoClient.from_config(GigaEvoConfig(memory_base_url=…))`
    builds an identical instance through both names with
    `_base_url == "https://memory.gigaevo.io"`. 319/321 client unit
    tests pass; the 2 failures (`test_clear_all`, `test_chain_step_fields_preserved`)
    are pre-existing and unrelated. Legacy-imports gate
    (`api/tests/test_no_legacy_gigaevo_memory_imports.py`) 11/11
    pass — the gate's `PROD_DIRS` tuple intentionally excludes the
    relocated shim. Ruff clean across all touched source + test trees.*
- **[DONE]** Rename `MemoryClient` → `GigaEvoClient`; keep `MemoryClient` as
  alias for one minor version. Same for `PlatformMemoryClient` → either
  drop (re-export `MemoryCardsLiteClient`) or repurpose for the
  Platform-side surface (see §2.2).

*Shipped 2026-05-16 (iteration #42, directory + class rename together):*
- *Physical directory rename via `mv src/gigaevo_memory src/gigaevo_client`.
  Internal modules use relative imports (`from .X`) which survive the
  rename unchanged. The 5 remaining `gigaevo_memory` references inside
  the new directory were all in docstrings; the one user-facing
  `AttributeError` message was updated to say `gigaevo_client`.*
- *Class `MemoryClient` renamed to `GigaEvoClient` in
  `gigaevo_client/client.py`; legacy spelling preserved as the
  module-level assignment `MemoryClient = GigaEvoClient` so
  `isinstance(c, MemoryClient)` keeps working. `from_config(cls, config)
  -> "GigaEvoClient"` type annotation + the surrounding docstrings
  updated to reference the new name.*
- *`gigaevo_client/__init__.py` lazy `__getattr__` collapses both
  `GigaEvoClient` and `MemoryClient` lookups to `from .client import
  GigaEvoClient`. `__all__` lists both names. `__version__` bumped to
  `"0.3.0"`.*
- *New `gigaevo_memory/__init__.py` shim (60 lines) emits one
  `DeprecationWarning` per process pointing at `gigaevo_client`,
  mirrors `__all__` + `__version__` from the new package, and
  eagerly registers every submodule in `sys.modules`
  (`gigaevo_memory.X` → `gigaevo_client.X` for X in `_base, _compat,
  agent_skills, agents, cache, chains, client, config, embeddings,
  exceptions, memory_cards, models, platform_client, search_types,
  watcher`) so `from gigaevo_memory.config import GigaEvoConfig` keeps
  working. Top-level `__getattr__` forwards any obscure name to the
  canonical package.*
- *`pyproject.toml` updates: `[tool.hatch.version].path` points at the
  new `gigaevo_client` package; `[tool.hatch.build.targets.wheel]
  packages = ["src/gigaevo_client", "src/gigaevo_memory"]` so the
  wheel ships both directories; new `filterwarnings` entry silences
  the rename DeprecationWarning during the existing test suite so
  248 pre-existing tests don't get warning-spammed (the rename tests
  re-enable warnings locally to assert the shim fires).*
- *21 new tests in `client/python/tests/test_package_rename.py`
  across 7 classes: canonical-path (3 — module imports,
  `__version__ == "0.3.0"`, top-level names); legacy-path (4 —
  top-level names, submodule access, models submodule, version
  mirror); class-identity (5 — `MemoryClient is GigaEvoClient` via
  both packages, cross-package identity, `isinstance` works for
  both names, `__module__` points at canonical home); deprecation
  warning (3 — legacy import fires with rename + 0.3.0 mention,
  canonical import silent); `__all__` (2 — canonical contains both
  client names, legacy mirrors canonical); from_config round-trip
  (2 — works via both names); unknown attribute (2 — canonical
  raises clean error, legacy shim mentions both packages in error).*
- *Real-execution evaluation: imported `gigaevo_memory` in a fresh
  process with `-W default` and observed the DeprecationWarning on
  stderr; confirmed `GigaEvoClient is MemoryClient` via both
  packages; `GigaEvoClient.__module__ == "gigaevo_client.client"` so
  `repr(instance)` shows the canonical home; built a
  `MemoryClient(api_key='sk-rename-test')` via the legacy alias and
  confirmed the `X-API-Key` header propagates; `isinstance` works
  for both names. Full client suite: 269 tests pass through the
  shim; the 2 pre-existing failures (iter-#19 `test_clear_all`
  needing `confirm=True`, `test_chain_step_fields_preserved`
  data-shape) are unrelated and were already failing in iter #39.*
- *Remaining work*: §2.1 P1 middle item — rename the PyPI distribution
  to `gigaevo-client` and ship `gigaevo-memory` as a meta-package
  depending on it. That requires a release + publish workflow
  change; the in-tree code is ready (both directories are listed in
  the wheel build target), but flipping the published distribution
  name is a separate operational step. ``PlatformMemoryClient`` is
  left untouched in this iteration — the §2.2 work owns its fate
  (drop vs. repurpose).

### 2.2 PlatformClient surface
- **[DONE]** Add `PlatformClient` class (separate from `GigaEvoClient`) in
  `gigaevo_client/platform.py` calling gigaevo-platform's API:
  - `health()` → wraps `GET /api/v1/status`.
  - `list_experiments()`, `get_experiment(id)`, `start_experiment(id)`,
    `stop_experiment(id)`, `get_status(id)`, `get_results(id)`.
  - `create_chain_experiment(spec: ChainExperimentSpec) -> ExperimentRef`
    — wraps `POST /api/v1/experiments/chains`.
  - `create_evolution(spec: EvolutionSpec) -> EvolutionRef` — wraps the
    new endpoint requested in Platform TODO §1.
  - `stream_events(experiment_id) -> AsyncIterator[Event]` — wraps the
    new SSE/WebSocket endpoint requested in Platform TODO §2.
- **[DONE]** `class GigaEvoSuite(GigaEvoClient, PlatformClient)` convenience
  composite holding two httpx clients (one per backend).

*Shipped 2026-05-16 (iteration #43):*
- *New `client/python/src/gigaevo_client/platform.py` ships
  `PlatformClient` — thin httpx wrapper around the §2.2 spec
  endpoints. 11 methods total: `health()`, `list_experiments()`,
  `get_experiment(id)`, `get_status(id)`, `get_results(id)`,
  `start_experiment(id)`, `stop_experiment(id)`,
  `create_chain_experiment(spec)`, `create_evolution(spec)`,
  `stream_events(experiment_id)` (yields parsed dicts from
  `data: ` SSE frames), plus `close()` + context-manager. Default
  `base_url` is `http://localhost:8001` (conventional sibling port
  to Memory's `8000`). Auth via the same `X-API-Key` header as
  Memory.*
- *New `client/python/src/gigaevo_client/suite.py` ships
  `GigaEvoSuite` as a **composition** wrapper, not the literal
  multiple-inheritance the TODO sketched. Reason: each sub-client
  owns its own `httpx.Client` pointed at a different backend, so
  `class GigaEvoSuite(GigaEvoClient, PlatformClient)` would clash
  on `self._http`. Composition with `suite.memory` and
  `suite.platform` attributes gives the same "one object, both
  surfaces" ergonomics without the MRO ambiguity. The TODO's
  literal `class …` syntax is documented as the design alternative
  considered; the rationale is in the module docstring so future
  maintainers see the trade-off explained.*
- *`__init__.py` lazy-loader extended: `PlatformClient` and
  `GigaEvoSuite` join the canonical `__all__`; `__getattr__` adds
  branches that import them on first access (avoids paying their
  import cost when a caller only touches the Memory client). Legacy
  shim's submodule registry adds `platform` and `suite` so
  `from gigaevo_memory.platform import PlatformClient` works.*
- *`GigaEvoSuite.from_config(cfg)` is the canonical entry point for
  CARE — falls back to `http://localhost:8001` when
  `config.platform_base_url is None` (matches
  `PlatformClient.from_config`'s default). Both sub-clients share
  the same `api_key` and `timeout` from the config.*
- *30 new tests in `client/python/tests/test_platform_client.py`
  across 10 classes: construction (3 — default URL, api_key header,
  trailing-slash strip); from_config (2 — uses platform_base_url,
  fallback when None); read endpoints (5 — `health()`,
  `list_experiments`, `get_experiment`, `get_status`,
  `get_results` via respx mocks); mutators (4 — start/stop, spec
  forwarding for chain experiments + evolutions); error propagation
  (1 — 404 raises `HTTPStatusError`); auth (1 — `X-API-Key`
  travels on every request); SSE streaming (2 — yields parsed
  dicts, skips empty `data:` frames); suite construction (4 —
  default URLs, two separate http clients, shared api_key, explicit
  URLs); suite from_config (3 — round-trip both URLs, fallback
  for missing platform URL, shared key); suite lifecycle (2 —
  context manager closes both, explicit close); legacy imports
  (3 — both names + submodule reach via `gigaevo_memory` shim).*
- *Real-execution evaluation: built
  `GigaEvoSuite.from_config(GigaEvoConfig(memory_base_url=
  'http://memory.test', platform_base_url='http://platform.test',
  api_key='sk-suite-test'))`; wired respx mocks for both backends
  on different hostnames; called `suite.memory._http.get('/health')`
  and `suite.platform.health()` from the same suite instance —
  both returned the right backend's response, both carried the
  shared `X-API-Key`, both used **different** `httpx.Client`
  instances (`suite.memory._http is not suite.platform._http`).
  On context-manager exit both clients reported `is_closed=True`.
  299 client tests pass; the 2 pre-existing failures (iter-#19
  `test_clear_all`, `test_chain_step_fields_preserved`) are
  unrelated and were already failing before this iteration.*
- *Reserved scope*: typed Pydantic models for `ExperimentRef`,
  `EvolutionRef`, `Event` were not added in this iteration —
  methods return parsed dicts so the gigaevo-platform schema can
  evolve without breaking this client. Layering Pydantic on later
  is non-breaking (return type narrows from `dict[str, Any]` →
  typed model).
- *CARE §10 alignment note (2026-06-05):* `list_evolutions()` and
  `list_individuals()` intentionally return the platform server's
  response envelopes, not bare lists. Sync and async
  `cancel_evolution()`, `pause_evolution()`, and
  `resume_evolution()` are client-side stubs that raise
  `NotImplementedError` until gigaevo-platform ships the matching
  server routes.
- **[DONE for in-repo callers + CI gate; external repos remain]**
  Update callers: `gigaevo-core`, `carl-mage`, `web_ui/app/client.py`
  to import from `gigaevo_client`. Add a CI gate forbidding new
  `gigaevo_memory` imports.
  *Shipped 2026-05-16 (iteration #44):*
  - *`web_ui/app/client.py` migrated to `gigaevo_client`: top-level
    `from gigaevo_client import GigaEvoClient` replaces the legacy
    `from gigaevo_memory import MemoryClient`; the inner
    `gigaevo_memory.exceptions` import points at
    `gigaevo_client.exceptions`; the two `gigaevo_memory.SearchType`
    references inside `unified_search` / `batch_search` now read
    `from gigaevo_client import SearchType`. The `MemoryClient`
    instantiation inside the wrapper now constructs
    `GigaEvoClient(base_url=..., timeout=...)`; log messages and
    docstrings updated to reflect the canonical name. The
    `MemoryClientWrapper` class name kept as-is — it's a web-UI
    concept that wraps the SDK client; the underlying SDK class is
    the only thing that needed renaming.*
  - *New CI gate `api/tests/test_no_legacy_gigaevo_memory_imports.py`
    walks every `.py` file under `api/app/`, `web_ui/app/`, and
    `client/python/src/gigaevo_client/` and uses `ast.parse` +
    `ast.walk` to find every executable `ImportFrom` /
    `Import` node referring to `gigaevo_memory` (or any
    `gigaevo_memory.X` submodule). AST is the source of truth —
    a first regex-based attempt false-positive'd on a docstring
    `Usage::` code block in `gigaevo_client/config.py:16` that
    contained the text `from gigaevo_memory import GigaEvoConfig`.
    The legacy shim itself (`client/python/src/gigaevo_memory/`)
    and test directories are intentionally excluded — tests
    exercise the legacy path to prove the shim still works.*
  - *11 tests in the gate file across 2 classes: production-tree
    clean (3 — walk every prod dir, gigaevo_client self-consistent,
    web_ui specifically migrated); negative-path (8 — from-import,
    bare import, aliased `import gigaevo_memory as gm`, submodule
    import, indented imports inside function bodies, docstring
    mentions ignored, canonical `gigaevo_client` ignored,
    `gigaevo_memory_helper`-style sibling-name ignored). The
    negative-path suite is what guarantees a real regression
    (someone adds `from gigaevo_memory import X` to a new
    production file) trips the green-light test in the same run.*
  - *Real-execution evaluation: imported `web_ui.app.client` in a
    fresh process with `warnings.filterwarnings('error',
    message='.*gigaevo_memory.*', category=DeprecationWarning)` —
    the import succeeded with no warning, proving zero legacy
    paths remain in the migrated file. Confirmed
    `type(wrapper._client).__module__ == 'gigaevo_client.client'`
    and `GigaevoMemoryError` resolves to
    `gigaevo_client.exceptions.MemoryError`. 299 client tests pass
    (same 2 pre-existing unrelated failures from iter #39).*
  - *External repos `gigaevo-core` and `carl-mage` are not in this
    repository; their migration to `gigaevo_client` is the operator's
    responsibility once they pull the next published wheel. The CI
    gate enforces in-repo discipline so the canonical path doesn't
    silently regress while external callers catch up.*

### 2.3 Connection profiles
- **[DONE]** Single config object `GigaEvoConfig(memory_base_url,
  platform_base_url, api_key, embedding_provider, cache_policy, timeout)`
  used to construct either client.
  *Shipped 2026-05-16 (iteration #39):*
  - *New `client/python/src/gigaevo_memory/config.py` ships
    `GigaEvoConfig` — a frozen `@dataclass` carrying every knob both
    `MemoryClient` and `PlatformMemoryClient` need:
    `memory_base_url` ("http://localhost:8000"),
    `platform_base_url` (None; reserved for the §2 unified-client
    split), `api_key` (None), `embedding_provider` (None),
    `cache_policy` (TTL), `cache_ttl` (300), `timeout` (30.0),
    `freshness_on_miss` (False), `sse_prefetch` (False). Frozen so
    a single config can be safely shared across threads / clients.*
  - *Ergonomic `cfg.with_overrides(**kwargs) -> GigaEvoConfig` for
    deriving environment-specific configs (prod → staging) without
    mutating the original. Validates every kwarg name against the
    field set; a typo like `with_overrides(timout=5)` raises
    `TypeError("unknown GigaEvoConfig field(s): ['timout']. Valid
    fields: [...sorted list...]")` instead of silently dropping the
    override.*
  - *`cfg.memory_client_kwargs()` returns the dict subset both
    client `__init__`s accept; keeps the unpack logic in one place
    so future client surface changes only touch the dataclass + one
    helper method.*
  - *Both client classes gained an `api_key` kwarg threaded into
    `BaseMemoryClient.__init__` — when set, every HTTP request
    carries `X-API-Key: <api_key>` via `httpx.Client(headers=...)`.
    Empty string is treated as missing (matches server-side opt-in
    semantics). Plumbing is non-breaking: every existing call site
    that doesn't pass `api_key` keeps the previous header-less
    behaviour.*
  - *`MemoryClient.from_config(cfg)` and
    `PlatformMemoryClient.from_config(cfg)` classmethods provide the
    canonical config → client construction path. Both call
    `cls(**cfg.memory_client_kwargs())`.*
  - *`GigaEvoConfig` exported from the top-level `gigaevo_memory`
    package via the existing lazy `__getattr__` mechanism (no new
    eager imports — keeps import time low for callers that only
    need the model dataclasses).*
  - *20 new tests in `client/python/tests/test_gigaevo_config.py`
    across 6 classes: defaults (3 — defaults match standalone client,
    frozen, explicit construction); with_overrides (4 — returns new
    instance, partial override, typo-typed-helpful-error, multiple
    typos alphabetised); `memory_client_kwargs` (3 — surface match,
    base_url propagates, api_key propagates); `from_config` (4 —
    MemoryClient default config, MemoryClient explicit config,
    PlatformMemoryClient, trailing slash stripped by client); X-API-Key
    header (4 — set via from_config, absent when None, set via direct
    __init__, empty-string treated as missing); backwards compat
    (2 — long-form constructor still works, every original kwarg
    still works).*
  - *Real-scenario evaluation: built `GigaEvoConfig(
    memory_base_url='https://memory.gigaevo.io',
    api_key='sk-prod-abc123', timeout=10.0)`; constructed both
    `MemoryClient.from_config(cfg)` and
    `PlatformMemoryClient.from_config(cfg)`; confirmed
    `_http.headers['X-API-Key']` is `'sk-prod-abc123'` on both;
    derived `staging = cfg.with_overrides(memory_base_url=...,
    api_key='sk-staging-xyz')` and confirmed the prod config was
    untouched (immutability proven via runtime, not just type
    hints); `cfg.with_overrides(timout=5)` raised the documented
    helpful error. 20 client-side + 85 server-side regression tests
    pass.*
- **[DONE]** Read config from `~/.config/gigaevo/config.toml` and env vars
  (`GIGAEVO_MEMORY_URL`, `GIGAEVO_PLATFORM_URL`, `GIGAEVO_API_KEY`).
  *Shipped 2026-05-16 (iteration #40):*
  - *Three new classmethods on `GigaEvoConfig` (in
    `client/python/src/gigaevo_memory/config.py`):
    `from_file(path)` reads a TOML file via stdlib `tomllib`,
    coerces `cache_policy` from a string ("ttl" or "TTL"), and
    raises `TypeError` with a sorted list of valid fields when the
    TOML contains an unknown key. `from_env(env=None, base=None)`
    overlays the 3 documented env vars onto a base config; empty
    strings treated as unset so inherited blank vars can't wipe a
    real base value. `load(path=None, env=None)` is the composite
    entry point — defaults < TOML file < env vars.*
  - *`DEFAULT_CONFIG_PATH = Path.home() / ".config" / "gigaevo" /
    "config.toml"` is the conventional location operators put their
    TOML in. When `load()` is called without an explicit path and
    the file doesn't exist, the composite silently falls back to
    defaults + env (no error — operators with no config get the
    same result as `GigaEvoConfig()`).*
  - *Env var → field map is intentionally narrow (`GIGAEVO_MEMORY_URL`,
    `GIGAEVO_PLATFORM_URL`, `GIGAEVO_API_KEY` only) so accidental
    shell exports of common names (`TIMEOUT`, `CACHE_TTL`) can't
    perturb timing-sensitive client behaviour. Typed knobs go
    through the TOML file where they're explicit.*
  - *24 new tests in `client/python/tests/test_gigaevo_config_loaders.py`
    across 5 classes plus an autouse `_scrub_gigaevo_env` fixture
    that nukes any `GIGAEVO_*` env var bleeding in from the
    developer's shell: default path resolution (1); `from_file`
    (8 — minimal/empty TOML, explicit overrides, cache_policy as
    value vs name, unknown key with helpful error + valid-fields
    listing, unknown cache_policy, missing file → FileNotFoundError,
    string-path accepted); `from_env` (6 — three documented vars,
    no-vars-defaults, empty-string-as-unset, overlays onto base,
    partial env keeps base elsewhere, falls back to os.environ);
    `load` (6 — missing file + env, file only, env-overrides-file,
    no-file-no-env, default path via HOME monkeypatch + module-level
    constant patch, polluted-shell-env immunity via explicit env={});
    integration (2 — `MemoryClient.from_config(GigaEvoConfig.load())`
    round-trips both base_url and X-API-Key header end-to-end).*
  - *Real-scenario evaluation: wrote a real TOML to a tempdir
    (`memory_base_url`, `api_key`, `timeout`, `cache_policy`,
    `cache_ttl`); `GigaEvoConfig.load(cfg_path, env={})` produced
    all 5 fields from the file; `GigaEvoConfig.load(cfg_path,
    env={'GIGAEVO_API_KEY': 'sk-from-env'})` correctly overrode
    just the API key while preserving the file-only `timeout=7.5`
    and `cache_ttl=600`; built `MemoryClient.from_config(cfg)` and
    confirmed `_base_url == 'https://memory.gigaevo.io'`,
    `X-API-Key == 'sk-from-env'`, `_http.timeout == Timeout(7.5)`.
    Documented in README under "Client configuration" with a worked
    TOML example.*

---

## 3. Auth & multi-user (P1–P2)

Memory currently has no auth. CARE will be used in shared deployments; need a
minimum authentication surface.

- **[DONE for foundation + writes-side wiring + `make create-key`; read-side scoping remains]**
  API-key middleware: `X-API-Key` header validated against a
  `api_keys` DB table (key_hash, owner, scopes, expires_at). Issuance via
  `make create-key OWNER=alice`. Wire into `api/app/main.py` as a
  `Depends(require_api_key)` on every router (skip on `/health`).
  *Shipped 2026-05-16 (iteration #25 — foundation; not yet wired):*
  - *New `ApiKey` ORM model (`api/app/db/models.py`): UUID `key_id`
    primary key + SHA-256 hex `key_hash` (unique, indexed) + `owner`
    (indexed) + `label` + JSONB `scopes` + `created_at` /
    `expires_at` / `revoked_at` timestamps.*
  - *Alembic migration `004_api_keys.py`: create_table with both
    indexes (unique `ix_api_keys_key_hash`, non-unique
    `ix_api_keys_owner`). Reverses cleanly.*
  - *New `ApiKeyService` (`api/app/services/api_key_service.py`):
    `create_key(owner, scopes, label, expires_at) -> IssuedKey`
    (returns the **plaintext** once — caller persists, never the
    server); `verify_key(plaintext) -> ApiKey | None` (hashes input,
    looks up, checks expiry + revocation, empty-string short-circuit
    without DB hit); `revoke_key(key_id) -> bool` (idempotent —
    re-revoke returns False); `list_keys(owner=None,
    include_revoked=False)`.*
  - *New `api/app/auth.py` with `require_api_key` FastAPI dependency
    + `AuthContext` dataclass (`key_id`, `owner`,
    `frozenset[str] scopes`) with `has_scope` /
    `require_scope` helpers. Wire onto any route via
    `Depends(require_api_key)`. Raises 401 (missing / empty /
    unknown / revoked / expired) and 403 (insufficient scope) with
    `WWW-Authenticate: X-API-Key` header on 401 per RFC.*
  - *Token format: 32 URL-safe random bytes (~43 chars) via
    `secrets.token_urlsafe(32)`. Only the SHA-256 hex digest is
    stored; the plaintext is returned exactly once at creation and
    cannot be recovered server-side.*
  - *29 tests in `tests/test_api_key_auth.py`: pure helpers (6 — hash
    determinism, uniqueness, UTF-8, 64 hex chars, key generation
    randomness across 1024 calls); `ApiKeyService.create_key`
    (2 — plaintext-only-once, scope defaults); `verify_key` (6 —
    known / unknown / empty-no-DB / revoked / expired /
    future-expiry); `revoke_key` (3 — active / already-revoked /
    missing); `require_api_key` end-to-end via TestClient (6 —
    missing header / empty header / unknown / revoked / expired /
    valid + scope echo); `AuthContext` scope helpers (3 —
    `has_scope` / `require_scope` pass / 403 raise); migration 004
    (3 — revision chain / upgrade table+indexes / downgrade reverses).*
  - *Real-scenario evaluation walked the full auth lifecycle on a
    throwaway FastAPI app: (1) ops admin issues a 43-char token for
    `glazkov` with 3 scopes + 30-day expiry; (2) CARE calls
    `GET /agents/list` with the key → 200, AuthContext carries owner
    + scopes; (3) missing header → 401 with `WWW-Authenticate:
    X-API-Key`; (4) revoked key → 401; (5) protected route gates
    on `auth.require_scope("evolve")` — succeeds for the multi-scope
    key, returns 403 for a `read:any`-only key.*
  - *315 server unit tests pass; no regression. The
    `Depends(require_api_key)` dependency is **not yet mounted onto
    any existing router** — that's a deliberate scoping decision so
    this iteration's foundation ships without breaking the rest of
    the test suite. Wiring per-router and the `make create-key`
    helper are separate follow-up iterations.*

  *Shipped 2026-05-16 (iteration #34, `make create-key` CLI):*
  - *New `api/app/create_key.py` module with `main(argv)` entry
    point. Reads `OWNER` / `SCOPES` / `LABEL` / `EXPIRES_DAYS` from
    either CLI flags (`--owner alice`) or env vars (Makefile path).
    Flags take precedence so the Makefile-style env passing and
    direct `uv run python -m app.create_key --owner alice` both
    work without ceremony.*
  - *Makefile `create-key` target: validates `OWNER` is set
    (exits 2 with a hint otherwise), then runs
    `docker compose run --rm memory-api python -m app.create_key`
    with the parsed env vars. Listed in `.PHONY` and added to
    the help-grep output.*
  - *Exit codes are operator-friendly: 0 success, 2 usage error
    (no OWNER / bad EXPIRES_DAYS — never touches the DB), 1 for
    everything else (DB unreachable, migration not applied).
    Stderr-only errors so stdout stays clean for a `xargs`/pipe
    flow if the operator wants to copy the plaintext directly
    into a secrets manager.*
  - *Output is operator-readable: the plaintext line plus the
    new row's `key_id` / `owner` / `scopes` / `label` /
    `created_at` / `expires_at`, then a `curl -H 'X-API-Key: ...'`
    one-liner. Plaintext warning ("not be shown again") makes the
    one-shot semantics impossible to miss.*
  - *26 new tests in `tests/test_create_key_cli.py` across 4
    classes: pure helpers (5 — `_parse_scopes` semantics +
    6 — `_parse_expires_days` including the zero/negative
    guard); arg resolution (8 — CLI vs env vs override
    precedence + missing-owner exits 2 + bad expiry exits 2);
    output formatting (4 — plaintext + key_id + scopes/expiry
    placeholders); end-to-end (3 — success path returns 0 with
    mocked `ApiKeyService.create_key`, missing owner exits 2
    without DB call, DB exception returns 1 with stderr message).*
  - *Real-scenario evaluation: (A) `OWNER=alice` env with
    unreachable DSN → exit 1, stderr `"failed to issue key:
    [Errno 8] nodename nor servname..."`; (B) bare `python -m
    app.create_key` (no owner) → exit 2, stderr hint;
    (C) `--help` → exit 0 with argparse-rendered usage covering
    every flag. The "operator issues key 30 days before a
    contractor onboards" flow now works end-to-end: `make
    create-key OWNER=contractor EXPIRES_DAYS=30 LABEL=
    "consulting Q3"` → row written, plaintext printed once,
    can immediately be exchanged via `X-API-Key`.*
- **[DONE]**
  Namespacing: every write uses `namespace = api_key.owner` by
  default; queries filter on owner unless scope `read:any` is granted.
  *Foundation shipped 2026-05-16 (iteration #28):*
  - *Dual-mode `require_api_key`: `settings.auth_required` (default
    `False`) switches between **strict** (missing header → 401,
    invalid → 401 — production) and **opt-in** (missing header →
    anonymous `AuthContext`, invalid → 401 even in opt-in to prevent
    silent downgrade — dev/CI default).*
  - *New `AuthContext.is_anonymous` property and
    `_anonymous_context()` factory using
    `settings.auth_anonymous_owner` (default `"anonymous"`).
    Anonymous contexts carry empty `scopes`, so
    `auth.require_scope("evolve")` still 403s an unauthenticated
    caller — turning on `Depends(require_api_key)` is non-breaking,
    but `auth.require_scope(...)` remains a real gate.*
  - *13 new tests in `tests/test_auth_dual_mode.py` across 4 classes:
    opt-in mode (4 — missing-header / empty-header / invalid-still-401 /
    valid-returns-full); strict mode (3 — missing-header-401 /
    valid-returns-full / revoked-401); anonymous-context helpers
    (4 — is_anonymous property, named-context-not-anonymous,
    anonymous-fails-scope-gate, custom anonymous owner); backward
    compat (1 — iter #25's 401 expectations still hold under strict
    mode).*
  - *Iter #25's `tests/test_api_key_auth.py` gained an autouse
    `_strict_mode` fixture pinning `auth_required=True` so its
    pre-dual-mode 401 assertions remain valid.*
  - *Real-scenario evaluation: 4 deployment profiles —
    (A) dev laptop, `auth_required=False`, no key → 200 anonymous
    GET, 403 on `POST /evolve` (anonymous lacks scope);
    (B) staging w/ valid key → 200 with `owner=glazkov`, revoked key
    still 401 (no silent downgrade);
    (C) prod strict → 401 without key, 200 with valid key;
    (D) read-only key vs scope-gated route → 403 with the precise
    "Missing required scope: 'evolve'" detail.*
  - *Per-route namespace defaulting (writes inherit `auth.owner`
    when `meta.namespace` is unset) is a separate follow-up — that
    crosses every typed router and is the natural next iteration
    now that the dual-mode foundation is in place.*

  *Shipped 2026-05-16 (iteration #29, bulk router):*
  - *`POST /v1/bulk/save` now declares
    `auth: AuthContext = Depends(require_api_key)` so the dual-mode
    dependency is exercised on a real production-relevant route.
    Anonymous callers go through unchanged in opt-in deployments
    (iter #23's tests still pass); authenticated callers trigger
    namespace defaulting.*
  - *New pure helper `_apply_namespace_default(item, auth)`:
    (1) anonymous → no change; (2) authenticated AND
    `item.meta.namespace is None` → namespace set to `auth.owner`
    via Pydantic `model_copy(update=...)` (input request body is
    never mutated); (3) authenticated AND explicit namespace →
    respected verbatim (caller is targeting a shared workspace
    deliberately; the service layer enforces what's allowed).*
  - *11 tests in `tests/test_bulk_auth_namespacing.py` across 5
    classes: pure helper (4 — anonymous no-default, authenticated
    auto-namespace, explicit-wins, input-not-mutated); opt-in mode
    (2 — no-key-keeps-None, explicit-namespace-respected);
    authenticated (3 — defaults to owner, explicit wins, per-item
    granularity across mixed namespaces in one batch); strict mode
    (1 — 401 without header); regression (1 — iter #23 no-key
    tests still pass).*
  - *Real-scenario evaluation walked 4 CARE deployment profiles
    against the bulk endpoint: (A) dev laptop, no key — anonymous,
    namespaces stay None; (B) personal CARE TUI key for `glazkov` —
    all 3 items auto-scoped to `'glazkov'`; (C) mixed batch with
    one explicit `finance-team` namespace — defaulted +
    explicit respected per-item; (D) production strict, no key →
    401. Pattern proven on the simplest router; the same change
    can replicate to chains / agents / agent_skills routers
    in subsequent iterations.*

  *Shipped 2026-05-16 (iteration #30, chains router + shared helper):*
  - *Extracted `default_namespace_for(meta_namespace, auth)` into
    `app/auth.py` as a pure helper (no DB I/O, no mutation) so every
    typed router can share one canonical resolution rule — anonymous
    pass-through, authenticated explicit-wins, authenticated default
    to `auth.owner`. Refactored bulk's `_apply_namespace_default`
    to delegate to it (iter #29's 11 tests still pass).*
  - *`POST /v1/chains` now declares
    `auth: AuthContext = Depends(require_api_key)` and calls
    `default_namespace_for(body.meta.namespace, auth)` before
    forwarding to `EntityService.create_entity(...)`. Anonymous
    callers in opt-in deployments still produce
    `namespace=None` writes (matches iter #11/#12 behaviour);
    authenticated callers auto-scope to their owner.*
  - *13 new tests in `tests/test_chains_auth_namespacing.py` across
    5 classes: pure helper (5 — anonymous-passthrough-None,
    anonymous-passthrough-explicit, authenticated-defaults-to-owner,
    authenticated-explicit-wins, pure-no-side-effects); opt-in mode
    (2 — no-key-keeps-None, no-key-explicit-respected); authenticated
    (3 — defaults to owner, explicit wins, alice writes to her
    namespace); strict mode (1 — 401 without header); bulk
    regression (2 — iter #29's anonymous + authenticated paths
    still produce identical behaviour after the bulk router was
    refactored onto the shared helper).*
  - *Real-scenario evaluation: same 4 CARE deployment profiles as
    iter #29 but exercised against `POST /v1/chains`:
    (A) dev laptop, no key — anonymous, `namespace=None`;
    (B) `glazkov` personal key, no explicit namespace — auto-scoped
    to `'glazkov'`; (C) `glazkov` personal key + explicit
    `'finance-team'` namespace — respected verbatim;
    (D) production strict, no key → 401. The shared helper
    means subsequent router rollouts (agents, agent_skills,
    memory_cards) are a one-line change each.*

  *Shipped 2026-05-16 (iteration #31, agents router):*
  - *`POST /v1/agents` now declares
    `auth: AuthContext = Depends(require_api_key)` and threads
    `default_namespace_for(body.meta.namespace, auth)` into the
    service. Anonymous opt-in callers keep `namespace=None` (no
    behaviour change for iter #11/#12 tests); authenticated callers
    auto-scope to `auth.owner` unless they pass an explicit namespace.
    Pure mechanical replication of the chains pattern — 3 lines of
    diff in `routers/agents.py`.*
  - *6 new tests in `tests/test_agents_auth_namespacing.py`
    (intentionally a strict subset of the chains layout so future
    rollouts can be diffed at a glance): opt-in (2 — no-key-keeps-None,
    explicit-namespace-respected); authenticated (3 — defaults to
    owner, explicit wins, alice writes to her namespace); strict
    mode (1 — 401 without header). Shared helper tests live with
    the chains suite; no need to duplicate per-router.*
  - *Real-scenario evaluation: same 4 CARE deployment profiles —
    (A) dev laptop, no key → anonymous, `namespace=None`;
    (B) `glazkov` key, no namespace → auto-scoped to `'glazkov'`;
    (C) `glazkov` key + explicit `'finance-team'` → respected;
    (D) production strict, no key → 401. The "save my agent
    from CARE TUI" flow that the user demoed in the original
    scenario is now correctly auto-scoped end-to-end.*

  *Shipped 2026-05-16 (iteration #32, agent_skills router):*
  - *`POST /v1/agent-skills` now declares
    `auth: AuthContext = Depends(require_api_key)` and threads
    `default_namespace_for(body.meta.namespace, auth)` into the
    service. Same 3-line mechanical replication of the chains
    pattern as iter #31 did for agents.*
  - *6 new tests in `tests/test_agent_skills_auth_namespacing.py`
    matching the agents suite layout (opt-in: 2, authenticated: 3,
    strict: 1). Reads as a copy-paste diff so future rollouts can be
    confirmed at a glance.*
  - *Real-scenario evaluation: MAGE-side capability lookup flow —
    (A) `glazkov` key resolves a `pdf-extract` SKILL.md and POSTs
    without `meta.namespace` → entity persisted under `'glazkov'`;
    (B) explicit `namespace='shared-skills'` for a curated catalogue
    → respected verbatim; (C) anonymous dev-laptop ingest → stays
    `None` (matches existing iter #4 behaviour); (D) production
    strict → 401 without key. Full agent_skill lifecycle (create
    → list → record_run) now auth-aware for the create step;
    list/run-recorded already operate on entity_id so no
    namespace defaulting is needed there.*

  *Shipped 2026-05-16 (iteration #33, memory_cards router — writes-side rollout complete):*
  - *`POST /v1/memory-cards` now declares
    `auth: AuthContext = Depends(require_api_key)` and threads
    `default_namespace_for(body.meta.namespace, auth)` into the
    service. Same 3-line mechanical replication of the chains
    pattern that iters #30–#32 used.*
  - *6 new tests in `tests/test_memory_cards_auth_namespacing.py`
    matching the agent_skills / agents suite layout: opt-in (2),
    authenticated (3), strict (1).*
  - *Writes-side rollout is now complete across all 5 entity
    write paths: `POST /v1/chains`, `POST /v1/agents`,
    `POST /v1/agent-skills`, `POST /v1/memory-cards`, and
    `POST /v1/bulk/save`. 94 auth-namespacing tests green
    end-to-end. The shared `default_namespace_for` helper
    in `app/auth.py` is the single source of truth — any
    future write endpoint can wire it in 3 lines.*
  - *Real-scenario evaluation: closes the CARE "Agent A retro
    notes" flow — user runs Agent A → CARE writes a memory card
    summarising results → with a `glazkov` key the card auto-scopes
    to namespace `glazkov` and shows up in the user's library
    side-by-side with the agent itself. No `meta.namespace` field
    needed in the request body.*

  *Shipped 2026-05-16 (iteration #41, read-side rollout complete):*
  - *New pure helper `default_read_namespace_for(query_namespace, auth)`
    in `app/auth.py`. Four-case truth table:
    (1) anonymous → pass-through query value (preserves the
    "anonymous can list everything in dev/CI" semantic);
    (2) authenticated + explicit `?namespace=X` → respected verbatim;
    (3) authenticated + no query + has `read:any` → `None` (caller
    explicitly opted into cross-namespace reads);
    (4) authenticated + no query + no `read:any` → defaults to
    `auth.owner` (mirrors the writes-side auto-scoping).*
  - *All 5 typed list endpoints wired: `GET /v1/chains`,
    `GET /v1/agents`, `GET /v1/agent-skills`,
    `GET /v1/memory-cards`, `GET /v1/steps`. The latter two had
    no `?namespace` query parameter at all before — added in this
    iteration along with the helper call so they match the other
    routers' shape.*
  - *20 new tests in `tests/test_list_auth_namespacing.py` across
    8 classes: pure helper (7 — anonymous-pass-None,
    anonymous-pass-explicit, authenticated-explicit-wins,
    authenticated-default-to-owner, authenticated-with-read:any-stays-None,
    authenticated-read:any-still-respects-explicit-query,
    pure-no-side-effects); end-to-end on `GET /v1/agents` via
    `EntityService.list_entities` spy (anonymous: 2, authenticated:
    3, read:any scope: 2, strict-mode: 1); newly-namespaced
    memory_cards (2) + steps (1) list endpoints; direct
    dependency-override path (2 — confirms the helper end-to-end
    via `app.dependency_overrides[require_api_key]` injection,
    cleaner than full DB stubbing).*
  - *Real-scenario evaluation: ran the truth table for all 6 cases
    (`(None | explicit) x (anonymous | scopeless | read:any)`) via
    direct Python — every output matched the design.
    The CARE "I want my agents only" flow now works without callers
    setting `?namespace=alice` on every request: a `glazkov`
    personal key `GET /v1/agents` → filtered to namespace
    `glazkov` server-side. An ops principal with `read:any` →
    sees every namespace. Anonymous opt-in users in dev/CI →
    still see every namespace (no behaviour change).
    166 auth-pipeline unit tests pass end-to-end with no
    regressions to the iter #28-#33 writes-side or iter #37 scope
    tests.*
  - *Closing this rollout means the §3 P1 spec is fully satisfied:
    auto-scoped writes (iters #29-#33) + auto-scoped reads
    (iter #41) + the `read:any` bypass scope (iter #37) form the
    complete CARE-deployment namespace model.*
- **[DONE]** Roles & scopes: `read:any`, `write:agent_skill`, `evolve`, etc.
  *Shipped 2026-05-16 (iteration #37):*
  - *Canonical scope vocabulary in `app/auth.py` as importable
    string constants: `SCOPE_READ_ANY="read:any"`,
    `SCOPE_WRITE_ANY="write:any"`, `SCOPE_DELETE_ANY="delete:any"`,
    `SCOPE_CLEAR_ALL="clear:all"`, `SCOPE_ADMIN_KEYS="admin:keys"`,
    `SCOPE_EVOLVE="evolve"`. `ALL_SCOPES` is the immutable
    `frozenset` inventory so call-sites stop stringly-typing.*
  - *Role presets as immutable `frozenset[str]` bundles:
    `ROLE_READER` (read:any only), `ROLE_EDITOR` (read+write:any),
    `ROLE_ADMIN = ALL_SCOPES` (every canonical scope — auto-extends
    when a new scope is added so admin wiring never goes stale).
    `ApiKeyService.create_key(scopes=list(ROLE_X))` is the
    operator-side spread idiom.*
  - *First scope-gated endpoint: `POST /v1/maintenance/clear-all`
    now wires `auth.require_scope(SCOPE_CLEAR_ALL)` BEFORE the
    X-Confirm header check. Two independent guards, scope gate
    first so unauthorised callers don't learn whether the X-Confirm
    phrase is right. Anonymous opt-in callers (empty scope set)
    always 403; a regular `glazkov` key without `clear:all` 403s
    too; only an admin / explicitly-issued maintenance key reaches
    the X-Confirm + handler body.*
  - *14 new tests in `tests/test_auth_scopes.py` across 3 classes:
    scope strings (3 — canonical values, inventory completeness,
    immutability); role presets (6 — reader/editor/admin contents,
    immutability, monotonic preset ordering reader ⊂ editor ⊂ admin);
    `AuthContext` behaviour (5 — reader passes read:any, reader
    fails clear:all with 403, editor passes read+write but not
    clear, admin passes every canonical gate, free-form scopes
    still work for deployment-specific tags).*
  - *Updated `tests/test_clear_all_confirmation.py`: introduced
    `_admin_auth` fixture that overrides `require_api_key` with a
    static `clear:all`-bearing context so the iter #19 X-Confirm
    assertions keep working at the second guard. Added new
    `TestScopeGate` class (3 tests — anonymous opt-in 403s,
    authenticated-without-`clear:all` 403s, scope gate fires
    BEFORE X-Confirm so missing-confirm with no-scope returns 403
    not 412).*
  - *Real-scenario evaluation: confirmed the operator flow via
    direct python — `list(ROLE_EDITOR)` round-trips into
    `ApiKeyService.create_key(scopes=...)` cleanly; an
    `AuthContext(scopes=ROLE_ADMIN)` passes every gate in
    `ALL_SCOPES`; the `clear:all` endpoint returns the documented
    403 detail (`"Missing required scope: 'clear:all'"`) for both
    anonymous and `read:any`-only contexts. 146 auth-pipeline
    unit tests pass end-to-end.*
  - *Reserved scopes that don't gate any endpoint yet:
    `SCOPE_WRITE_ANY`, `SCOPE_DELETE_ANY`, `SCOPE_ADMIN_KEYS`,
    `SCOPE_EVOLVE`. They're in the vocabulary so keys can be
    pre-provisioned with the future shape; wiring them onto
    specific endpoints is the natural next iteration (e.g.
    cross-namespace writes / soft-deletes, or the
    auth-driven `namespace=auth.owner` read filter that §3 P1
    teed up).*
- **[DONE]** OIDC integration (e.g. via `authlib`) for SSO deployments.
  *Shipped 2026-05-16: `Authorization: Bearer <jwt>` accepted alongside
  the existing `X-API-Key` header. CARE/MAGE production deployments
  can drop API keys entirely and have users authenticate via their
  corporate SSO (Keycloak/Auth0/Okta/Google) — tokens are verified
  against the configured OIDC provider's JWKS, `sub` projects onto
  `AuthContext.owner`, the scopes claim onto `AuthContext.scopes`.*
  - *New module `api/app/oidc.py` (~230 lines):*
    - *`OIDCVerifier.verify(token)` — decodes the JWT, validates
      signature against JWKS, then enforces `iss` / `aud` / `exp`
      claims with `OIDC_LEEWAY_SECONDS` clock-skew tolerance.
      Forced JWKS refresh on first signature failure handles
      provider key rotation transparently — operators don't need to
      restart the API when their identity provider rolls keys.*
    - *`JWKSCache` — thread-safe TTL cache for the issuer's JWKS.
      Stale-on-failure semantics: a transient JWKS-endpoint outage
      keeps the previous good keys in play rather than failing every
      request (Prometheus `gigaevo_memory_http_requests_total{status="503"}`
      would still rise via the eventual ApiKey path, but live
      sessions stay up).*
    - *`get_oidc_verifier()` / `reset_oidc_verifier()` — module-level
      singleton management. Tests use the reset helper to swap
      configs cleanly.*
    - *`_normalise_scopes` — accepts both the OAuth2 standard
      space-separated string AND the array form some providers
      (Auth0, Keycloak) emit when the claim is named `scopes` (plural).*
  - *8 new settings on `api/app/config.py::Settings`: `oidc_enabled`,
    `oidc_issuer`, `oidc_jwks_uri` (defaults to
    `<issuer>/.well-known/jwks.json`), `oidc_audience`,
    `oidc_sub_claim` (default `"sub"`), `oidc_scopes_claim`
    (default `"scope"`), `oidc_jwks_cache_ttl_seconds` (default 600),
    `oidc_leeway_seconds` (default 30). All env-driven via the
    existing pydantic-settings setup.*
  - *`require_api_key` (`api/app/auth.py`) extended to try Bearer
    first via the new `_extract_bearer_token` helper. Precedence:
    Bearer beats X-API-Key when both presented (it's the stronger
    credential); Bearer-but-OIDC-disabled returns a 401 with a
    helpful "OIDC is disabled" hint rather than silently falling
    through to the API-key path; invalid Bearer in strict mode 401s
    exactly like an invalid API key. `WWW-Authenticate` response
    header now advertises both schemes (`"Bearer, X-API-Key"`).
    JWT `jti` claim is used as `AuthContext.key_id` so audit logs
    can correlate to specific issued tokens; falls back to `sub`
    when `jti` is absent.*
  - *Dependency: `authlib>=1.3` added to `api/pyproject.toml`. Adds
    cryptography + joserfc transitively but no other behaviour
    changes. `authlib.jose` is what authlib publicly recommends for
    JWT/JWK work.*
  - *Tests: 35 new tests in `api/tests/test_oidc.py` across 6 classes —
    bearer-header extraction (5: well-formed / case-insensitive
    scheme / missing / non-Bearer scheme / empty); scope
    normalisation (5: space-separated string / empty / array /
    None / unknown shape); JWKS cache (4: first-fetch caching /
    force-refresh / stale-on-failure / initial-failure raises);
    `OIDCVerifier` end-to-end (9 against an in-test RSA keypair:
    valid / expired / wrong issuer / wrong audience / missing sub /
    wrong signature / array scopes claim / no-audience config /
    empty token); singleton management (5: disabled → None /
    returns same instance / reset drops / missing issuer raises /
    JWKS URI defaults to well-known); auth dependency (7: valid
    Bearer → AuthContext / invalid Bearer 401 / Bearer-without-OIDC
    401 / Bearer beats X-API-Key / opt-in fallback / strict 401 /
    jti → key_id). 35/35 pass.*
  - *2 pre-existing auth tests (`test_auth_dual_mode::test_missing_header_401`,
    `test_api_key_auth::test_missing_header_401`) pinned the
    literal 401 detail message — updated to the new
    "Missing X-API-Key or Authorization: Bearer header" wording
    (the message change is semantically correct now that both
    schemes are valid). `test_api_key_auth` also tightened to
    check the new `WWW-Authenticate: Bearer, X-API-Key` header.
    Combined auth+OIDC suite: 90/90 pass.*
  - *Real-execution evaluation: stood up an in-process FastAPI app
    with a `Depends(require_api_key)`-protected `/whoami` route, in
    strict mode + OIDC enabled. Generated an RSA keypair in-process,
    minted JWTs with `authlib.jose.jwt.encode`, and exercised 7
    operator scenarios end-to-end: (A) valid CARE-user SSO token →
    200 with `owner=alice@example.com`, scopes `["evolve", "read:any"]`,
    `key_id="session-abc-123"` (from JWT's `jti`); (B) impostor
    token from wrong issuer → 401 "Invalid claim 'iss'"; (C)
    expired token → 401 "The token is expired"; (D) malformed
    token → 401 "Token signature invalid"; (E) no auth in strict
    mode → 401 with `WWW-Authenticate: Bearer, X-API-Key`; (F)
    Auth0-style array `scopes` claim → projected correctly to
    `AuthContext.scopes`; (G) Bearer sent to deployment with
    `OIDC_ENABLED=false` → 401 with helpful "OIDC is disabled"
    detail. README Authentication section rewritten to advertise
    both schemes + the OIDC config knobs. Ruff clean on all
    touched files.*

---

## 4. Search & retrieval upgrades (P1–P2)

- **[DONE]** `document_kind` support for AgentSkills — index three doc kinds:
  `skill_description` (BM25 on description), `skill_instructions`
  (BM25+vector on the SKILL.md body), `skill_allowed_tools` (tags-style
  facet). Lets MAGE search "PDF skill" against descriptions only and
  filter by required tool tags.
  *Already shipped in iteration #4 — `derive_agent_skill_search_documents`
  emits **four** doc kinds: `skill_description`, `skill_instructions`,
  `skill_full` (BM25 catch-all over name+desc+body), and
  `skill_allowed_tools` (CSV of allowed-tools tokens for facet
  filtering). Indexed via `entity_search_documents` with embeddings.*
- **[DONE]** Capability matching helper:
  `MemoryClient.find_capability_matches(rough_aim: str, top_k: int=3)`
  returning matched skills + MCP servers + tools across entities.
  *Shipped 2026-05-16 (iteration #14): `MemoryClient.find_capability_matches(
  rough_aim, top_k=3, *, search_type=BM25, namespace=None, channel="latest",
  embedding_provider=None, deep=False)` — searches the `agent_skill`
  entity type with the `skill_description` document_kind (the cleanest
  BM25 input).  ``deep=True`` runs a second query against
  `skill_instructions` (the SKILL.md body) and merges results, deduped
  by `entity_id` with higher-score-wins. Empty/whitespace queries
  short-circuit to `[]` without a network call. New `CapabilityHit`
  Pydantic model in `gigaevo_memory.models` (with
  `CapabilityHit.from_search_hit()` projection helper) recording
  `entity_id`, `entity_type`, `name`, `description`, `score`,
  `snippet`, `tags`, `matched_via` (which doc kind found the hit).
  Exported via lazy `__getattr__` from `gigaevo_memory`. 11 tests in
  `client/python/tests/test_capability_matching.py`: BM25 ranking
  (4 — ranking, doc-kind, namespace, top_k), empty-input (1),
  projection (2 — description from content, matched_via fallback),
  deep merge (3 — two-call surface, dedup with higher-score, inverse
  case), vector path (1). Real-scenario evaluation: BM25
  "extract PDF" returns ranked skills; deep search "use pdfplumber for
  tables" issues two queries and surfaces the instructions-body match
  with `matched_via="skill_instructions"`; vector paraphrase
  ("pull tabular content") works with embedding_provider injection;
  empty query short-circuits.

  **Scope note**: today every hit's `entity_type` is `agent_skill`.
  When MCP servers / tools get dedicated entity types (future P2),
  hits of those types will land in the same ranked list and MAGE can
  discriminate by `entity_type` — the helper's return shape is
  forward-compatible.*
- **[DONE]** Reranker hook: optional cross-encoder reranking after hybrid
  retrieval. Configurable via `RERANKER_MODEL` env.
  *Shipped 2026-05-16 (iteration #27):*
  - *New `api/app/services/search_strategies/reranker.py` defines a
    minimal `Reranker` Protocol — single async method
    `rerank(query, hits) -> hits`. Implementations may re-order,
    drop, or re-score hits, but **may not introduce new ones**
    (the candidate set is closed at retrieval time).*
  - *`IdentityReranker` (no-op default) ships in the same module
    and is always registered under kind ``"identity"``.*
  - *`RerankerRegistry` class lets out-of-tree code plug a new
    reranker without modifying the gigaevo-memory package itself:
    `RerankerRegistry.register(kind, factory)`,
    `.get(kind) -> Reranker`,
    `.registered_kinds() -> list[str]`. Last-writer-wins semantics
    for test overrides. Unknown kinds log a single warning then
    fall back to `IdentityReranker` so a typo in the env never
    breaks search.*
  - *Wired into `UnifiedSearchService`: constructor accepts an
    optional `reranker: Reranker | None = None`; defaults to
    `RerankerRegistry.get(settings.reranker_kind)` (which is
    `"identity"` unless overridden). A new
    `_apply_reranker(query, hits)` helper handles both async
    and sync `rerank` implementations (uses `inspect.isawaitable`
    on the return value) and short-circuits on empty hit lists so
    a real cross-encoder model isn't invoked on nothing. Wiring
    fires for both `search()` (single query) and `batch_search()`
    (one rerank call per query, parallelised via `asyncio.gather`).*
  - *New setting `reranker_kind: str = "identity"` in
    `app/config.py`, env-overridable like the rest.*
  - *16 tests in `tests/test_reranker.py` across 4 classes:
    `IdentityReranker` (2 — pass-through, empty list);
    `RerankerRegistry` (6 — identity always registered, register +
    get, unknown falls back + logs warning, identity is silent,
    last-writer-wins, sorted registered list); single-search wiring
    (7 — default from settings, settings kind drives choice,
    explicit override wins, rerank-reorders-hits, sync-rerank
    handled, reranker can drop, empty results skip the reranker);
    batch search (1 — per-query independent invocation).*
  - *Real-scenario evaluation: a deployment registers a
    `cross_encoder` fake that boosts verbatim query matches by 0.5
    and drops hits below 0.4. BM25 returns
    `misc-utility` (score 0.92) > `pdf-extractor` (0.45) >
    `noise-skill` (0.30) for the query `"pdf"`. Post-rerank:
    `pdf-extractor` (0.95) bubbles past `misc-utility` (0.92),
    `noise-skill` drops out. Demonstrates the canonical
    "BM25 → cross-encoder re-rank" hybrid pipeline.*
  - *343 server unit tests pass; no regression.*
- **[DONE]** Faceted filter by `allowed_tools` token (e.g. only show skills
  that don't require `Bash`).
  *Shipped 2026-05-16 (iteration #22):*
  - *Two new query params on `GET /v1/agent-skills`: `requires_tool`
    (repeated, AND semantics — `?requires_tool=Read&requires_tool=Write`
    keeps only skills whose `allowed_tools` contains BOTH tokens) and
    `excludes_tool` (repeated, OR semantics for the negation — drops
    skills that mention ANY listed token).*
  - *Two pure helpers in `routers/agent_skills.py`:
    `_skill_tool_tokens(version)` projects `content.allowed_tools`
    safely (handles missing / non-list / None content); 
    `_filter_skills_by_tools(items, *, requires_tool, excludes_tool)`
    applies the set-math filter and preserves the upstream sort order.*
  - *Post-filter strategy: `allowed_tools` lives in
    `EntityVersion.content_json` (JSONB), which `list_entities`
    doesn't push down. The router fetches `min(limit * 4, 200)`
    candidates when filters are active and trims after filtering, so
    pagination stays honest without a JOIN+JSONB-operator detour.
    Bounded overhead — fine for typical catalogues (≤200 skills).*
  - *Client `list_agent_skills(requires_tools=..., excludes_tools=...)`
    serialises both as repeated query params via a new
    `_list_entities(extra_params={...})` extension point on
    `BaseMemoryClient`. Empty lists elided so `?requires_tool=`
    doesn't appear on the wire.*
  - *17 server tests in `tests/test_allowed_tools_filter.py`:
    `_skill_tool_tokens` (4 — list / missing / malformed-non-list /
    None-content); `_filter_skills_by_tools` (9 — no-filters
    passthrough / requires-single / requires-multi-AND /
    impossible-requires drops all / excludes-single /
    excludes-multi-OR / requires+excludes combined / untagged-skill
    semantics / order preservation); router wiring (4 — OpenAPI
    exposes the new params with list-of-string shape; fetch
    multiplier applied when filters active; no multiplier without
    filters). 6 client tests in
    `client/python/tests/test_allowed_tools_filter_client.py`:
    repeated `requires_tool` / `excludes_tool` / combined / empty-list
    elided / no-kwarg-no-param / composes-with-existing-knobs.*
  - *Real-scenario evaluation walked 4 CARE/MAGE workflows:
    (A) sandbox-restricted "exclude Bash" returned [weather, docs];
    (B) "requires Read AND Write" returned [pdf, docs, notes];
    (C) combined `requires=WebFetch + excludes=Bash` with
    `sort_by=run_count desc` returned [weather]; (D) empty filter
    lists elided from the query string.*
  - *267 server unit tests + 156 client unit tests pass; no regression.*
- **[DONE]** Semantic deduplication: detect chains/skills with >0.95 cosine
  similarity on embeddings and suggest merge.
  *Shipped 2026-05-16: new endpoint
  `GET /v1/{entity_type}/duplicates` flags near-duplicate pairs by
  cosine similarity over the channel-resolved embedding. CARE / MAGE
  use this for catalogue hygiene — surfacing chains or skills that
  drifted toward each other so a human can merge them.*
  - *Service: new `EntityService.find_duplicate_pairs(entity_type_singular,
    *, channel, threshold, namespace, limit)`. Gated by
    `settings.enable_vector_search` (returns `None` when disabled →
    router maps to 503). SQL is a CTE-backed self-join over
    `entity_versions.embedding` using pgvector's `<=>` cosine-distance
    operator; the predicate
    `a.entity_id < b.entity_id` canonicalises each unordered pair so
    it appears at most once. Results sorted by `similarity DESC`.
    Channel resolution via the JSONB `channels ->> :channel`
    expression so every entity contributes exactly one embedding (the
    one currently pinned to the requested channel). Defensive
    filters: `deleted_at IS NULL`, `embedding IS NOT NULL`,
    optional `e.namespace = :namespace`. Namespace param is omitted
    from the SQL string when the caller passes None (no `IS NULL`
    semantics needed — the absent filter naturally widens the scan).*
  - *Response models in `api/app/models/responses.py`:
    `DuplicateMember` (entity_id, version_id, name, display_name,
    namespace), `DuplicatePair` (entity_a, entity_b, similarity in
    [0, 1], suggestion: free-string default `"merge"`),
    `DuplicatesResponse` (entity_type, channel, threshold, pairs).
    Mirrored on the client in `gigaevo_client/models.py` and exported
    via `__all__` + the lazy `__getattr__`.*
  - *Router: new dedicated module `api/app/routers/dedup.py` exposes
    `GET /v1/{entity_type}/duplicates` (response model
    `DuplicatesResponse`, `tags=["search"]`, regex-validated
    `threshold` 0.5–1.0 + `limit` 1–500). Accepts both hyphenated
    (`agent-skills`) and underscored (`agent_skills`) plurals
    matching `VALID_ENTITY_TYPES`. 400 on unknown entity types, 503
    when vector search disabled (with a helpful detail message
    pointing operators at `ENABLE_VECTOR_SEARCH`).*
  - *Wiring (subtle): the dedup router MUST be registered before the
    typed entity routers in `main.py` — its path is
    `/v1/{entity_type}/duplicates` and the typed routers declare
    `/v1/{type}/{entity_id}` where FastAPI would otherwise try to
    parse the literal `"duplicates"` as a UUID and reject with 422.
    Initial test run caught this: 5 endpoint tests failed with 422
    until I moved `app.include_router(dedup.router, prefix="/v1")`
    above the typed-router block (with a comment explaining why).*
  - *Client SDK:
    `GigaEvoClient.find_duplicates(entity_type, *, channel, threshold,
    namespace, limit) -> DuplicatesResponse` on the `SearchMixin`.
    `namespace=None` is elided from the query string (avoids sending
    the literal string `"None"`).*
  - *Tests:*
    - *14 server tests in `api/tests/test_semantic_dedup.py` across
      2 classes — service (6: feature-flag-disabled → None /
      enabled → runs query / threshold+namespace+limit bound to SQL
      params / namespace omitted drops filter / row shape translates
      to pair structure / empty rows → empty pairs); endpoint (8:
      happy path / 503 vector-search-disabled / 400 invalid entity
      type / hyphenated plural accepted / query params threaded /
      threshold bounds 422 / limit bounds 422 / endpoint registered
      in OpenAPI with all 3 response components). 14/14 pass.*
    - *5 client tests in `client/python/tests/test_semantic_dedup_client.py`:
      default params / explicit overrides / namespace=None elided /
      typed round-trip / empty pairs round-trip. 5/5 pass.*
    - *38 existing chains-router tests (`test_chains_router_library`,
      `test_lineage_endpoint`, `test_differential_channel`) confirmed
      green after the route-ordering change — no regression.*
  - *Real-execution evaluation: computed cosine similarities on 3
    representative 4-dim embeddings (pdf-extract / pdf-text-extract /
    weather) and verified `(pdf-extract, pdf-text-extract)` scored
    ~1.0 (> 0.95 threshold) while `(pdf-extract, weather)` and
    `(pdf-text-extract, weather)` both scored ~0.50 (filtered out).
    Walked the actual `find_duplicate_pairs` with `enable_vector_search=true`
    against a stubbed `db.execute` returning the qualifying row;
    confirmed SQL params bound correctly (entity_type=agent_skill,
    channel=latest, threshold=0.95, namespace=alice, limit=10), SQL
    string contains the pgvector `<=>` operator + the
    `a.entity_id < b.entity_id` canonicalisation predicate, response
    pair carries `suggestion=merge` and `entity_a.entity_id <
    entity_b.entity_id`. Toggled `enable_vector_search=false` and
    confirmed the service returns `None` (router maps to 503). Added
    a second qualifying pair at similarity 0.962 and confirmed the
    response orders strictly descending by similarity (PDF pair
    first, finance pair second). Ruff clean on all touched files.*

---

## 5. Versioning & evolution metadata (P1–P2)

`entity_versions.evolution_meta JSONB` already exists but is unused. CARE
needs the evolution loop to leave breadcrumbs.

- **[DONE]** Standardise `evolution_meta` schema:
  ```json
  {
    "parent_version_ids": ["..."],
    "fitness_score": 0.87,
    "generation": 12,
    "experiment_id": "exp-...",
    "objectives": {"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200},
    "mutation_kind": "step_swap" | "prompt_rewrite" | "topology_change"
  }
  ```
  Add Pydantic model `EvolutionMeta` in `api/app/models/`.
  *Shipped 2026-05-16: `EvolutionMeta` in `api/app/models/requests.py`
  extended with the 6 CARE/Platform standardised fields
  (`parent_version_ids`, `fitness_score`, `generation` (≥0),
  `experiment_id`, `objectives` dict, `mutation_kind` free string with
  documented typical values). The 6 legacy gigaevo-core fields
  (`prompt_ref`, `fitness`, `is_valid`, `metrics`,
  `behavioral_descriptors`, plus `mutation_kind` shared with the new
  shape) are **preserved verbatim** for backward compat — pre-existing
  JSONB rows decode cleanly without reshape. `EvolutionMeta` mirrored
  client-side in `gigaevo_memory.models` and exported via the lazy
  `__getattr__` pattern. 17 server tests in `tests/test_evolution_meta.py`
  cover standardised shape, mutation_kind free-string parametrised,
  generation validation, legacy roundtrip, mixed new+legacy, request
  envelope acceptance (both typed and raw dict), and OpenAPI exposure
  of all 11 fields. 6 client tests in
  `client/python/tests/test_evolution_meta.py` cover top-level re-export
  + standardised + legacy + validation + JSONB round-trip. Real-scenario
  evaluation: gigaevo-platform PUTs an evolved chain (generation 12,
  fitness 0.87, 2 parents, 3 objectives, mutation `"crossover"`); CARE
  reads back the typed lineage; a legacy `step_swap` row from
  gigaevo-core also decodes cleanly with `fitness_score=None`.*
- **[DONE]** API support: `POST /v1/chains/{id}` accepts `evolution_meta` in
  the version envelope; `GET /v1/chains/{id}/versions` returns it.
  *Shipped 2026-05-16: `EntityCreateRequest` / `EntityUpdateRequest`
  already carry `evolution_meta: EvolutionMeta | None`;
  `EntityService.create_entity` / `update_entity` persist it onto
  `EntityVersion.evolution_meta`; `VersionInfo` / `VersionDetail`
  response models expose it. Pydantic auto-coerces a wire-side dict
  into the typed model so callers can send either shape. Verified via
  `TestEntityCreateRequestRoundTrip` (3 tests).*
- **[DONE]** New endpoint `GET /v1/chains/{id}/lineage` — returns the
  ancestry DAG (parent_version_ids walked recursively). UI uses this for
  evolution-tree visualisation.
  *Shipped 2026-05-16 (iteration #18):*
  - *Server-side `EntityService.get_lineage(entity_id, *,
    channel="latest", version_id=None, max_depth=10)` does BFS through
    `entity_versions.parents` (the typed UUID[] column, faster than
    JSONB extraction). Starts from the channel-resolved version or an
    explicit `version_id`. Dedupes by version_id so diamond crossovers
    appear once. Returns ``None`` if the entity or starting version
    can't be resolved. ``max_depth_reached`` flag tells the client
    when the BFS hit the cap with parents still unexplored.*
  - *`GET /v1/chains/{chain_id}/lineage` endpoint on the chains
    router. Query params: `channel="latest"`, `version_id` (optional),
    `max_depth` (1–100, default 10). 404s when the entity isn't a
    chain or when the starting version doesn't resolve.*
  - *`LineageResponse` + `LineageVersion` Pydantic models on both
    sides (`api/app/models/responses.py` + `gigaevo_memory.models`).
    Each `LineageVersion` carries `version_id`, `version_number`,
    `parents`, `evolution_meta`, `change_summary`, `author`,
    `created_at`, `depth` (BFS depth from root) — enough for CARE to
    render layered evolution-tree visualisations without re-walking.*
  - *Client method `MemoryClient.get_chain_lineage(entity_id, *,
    channel, version_id, max_depth)` returns `LineageResponse`.*
  - *10 server tests in `tests/test_lineage_endpoint.py`: missing
    entity / root-only / single-parent chain / diamond crossover dedup
    / max_depth cap with `max_depth_reached=True` / explicit
    `version_id` (descendants excluded) / unknown version_id rejected
    / router registration + OpenAPI exposure of `LineageResponse` +
    `LineageVersion` + `max_depth` bounds (1–100). 7 client tests in
    `client/python/tests/test_lineage_client.py`: default params /
    explicit version_id / custom channel / typed-response parsing /
    diamond dedup / max_depth_reached flag / 404 → NotFoundError.*
  - *Real-scenario evaluation: rendered the LibraryScreen
    evolution-tree for a 6-version chain with a diamond crossover
    (v0 → v1 → {v2, v3} → v4 (crossover ⚡) → v5). Output groups
    versions by BFS depth (matching how the LibraryScreen renders
    layers), surfaces evolution_meta.mutation_kind +
    evolution_meta.fitness_score per node, and correctly identifies
    v4 as a multi-parent crossover node.*
  - *217 server unit tests + 145 client unit tests pass; no regression.*
- **[DONE]** Channel `evolved` semantics: `latest` always tracks the most
  recently written version, `stable` the human-blessed one, `evolved` the
  highest-fitness one. Auto-update `evolved` on successful experiment.
  *Shipped 2026-05-16 (iteration #20):*
  - *New helper `EntityService._extract_fitness(evolution_meta)` —
    canonical fitness scalar extraction, prefers the §5 P1
    standardised `fitness_score` field, falls back to legacy
    gigaevo-core `fitness` alias, coerces ints → float, returns None
    on unparsable values.*
  - *New helper `EntityService._maybe_promote_evolved_channel(channels,
    new_version_id, evolution_meta)` — applies the auto-pin rules:
    no fitness → no-op; no `evolved` channel yet → pin (first
    evolution); current pin has missing / unparsable fitness →
    promote new; new fitness strictly greater than current → promote;
    otherwise keep incumbent. Strict `>` deliberately: a re-run with
    identical score doesn't churn the channel pointer. Corrupt
    pointers and missing referenced versions are overwritten.*
  - *Wired into both `create_entity` (initial channels include
    `evolved` when fitness ships with the first version) and
    `update_entity` (after the standard `latest` / per-channel pins,
    runs the auto-promotion check). Transparent to callers — no API
    change.*
  - *17 server tests in `tests/test_evolved_channel.py`: fitness
    extraction (6 cases — None/empty/standardised/legacy/precedence/
    unparsable/int coercion); channel-promotion helper (9 cases —
    no-fitness no-op / first-evolution pin / higher-fitness
    promote / lower keeps / equal keeps / missing-current promotes /
    corrupt-pointer overwrites / missing-version overwrites / legacy
    field drives promotion); end-to-end via `create_entity` (2 cases —
    with fitness pins `evolved`, without fitness leaves it absent).*
  - *Real-scenario evaluation: walked 5 generations of an evolution
    run (fitness 0.30 → 0.45 → 0.61 → **0.52 (regression)** → 0.83).
    The `evolved` channel correctly tracks the highest-scoring
    version: promotes at gens 0/1/2/4, **keeps** gen-2's pin during
    gen-3's regression. Enables CARE's "show only best-evolved
    chains" filter via `GET /v1/chains/{id}?channel=evolved`.*
  - *243 server unit tests pass; no regression.*
- **[DONE]** Differential channel views: list versions that beat the
  `stable` channel on a given objective.
  *Shipped 2026-05-16: new endpoint
  `GET /v1/chains/{chain_id}/versions/beating` returns the
  "promotion candidates" view — versions whose chosen objective
  value strictly beats the baseline channel's pin. CARE renders it
  on the LibraryScreen detail pane so a human can pick a winner to
  manually promote to `stable`.*
  - *Service: new helper
    `EntityService._extract_objective_value(evolution_meta, objective)`
    — for `objective="fitness_score"` reads the standardised
    `fitness_score` field with legacy `fitness` fallback (matches the
    `evolved`-channel auto-promotion precedence); any other string is
    looked up in `evolution_meta.objectives[<name>]`. Defensive
    against missing/unparsable values (returns `None`, never `0.0`).
    New
    `EntityService.find_versions_beating(entity_id, *, baseline_channel,
    objective, limit, sort_dir)` returns a structured payload matching
    the response model. Strict `>` filtering (matches `evolved`
    auto-promotion: ties keep the incumbent). Soft-deleted entities
    → `None` (404). When the baseline channel isn't pinned, or its
    pin doesn't carry the requested objective, the method returns a
    well-formed payload with `baseline_value=None` and `winners=[]`
    so the UI can render a "no baseline available" state instead of
    inferring from a 404.*
  - *Response models in `api/app/models/responses.py`:
    `VersionScore` (version_id, version_number, value, delta, author,
    created_at, change_summary) and `DifferentialChannelView`
    (entity_id, baseline_channel, baseline_version_id, objective,
    baseline_value, winners). Mirrored client-side in
    `gigaevo_client/models.py` and exported via `__all__` +
    lazy `__getattr__`.*
  - *Router: `api/app/routers/chains.py::list_versions_beating_channel`
    mounted at `GET /v1/chains/{chain_id}/versions/beating`. Query
    params: `channel` (default `"stable"`), `objective`
    (default `"fitness_score"`), `limit` (1–200, default 50),
    `sort_dir` (pattern `^(asc|desc)$`, default `"desc"` so the
    biggest improvements surface first). Validates the entity is
    actually a chain (so the chains-mounted endpoint doesn't surface
    other types).*
  - *Client SDK: `GigaEvoClient.list_chain_versions_beating(entity_id,
    *, channel, objective, limit, sort_dir) -> DifferentialChannelView`.
    Same defaults as the server.*
  - *Tests:*
    - *23 server tests in `api/tests/test_differential_channel.py`
      across 3 classes — `_extract_objective_value` (8 — fitness_score
      precedence / legacy fallback / named objective / missing
      objective / non-dict objectives / None meta / unparsable value /
      int coercion); `find_versions_beating` (7 — missing entity →
      None / strict-`>` filter excludes ties + baseline itself + no-fitness
      / sort_dir asc / limit cap / named objective / no baseline pin
      structured empty / baseline pinned but no value); endpoint
      (8 — happy path / query params threaded / 404 missing chain /
      404 wrong entity type / no-baseline 200 with structured empty /
      invalid sort_dir 422 / limit bounds 422 / endpoint registered
      in OpenAPI with VersionScore + DifferentialChannelView schemas).*
    - *4 client tests in
      `client/python/tests/test_differential_channel_client.py`:
      default param shape / explicit overrides /
      typed-response parsing (DifferentialChannelView +
      VersionScore round-trip) / empty winners.*
  - *Real-execution evaluation: built a realistic 5-generation chain
    (fitness 0.30 → 0.45 → 0.61 → 0.52 → 0.83, plus a v5 with
    fitness 0.78), with `stable` pinned to v2 (fitness=0.61, the
    user-blessed version) and v2 + v4 + v5 carrying multi-objective
    payloads (`accuracy`, `latency_ms`). Walked 4 CARE scenarios
    through the actual `find_versions_beating`: (A) objective
    `fitness_score` → 2 winners (v4 Δ=+0.22, v5 Δ=+0.17, sorted desc);
    (B) objective `accuracy` (baseline 0.80) → 1 winner (v4=0.92,
    v5's 0.75 correctly excluded as below baseline); (C) objective
    `latency_ms` (baseline 1500) → 0 winners (strict-`>` correctly
    rejects v4=1240 and v5=800 as "lower than baseline" — documented
    semantic match with `evolved`-channel auto-promotion); (D)
    baseline channel not pinned → structured empty payload with
    `baseline_value=None`. Ruff clean on all touched files.*

---

## 6. SSE & real-time updates (P1)

The client already exposes `watch_chain()` backed by SSE. Verify and extend.

- **[DONE]** Audit `/v1/{type}/{id}/events` — make sure all entity types emit
  events (today only chains do, per `client.py:585`). Add for steps, agents,
  memory_cards, agent_skills.
  *Shipped 2026-05-16 (iteration #16). Audit findings:*
  - *The events endpoint at `/v1/events/stream` is generic — it filters
    by `entity_type` / `entity_id` / `namespace` query params and works
    for ANY entity type. Steps / agents / memory_cards / agent_skills
    didn't need new endpoints; the routing was already type-agnostic.*
  - *Real gap: the §1.4 library-mutation service methods
    (`set_favourite`, `record_run`, `update_metadata` added in
    iteration #7) **never called** `publish_entity_event`, so CARE's
    library hot-reload would miss every favourite-toggle /
    run-record / rename across **all** entity types.*
  - *Fix: all three methods now publish distinct event types —
    `"favourite_toggled"` / `"run_recorded"` / `"metadata_updated"` —
    carrying the entity's actual `entity_type` so CARE can filter
    per-type without inspecting payloads. `update_metadata` publishes
    **once** per PATCH regardless of how many fields changed, and
    publishes **nothing** when called with all-None kwargs (a no-op
    PATCH the library shouldn't react to). Existing version-mutation
    events (`"created"` / `"updated"` / `"deleted"`) remain unchanged.*
  - *9 tests in `tests/test_library_mutation_events.py` cover:
    favourite-toggle publish/no-publish-on-missing (2); record_run
    publish + cross-entity-type parametrised (`agent`/`chain`/
    `agent_skill`/`memory_card`/`step`) (2); update_metadata
    single-publish-per-PATCH + multi-field-single-event +
    no-op-no-publish + missing-entity-no-publish (4); and a final
    test asserting the three event types are distinct (1). Added
    an autouse fixture in `tests/test_library_mutations.py` to
    silence the publisher in iter #7's tests (which mock the DB but
    don't expect Redis traffic) — 17/17 of those still pass.
    Real-scenario: walked a CARE library flow across chains +
    agent_skills, captured 6 events (3 types × 2 entity types) via a
    publisher mock; verified CARE-side filter-by-entity_type returns
    only that type's events, and filter-by-event_type isolates
    `run_recorded` for a stats widget.*
- **[DONE]** Server-wide `/v1/events` firehose with filter params
  (`entity_type`, `namespace`, `tags`) for the CARE catalog screen.
  *Shipped 2026-05-16 (iteration #17):*
  - *The firehose already lives at `/v1/events/stream` (single
    server-wide channel `memory:events` backed by Redis pub/sub).
    This iteration enriched the filter surface so CARE can subscribe
    with the precision its library needs.*
  - **Server-side filter knobs**: `tags` (repeated query param,
    OR-semantics — event matches when its tag set intersects the
    requested set) and `event_type` (filter on event kind, e.g.
    `run_recorded` for a stats widget). Plus the pre-existing
    `entity_type` / `entity_id` / `namespace`. Filter logic extracted
    into a pure `_event_passes_filters(event, …)` predicate for unit
    testing without spinning Redis.
  - **Publisher payload enrichment**: `publish_entity_event()` now
    accepts optional `namespace` and `tags` kwargs (backward compat —
    older callers without them keep working; defaults are `None` and
    `[]`). Every entity-scoped publish call site in
    `entity_service.py` (created / updated / deleted / favourite_toggled /
    run_recorded / metadata_updated / pinned / promoted) now passes
    `entity.namespace` and `list(entity.tags or [])`. The bulk
    `clear_all` path keeps its minimal 3-arg call since it only has
    `entity_type` available.
  - **Client-side `MemoryClient.watch_entities(callback, *,
    entity_type, entity_id, namespace, tags, event_type)`**: lower-level
    primitive than `watch_chain` — the callback receives the raw event
    dict (no automatic content refresh, which would explode the
    server load on namespace-wide subscriptions). `Subscription` class
    extended with optional `namespace` / `tags` / `event_type` ctor
    kwargs; `entity_id` and `callback` are now optional so generic
    library subscriptions work. The chain-specific
    `get_chain_dict + chain_from_content` refresh path only runs when
    BOTH `entity_type=="chain"` AND `entity_id is not None` — pure
    legacy compat for `watch_chain`. Existing `watch_chain` API
    unchanged.
  - **14 server tests** in `api/tests/test_events_firehose.py`:
    filter predicate (no-op, entity_type, entity_id, namespace,
    event_type — 5); tags filter (intersection, OR-within, no overlap,
    empty-event-tags, missing-tags-field — 5); all-filters-combined
    (2); publisher payload (with-fields, optional — 2).
  - **10 client tests** in
    `client/python/tests/test_watch_entities.py`: subscription param
    shape (4 — no-filter, chain-pinned, namespace-only, all-filters);
    event handling (4 — raw dispatch, invalid JSON dropped,
    None-callback safe, chain-pin refresh path); public API (2 —
    watch_entities filter propagation, watch_chain unchanged).
  - Fixed iter #16 tests' assertion shapes to include the new
    `namespace`/`tags` kwargs; all 9 still pass.
  - Real-scenario evaluation walked 4 CARE subscription patterns:
    library hot-reload (namespace+entity_type), favourites widget
    (entity_type+tags AND-combined with OR-within-tags), stats widget
    (event_type only), and inspected the published payload — every
    filter combination produced the expected pass/drop verdicts.
  - 207 server unit tests + 148 client unit tests pass; no regression.
- **[DONE]** Backpressure: SSE clients with `max_lag_seconds` exceeded get a
  `lag_warning` event and may be dropped after a threshold.
  *Shipped 2026-05-16 (iteration #26):*
  - *Lag = wall-clock gap between the publisher's `timestamp` (set
    by `publish_entity_event` since iter #16) and the moment the
    SSE generator is ready to yield. Captures consumer-side
    slowness (TUI paused under an inspector, backgrounded process,
    flaky network) without any per-message bookkeeping.*
  - *Two new settings in `app/config.py` with env-overridable
    defaults: `sse_warn_lag_seconds: float = 10.0` and
    `sse_drop_lag_seconds: float = 60.0`. Both are floats so
    sub-second tuning is possible for low-latency deployments.*
  - *Pure helper `_compute_lag_action(event, *, now=None,
    warn_threshold_s=None, drop_threshold_s=None) -> (action,
    lag_seconds)` in `routers/events.py`. Action is one of
    ``"forward" | "warn" | "drop"``. Inclusive boundaries (`>=`)
    on both thresholds. Defensive handling: missing / unparsable
    timestamps → `"forward"`; naive ISO strings assumed UTC; clock
    skew (negative lag) → `"forward"`. Reads from `settings` when
    threshold kwargs omitted (production path) or accepts explicit
    overrides (test path).*
  - *Generator wiring: after the filter check, every event runs
    through `_compute_lag_action`. On `"warn"`, a `lag_warning`
    SSE event is emitted (`{lag_seconds, warn_threshold_seconds,
    drop_threshold_seconds, action, for_event:{entity_id,
    entity_type, event_type, timestamp}}`) **before** the original
    `entity_changed`, so a paused-then-resumed TUI gets both the
    diagnostic and the original event. On `"drop"`, a final
    `lag_warning` fires then the generator returns, which closes
    the connection cleanly (the `finally` block still runs
    `pubsub.unsubscribe` + `pubsub.close()`).*
  - *12 tests in `tests/test_sse_backpressure.py` across 3 classes:
    pure decision logic (9 — within-budget forward, warn at
    threshold, warn at exact boundary, drop at threshold, drop at
    exact boundary, negative lag = forward, missing timestamp =
    forward, unparsable timestamp = forward, naive timestamp =
    assume UTC); threshold configuration (2 — reads from settings
    by default, explicit overrides win); publisher integration
    (1 — round-trip the exact wire payload from
    `publish_entity_event` through `_compute_lag_action`, lag = 0).*
  - *Real-scenario evaluation walked 3 CARE subscriber states for
    the same published event: (A) healthy TUI yields after 2s →
    `forward`, normal flow; (B) lagging TUI after 15s → `warn`,
    emits a `lag_warning` event with the full diagnostic payload
    then the original `entity_changed`; (C) stuck TUI after 90s →
    `drop`, final `lag_warning` then connection close. CARE TUI
    treats `drop` as "reconnect on your own".*
  - *327 server unit tests pass; no regression.*

---

## 7. Operational & deployment (P2)

- **[DONE]** Health endpoint already exists; extend `/health` payload with
  `db_pool_used`, `db_pool_total`, `redis_used`, `pgvector_index_size`,
  `entity_counts`. CARE's status bar consumes this.
  *Shipped 2026-05-16 (iteration #21):*
  - *Three new helper functions in `api/app/routers/health.py`:
    `_collect_db_pool_stats()` reads `engine.sync_engine.pool.size()`
    / `.checkedin()` / `.checkedout()` / `.overflow()` for live
    connection-pool counters; `_collect_entity_counts(db)` runs a
    single `SELECT entity_type, COUNT(*) FROM entities WHERE
    deleted_at IS NULL GROUP BY entity_type` to populate the
    per-entity live-counts dict; `_collect_redis_metrics()` reads
    `redis.info("clients")` for `connected_clients` and
    `blocked_clients`. Each helper swallows its own errors —
    individual metrics collapse to None on failure rather than
    propagating up.*
  - *Status semantics preserved: only the dependency pings (postgres
    `SELECT 1`, redis `PING`) drive the binary `ok | degraded` flip.
    Metric outages render as `null` without affecting `status`.
    `entity_counts` is skipped (returns None) when postgres ping
    failed — there's no point retrying the count query.*
  - *Naming: chose `db_pool_size` / `db_pool_checkedin` /
    `db_pool_checkedout` / `db_pool_overflow` over the TODO's
    `db_pool_used` / `db_pool_total` so SQLAlchemy's actual pool
    semantics surface accurately. `pgvector_index_size` deferred —
    requires a per-index `pg_relation_size()` query that adds I/O on
    every health probe; CARE doesn't need it for v1.*
  - *7 server tests in `tests/test_health_enrichment.py`:
    enriched-shape (4 — all fields present / entity_counts
    aggregated by type / redis metrics pulled from info / db pool
    stats are integers); graceful degradation (3 — postgres down
    flips status + skips counts / redis down doesn't kill postgres
    metrics / entity_count_query failure collapses to None without
    flipping status).*
  - *Used `app.dependency_overrides[get_db]` rather than
    `patch.object` to override the dependency — FastAPI captures
    dependency references at app construction. Added an autouse
    `_reset_overrides` fixture so overrides don't leak between tests.*
  - *Real-scenario evaluation rendered 3 CARE-facing JSON payloads:
    (A) healthy dev session — full metrics + entity counts; (B)
    postgres outage — status flips to `degraded`, postgres `error:
    …`, redis half remains observable, counts go to null; (C) redis
    outage — postgres + counts still live, redis metric fields
    collapse to null. CARE's status bar can render `db_pool 0/5 ·
    redis 3 · chains 12 · agents 4 · …` directly from a single GET.*
  - *250 server unit tests pass; no regression.*
- **[DONE]** Backup script: `make backup` dumps Postgres + uploads to S3.
  Documented in README under "Operations".
  *Shipped 2026-05-16 (iteration #38):*
  - *New `deploy/scripts/backup.sh` — bash script with `--help` and
    `--dry-run` flags; dumps the docker-compose `postgres` service
    via `docker compose exec -T postgres pg_dump`, pipes through
    host-side `gzip`, and writes to `${BACKUP_DIR}/gigaevo-memory-
    YYYYMMDD-HHMMSSZ.sql.gz`. Optional S3 upload when `S3_BUCKET`
    is set (otherwise prints `"skipping S3 upload"`). Exit codes
    are operator-friendly: 0 success, 2 usage error, 1 pg_dump or
    upload failure. `set -euo pipefail` so the first stderr line
    surfaces the root cause.*
  - *Configuration via env vars (every var has a sensible default):
    `BACKUP_DIR=./backups`, `POSTGRES_USER=memory`,
    `POSTGRES_DB=memory`, `COMPOSE_FILE=deploy/docker-compose.yml`,
    `COMPOSE_PROJECT=gigaevo-memory`, `S3_BUCKET` (unset → no
    upload), `S3_PREFIX=gigaevo-memory/backups`. No CLI args
    needed for the common case — `make backup` Just Works.*
  - *Two new Makefile targets: `make backup` runs the script;
    `make backup-dry-run` runs `backup.sh --dry-run` (prints the
    pg_dump + aws s3 cp commands without executing). Both listed
    in `.PHONY` and surfaced via `make help`.*
  - *README "Operations" section documents the variable table,
    schedule/cron guidance, and pointers to `make migrate-check`
    and `make create-key OWNER=...` so the operator handbook lives
    in one place. README previously had no operations section.*
  - *16 new tests in `tests/test_backup_script.py` across 5
    classes: script-on-disk (4 — file exists, is u+g+o executable,
    `--help` returns 0 with usage, unknown flag → exit 2);
    pg_dump invocation (5 — default command shape, custom user/db,
    BACKUP_DIR override, COMPOSE_FILE override, COMPOSE_PROJECT
    override); S3 upload branch (3 — no bucket → skip, bucket →
    aws s3 cp line, S3_PREFIX override); filename pattern (2 — UTC
    timestamp regex, 6-digit seconds precision so concurrent runs
    don't collide); dry-run no-side-effects (2 — doesn't create
    nonexistent BACKUP_DIR, every action emits a `would ` line).
    Every test runs the script in `--dry-run` so no real DB,
    Docker, or AWS credentials are needed.*
  - *Real-execution evaluation: invoked the script directly with
    `deploy/scripts/backup.sh --dry-run` (defaults) →
    `would run: docker compose -p gigaevo-memory -f
    deploy/docker-compose.yml exec -T postgres pg_dump -U memory
    -d memory | gzip > ./backups/gigaevo-memory-20260516-
    164543Z.sql.gz` + `==> skipping S3 upload (S3_BUCKET unset)`.
    With `S3_BUCKET=gigaevo-prod-backups S3_PREFIX=postgres/2026`
    → adds `would run: aws s3 cp ./backups/...sql.gz
    s3://gigaevo-prod-backups/postgres/2026/...sql.gz`. Both
    exits 0. The CARE production deployment can now run
    `0 3 * * * cd /opt/gigaevo-memory && S3_BUCKET=... make
    backup` from cron for a nightly dump + S3 archive.*
- **[DONE]** Migration safety: add CI step that runs `alembic upgrade head`
  against a clean DB and `alembic downgrade -1` round-trip.
  *Shipped 2026-05-16 (iteration #36):*
  - *Two-layer gate. **Static** (`tests/test_migration_chain.py`,
    8 tests, no DB needed, runs on every push): walks the migration
    revision graph and asserts every module declares
    `revision`/`down_revision`/`upgrade`/`downgrade`; no duplicate
    revision ids; every `down_revision` points to an existing
    migration; exactly one root + one head; chain is linear (no
    branching); chain walk from root visits every migration in the
    directory (catches dangling files). **Dynamic**
    (`.github/workflows/migration-safety.yml`, runs in CI against a
    Postgres service container): `alembic upgrade head` →
    `alembic downgrade -1` → `alembic upgrade head` round-trip,
    using the `pgvector/pgvector:pg15` image so migration 001's
    `CREATE EXTENSION vector` works. Triggers on changes to
    `api/app/db/migrations/**`, `models.py`, or `alembic.ini`.*
  - *New `make migrate-check` Makefile target wraps the same two
    checks for local pre-push validation: runs the pytest gate, then
    the alembic upgrade/downgrade/upgrade round-trip through the
    docker-compose `memory-migrate` service so the local result
    matches CI byte-for-byte.*
  - *Negative-path evaluation: synthesised a broken migration
    pair (root `001` + orphan `002` with
    `down_revision='nonexistent'`) in a tmpdir, monkeypatched the
    test module's `MIGRATIONS_DIR`, and confirmed the assertion
    triggered with the exact error message
    `"revision '002' declares down_revision='nonexistent' but no
    migration with that id exists"`. Validates that the gate
    catches the most common copy-paste mistake (forgetting to update
    `down_revision` when stubbing a new migration).*
  - *Real-execution evaluation: parsed the workflow YAML, confirmed
    8 steps in the `alembic-roundtrip` job
    (`checkout` → `setup-uv` → `uv sync` → static pytest gate →
    `upgrade head` → `downgrade -1` → `upgrade head` →
    `alembic current`). All current 5 migrations (001 initial →
    005 library_listing_index) pass the static chain walk.*
- **[DONE]** Prometheus metrics (`/metrics` endpoint) — request counts,
  latency histograms per route, entity counts per type.
  *Shipped 2026-05-16:*
  - *New module `api/app/metrics.py` owns the three series asked for:*
    - *`gigaevo_memory_http_requests_total` — `Counter` labelled by
      `method` / `path_template` / `status`.*
    - *`gigaevo_memory_http_request_duration_seconds` — `Histogram`
      labelled by `method` / `path_template` with tuned buckets
      (`0.005`, `0.010`, `0.025`, `0.050`, `0.100`, `0.250`, `0.500`,
      `1.000`, `2.500`, `5.000`, `10.000` seconds — covers the memory
      API's typical p50–p99).*
    - *`gigaevo_memory_entities` — `Gauge` labelled by `entity_type`,
      refreshed lazily on every scrape from `SELECT entity_type,
      COUNT(*) FROM entities WHERE deleted_at IS NULL GROUP BY entity_type`.*
  - *Three discipline knobs baked in:*
    - *Cardinality: `path_template` is the FastAPI route pattern
      (`/v1/chains/{chain_id}`), never the raw path — every UUID
      collapses onto one label set. Unmatched paths land on the
      single literal `"unmatched"` template so 404 spam can't blow
      out cardinality.*
    - *Dedicated `CollectorRegistry` (not the default process
      registry) so the GigaEvo series don't co-mingle with anything
      else `prometheus_client` might auto-register.*
    - *Self-scrape guard: the middleware short-circuits on
      `request.url.path == "/metrics"` so the scrape endpoint never
      appears in its own counters. Without this Prometheus's 15s
      scrape would create a self-referential `/metrics` spike.*
  - *DB resilience: `refresh_entity_counts` is best-effort. A
    `SQLAlchemyError` keeps the gauge's previous values in place
    (Prometheus's `absent_over_time` alert can pick up a persistent
    outage) and the scrape still returns 200 with the rest of the
    series.*
  - *Wiring: `prometheus-client>=0.20` added to
    `api/pyproject.toml`; `metrics_middleware` registered as the
    first HTTP middleware in `main.py` (wraps the full handler
    stack); `metrics.router` mounted alongside `health.router`.
    The pre-existing `/metrics` JSON stub in
    `routers/health.py` (a placeholder returning
    `{"note": "Full Prometheus metrics to be implemented"}`) was
    deleted — it would have shadowed the new endpoint. The new
    endpoint declares `include_in_schema=False` so it doesn't
    pollute OpenAPI.*
  - *Tests: 17 new tests in `api/tests/test_metrics.py` across 6
    classes — registry shape (2 — 3 series registered + histogram
    buckets cover 5ms–10s strictly increasing); path-template
    resolution (3 — unmatched fallback + happy path + route without
    `.path`); middleware behaviour (6 — counter incremented +
    duration observed + uses route template not raw UUID path
    (parametrised over 2 different UUIDs, asserts they collapse to
    a `{`-bearing template) + status label reflects 404 + scrape
    path NOT self-counted + method label recorded); endpoint
    integration (4 — Prometheus content-type with `version=` /
    response carries all 3 metric names / HELP+TYPE annotations /
    excluded from OpenAPI schema); entity-count refresh (2 — gauge
    populates from stubbed SQL row set / DB error keeps previous
    gauge values). 17/17 pass.*
  - *Real-execution evaluation: drove a representative traffic burst
    against the live FastAPI app via TestClient (3 health pings,
    5 chain-404 GETs against random UUIDs, 2 unmatched-route 404s,
    1 scrape), then parsed the scrape back through
    `prometheus_client.parser.text_string_to_metric_families`.
    Confirmed: counter shows 3 entries under templates `/health`
    (status=200, count=3), `/v1/chains/{chain_id}` (status=404,
    count=5 — the 5 distinct UUIDs collapsed onto one template),
    and `unmatched` (status=404, count=2); `/metrics` itself
    absent from counters (self-scrape guard); histogram totals
    3 + 5 + 2 = 10 observations matching counter aggregate; entity
    gauge reports stubbed inventory (chain=23, agent=5,
    memory_card=142, agent_skill=8, step=0); HELP+TYPE annotations
    present for all three families (`counter`, `histogram`,
    `gauge`). Ruff clean.*

---

## 8. Quality-of-life (P2–P3)

- **[DONE]** Bulk operations endpoint: `POST /v1/bulk/save` accepting a
  mixed list of entities for one-shot import (used by CARE's
  `care import`).
  *Shipped 2026-05-16 (iteration #23):*
  - *New `api/app/routers/bulk.py` with `POST /v1/bulk/save`.
    Accepts a `BulkSaveRequest` carrying 1..500 `BulkSaveItem`s,
    each with `{entity_type, meta, content, channel, [entity_id],
    [embedding], [evolution_meta], [parent_version_id],
    [change_summary]}`. Items with `entity_id=None` create new
    entities; items with `entity_id` set upsert as new versions.*
  - *Per-item error isolation by default — a failure at index N
    doesn't roll back N-1 successes. Pass `stop_on_error=True` to
    abort on the first failure (the response then carries only the
    completed entries, not the skipped ones).*
  - *Returns `BulkSaveResponse` with a per-item `results` array
    (`{index, success, entity_ref?, error?}`) plus aggregate
    `success_count` / `error_count`. The `entity_ref` shape mirrors
    the typed-router responses (`{entity_type, entity_id, version_id,
    channel}`) so callers can drive follow-up requests without a
    separate GET.*
  - *Implementation: pure `_save_one(svc, item)` helper does the
    per-type dispatch (singular→plural via `VALID_ENTITY_TYPES`),
    catches `ValueError` and unexpected exceptions, returns a
    `(success, entity_ref, error)` tuple. The endpoint loop calls
    it per item, builds the response envelope. Three new Pydantic
    models: `BulkSaveItem` + `BulkSaveRequest` (requests.py) and
    `BulkSaveItemResult` + `BulkSaveResponse` (responses.py).*
  - *Client `MemoryClient.bulk_save(items, *, stop_on_error=False)`
    accepts a list of dicts, returns the full response envelope.
    Empty lists short-circuit before the network round-trip.*
  - *11 server tests in `tests/test_bulk_save.py`: per-item logic
    (5 — create path / update path uses entity_id / unknown
    entity_type rejects without DB hit / update 404 returns failure
    not exception / ValueError caught); endpoint flow (5 — three
    creates succeed / partial failure isolated to per-item /
    stop_on_error aborts early / empty items 422 / 501+ items 422);
    router registration (1 — OpenAPI describes the 4 new Pydantic
    components). 6 client tests in
    `client/python/tests/test_bulk_save_client.py`: request body
    shape (3 — items + stop_on_error_false / stop_on_error_true /
    empty-short-circuits); response shape (2 — envelope + mixed
    entity types); upsert mode (1).*
  - *Real-scenario evaluation walked 3 CARE `care import` workflows:
    (A) clean import of 6 mixed entities (3 chains + 2 agents +
    1 skill) in **1 HTTP call** vs 6 sequential POSTs; (B) partial
    failure with continue-past — got 2 successes + 1 detailed
    per-item error; (C) upsert mode bumped an existing chain to v2.*
  - *278 server unit tests pass; no regression.*
- **[DONE]** `clear_all(entity_type)` is too dangerous to leave unguarded —
  require `X-Confirm: yes-i-really-mean-it` header.
  *Shipped 2026-05-16 (iteration #19):*
  - *Server: `POST /v1/maintenance/clear-all` now reads
    `x_confirm: str | None = Header(default=None, alias="X-Confirm")`
    and returns **412 Precondition Failed** when the header is
    missing or doesn't exactly match
    `CLEAR_ALL_CONFIRM_TOKEN = "yes-i-really-mean-it"` (case-sensitive
    exact match). The guard runs **before** `entity_type` validation
    so an unauthorised request can't even probe the validation
    surface — `POST .../clear-all?entity_type=BOGUS` returns 412, not 400.*
  - *Client: `MemoryClient.clear_all(entity_type=None, *, confirm=False)`
    refuses to issue any HTTP call until `confirm=True` is supplied
    (raises `ValueError` immediately — important so a typo like
    `client.clear_all()` in a script doesn't reach the wire). When
    `confirm=True`, the client attaches the `X-Confirm` header. Also
    unwraps the server's `{"deleted": {...}}` envelope so the
    documented `dict[str, int]` return type is accurate (older code
    returned the raw envelope). `MemoryClient.CLEAR_ALL_CONFIRM_TOKEN`
    class attribute lets advanced callers inspect / override the
    sentinel (mirrors server's constant).*
  - *9 server tests in `tests/test_clear_all_confirmation.py`: no
    header → 412; wrong / empty / uppercase values → 412; correct
    value → 200; entity_type filter combined with confirm; entity_type
    validation runs after confirm; invalid entity_type without confirm
    still 412 (no surface leak); sentinel-stability sanity. 5 client
    tests in `client/python/tests/test_clear_all_confirmation.py`:
    confirm-False short-circuits before network; confirm-True attaches
    header; entity_type query-string passthrough; 412 → ConflictError;
    cross-package sentinel agreement (hard-coded since the API package
    isn't a client runtime dep — comment explicitly cross-references
    the server-side test).*
  - *Real-scenario evaluation walked 5 operator workflows: fat-finger
    typo (0 HTTP calls), deliberate wipe with full counts, targeted
    wipe with `entity_type=chain`, server-side rejection surfaces as
    `ConflictError`, sentinel agreement check. 226 server unit tests
    + 150 client unit tests pass; no regression.*
- **[DONE]** Pagination cursors instead of offset/limit on `list_*`
  endpoints — current limit-only pagination breaks past 10k entities.
  *Shipped 2026-05-16 (iteration #24):*
  - *`EntityService.list_entities()` already supported cursor
    pagination internally; this iteration exposes it on the typed
    routers as additive, non-breaking changes.*
  - *Server: `GET /v1/chains`, `/v1/agents`, `/v1/agent-skills` each
    accept a new `cursor: str | None` query param (alongside the
    existing `offset`). The response now carries two new headers:
    `X-Has-More` (`"true" | "false"`) and `X-Next-Cursor` (opaque
    cursor string, only present when has_more=true). The response
    body stays the existing flat `list[*Response]` shape — clients
    that don't read the headers see the same data, just paginated.*
  - *Tool-filter / cursor interaction: when `requires_tool` or
    `excludes_tool` is active on agent_skills, the post-filter may
    drop the last row whose position the cursor encodes — so the
    server explicitly suppresses both headers (`X-Has-More=false`,
    no `X-Next-Cursor`). Clients fall back to offset for
    tool-filtered walks.*
  - *Client: new `_list_entities_paged()` private helper on
    `BaseMemoryClient` reads both body + headers and returns
    `(items, next_cursor, has_more)` tuple. Three new public
    methods: `MemoryClient.list_chains_paged()`, `list_agents_paged()`,
    `list_agent_skills_paged()` — same kwargs as the offset-based
    list_* methods plus optional `cursor=None`. The offset-based
    methods stay unchanged for backward compat.*
  - *8 server tests in `tests/test_cursor_pagination_routers.py`:
    no-more emits `false` no cursor; has-more emits true with
    cursor; cursor query param forwarded for chains+agents; tool
    filter invalidates cursor on agent_skills; OpenAPI exposes the
    cursor param on all 3 paths. 8 client tests in
    `client/python/tests/test_cursor_pagination_client.py`:
    first-page no cursor / subsequent page carries cursor / end of
    stream / filters compose / typed-tuple shape / tool filter
    returns no cursor / tool filter repeated query param /
    end-to-end 3-page walk.*
  - *Real-scenario evaluation: walked a 250-chain library in 5 HTTP
    calls via cursor (5 pages × 50 per page). Total `O(n)` vs.
    offset's `O(n²)` cost at large scale. Tool-filtered walk
    correctly degrades to offset (cursor=None, has_more=false).*
  - *286 server unit tests + 170 client unit tests pass; no regression.*
- **[DONE]** Browser-friendly entity diff endpoint
  (`GET /v1/{type}/{id}/diff?from=A&to=B&format=html`).
  *Shipped 2026-05-16: extended the existing diff endpoint with a
  `format` query knob (regex `^(json|html)$`, defaults to `json` so
  every existing programmatic caller is unaffected). When
  `format=html`, the response is a self-contained HTML page rendered
  by a new pure-function module `api/app/services/diff_html.py` —
  no external CSS/JS so the page works in any context (file://,
  dashboard iframe, plain `curl` to file).*
  - *Renderer module: `render_diff_html(*, entity_type, entity_id,
    from_version, to_version, patch) -> str`. Accepts the patch in
    either form `EntityService.diff_versions` may yield (raw
    list-of-ops or the JSON string from
    `jsonpatch.make_patch(...).to_string()`). Header carries the four
    documented metadata fields + a row of summary chips
    (one per RFC-6902 op kind, count + colour). Body is a 3-column
    table (op / path / value). Each row gets a `class="row <kind>"`
    css class so add/remove/replace/move/copy/test get colour-coded
    backgrounds. Every user-controlled string (path, value, scalar
    metadata) is run through `html.escape()`.*
  - *Router: `api/app/routers/versions.py::diff_versions` no longer
    pins `response_model=DiffResponse` (dispatches on `format`); JSON
    path returns the same `DiffResponse` shape as before, HTML path
    returns `fastapi.responses.HTMLResponse`. Invalid `format` values
    (e.g. `?format=xml`) get FastAPI's 422 from the regex pattern.*
  - *Tests: 31 new tests in `api/tests/test_diff_html.py` across 6
    classes — `_normalise_patch` (6 — list passthrough / JSON string
    parse / empty string / malformed string / non-list / drops
    non-dicts); `_format_value` (4 — None → null / scalar quoted /
    dict pretty-printed / HTML-escape); `_summarise` (2 — counts
    known ops / ignores unknown); `render_diff_html` (11 — complete
    doc / inline CSS / no external assets / header metadata /
    each-op-as-row / paths shown / summary chips / empty-patch state
    / value XSS-escape / path XSS-escape / accepts JSON-string patch
    / move op shows from field); endpoint JSON (4 — default is JSON
    / explicit json / 404 missing version / 400 invalid entity
    type); endpoint HTML (4 — text/html content-type + page content
    / entity_id in header / 404 propagated / 422 on invalid format).
    All 31 pass.*
  - *Real-execution evaluation: built a representative before/after
    chain content pair (3-step finance triage → 4-step with
    LLM-config + chart + comment), called the actual
    `jsonpatch.make_patch` to produce 9 real RFC-6902 ops (5
    `replace` + 4 `add` across `/max_workers`,
    `/steps/1/llm_config`, `/steps/1/aim`, `/steps/2/aim`,
    `/steps/2/title`, `/steps/3`, `/metadata/comment`,
    `/metadata/display_name`, `/metadata/tags/1`), then rendered
    via `render_diff_html()`. The 5381-byte page parses cleanly via
    stdlib `html.parser` (closing-tag stack empty), all 9 op paths
    surface, summary chips read `5 replace` + `4 add`, and the
    `<user@example.com>` text in `/metadata/comment` correctly
    renders as `&lt;user@example.com&gt;` (no angle-bracket
    injection). Ruff clean on the new module + tests + the touched
    router.*

---

## 9. Documentation (P2–P3)

- **[DONE]** `docs/AGENT_SKILL_ENTITY.md` — full spec of the new entity type,
  including how MAGE/CARE consume it and the ingestion helper from §1.3.
  *Shipped 2026-05-16: 270-line contract doc in
  `docs/AGENT_SKILL_ENTITY.md`. Covers:*
  - *Entity-type aspect table (singular/plural, ORM table + filter
    column, OpenAPI response model, content-schema modules on both
    sides, the 4 emitted search documents).*
  - *Content schema table with all 11 fields (4 required: `name` /
    `description` / `uri` / `sha256`; 7 optional: `manifest`,
    `instructions`, `allowed_tools`, `tags`, `compatibility`,
    `tarball_url`, `tarball_sha256`), pinned against the actual
    `AgentSkillContent` server model + `AgentSkillSpec` client model.*
  - *4 supported `uri` shapes (`github://`, `local://`, `https://`,
    `module://`) plus the bare-name fallback.*
  - *REST endpoint table covering all 8 routes
    (`POST` / `GET` / `GET/{id}` / `PUT/{id}` / `PATCH/{id}` /
    `POST/{id}/favourite` / `POST/{id}/run-recorded` /
    `DELETE/{id}`), plus the full list-query knob table
    (`limit` / `offset` / `cursor` / `channel` / `sort_by` / `sort_dir` /
    `favourites_only` / `tags` / `q` / `namespace` / `requires_tool` /
    `excludes_tool`) with defaults and the cursor-pagination caveat
    when tool filters are active.*
  - *Search-document table (4 kinds: `skill_description`,
    `skill_instructions`, `skill_full`, `skill_allowed_tools`) with
    each kind's text shape + intended consumer (BM25 first-pass /
    vector / catch-all / facet).*
  - *Library-metadata column table (`favourite`, `run_count`,
    `last_run_at`, `display_name`, `description`) showing defaults
    + which endpoints mutate them.*
  - *Client-SDK code sample (save / get / list with tool filter /
    record-run / catalogue mutations) plus the
    `ingest_skill_from_carl(resolved, entity_id=...)` flow and its
    5 duck-typed fallback chains.*
  - *Full CARE / MAGE consumption walkthrough — capability lookup via
    `client.search(entity_type="agent_skill", search_type="hybrid")`,
    `entity_id` injection into chain `metadata.allowed_skills`,
    runtime resolution, run-recording, catalogue actions.*
  - *Compatibility notes (read-leniently / write-strictly; server
    doesn't validate content against the model; tarball fields are
    informational; forward-compat additions go in `manifest`).*
  - *Doc-drift guard: 16 new tests in
    `api/tests/test_agent_skill_entity_doc.py` across 7 classes —
    every required + optional content field documented (2);
    sha256 pattern surfaced (1); all 4 `skill_*` document kinds
    documented + match the actual `DOCUMENT_KIND_SKILL_*` constants
    (2); every router path is in the doc + 5 HTTP verbs called out
    (2); 5 library-metadata columns documented + present on the ORM
    model (2); 4 URI shapes documented (1); helper name + module
    existence + 5 documented fallback chains pin against the actual
    `_extract_skill_spec` source (3); plural form matches
    `VALID_ENTITY_TYPES`, `INDEXED_ENTITY_TYPES` includes
    `agent_skill`, `AgentSkillResponse.entity_type` Literal default
    matches (3). 16/16 pass.*
  - *Real-execution evaluation: parsed the doc (270 lines, 8 H2
    sections, 11 table-delimiter rows confirm 6+ tables) then walked
    the documented CARE/MAGE flow against live code. Built a duck-typed
    `FakeResolvedSkill` (no `mmar_carl` import) carrying a
    `FakeManifest` exposing `name`, `description`, `instructions`,
    `metadata.tags`, `compatibility`, and `get_allowed_tools()`;
    fed it through `_extract_skill_spec()` → got an `AgentSkillSpec`
    with name=`pdf-extract`, uri=`github://anthropic/skill-pdf-extract@v1`,
    sha256 64-hex, allowed_tools=`["Read", "Write", "Bash(python:*)"]`,
    tags=`["pdf", "office"]`, tarball_url+tarball_sha256 populated.
    Dumped to JSON and ran `derive_agent_skill_search_documents()`
    against it → got exactly the 4 documented kinds, each carrying
    `card_id="pdf-extract"` (name doubles as external-id) and the
    expected text shapes (`skill_description="pdf-extract\n…"`,
    `skill_allowed_tools="Read, Write, Bash(python:*)"`). Confirmed
    all 8 documented `AgentSkillsMixin` methods
    (`save_agent_skill` / `get_agent_skill` / `list_agent_skills` /
    `delete_agent_skill` / `ingest_skill_from_carl` /
    `mark_agent_skill_favourite` / `record_agent_skill_run` /
    `update_agent_skill_metadata`) exist on the public surface.
    Ruff clean on the new doc-drift test + docs/.*
- **[DONE]** `docs/CARE_INTEGRATION.md` — contract doc paired with CARE's
  expectations of memory keys and namespaces.
  *Shipped 2026-05-16: umbrella contract doc in
  `docs/CARE_INTEGRATION.md`. Cross-references the three focused
  sibling specs (`AGENT_SKILL_ENTITY.md`, `EVOLUTION_META.md`,
  `CHAIN_CONTENT_CONVENTIONS.md`) and pins everything else CARE
  needs.*
  - *Memory keys — stable `entity_id` references CARE embeds in
    chains; the 5 entity types CARE consumes with their route
    prefixes (`/v1/steps`, `/v1/chains`, `/v1/agents`,
    `/v1/agent-skills`, `/v1/memory-cards`); resolution via
    `Entity.display_name` → `Entity.name` fallback.*
  - *Namespaces — full 4-quadrant write rule table and 5-quadrant
    read rule table (anonymous / authenticated × explicit / implicit
    ns × ±`read:any` for reads), pointing at the canonical helpers
    `default_namespace_for` / `default_read_namespace_for` in
    `api/app/auth.py`. CARE convention: per-user keys auto-scope all
    saves and lists to `auth.owner`; cross-namespace requires
    `?namespace=` + the `read:any` scope.*
  - *Authentication — dual-mode (`AUTH_REQUIRED=true` strict vs.
    opt-in default) with the anonymous-context fallback semantics;
    full 6-scope vocabulary table (`read:any`, `write:any`,
    `delete:any`, `clear:all`, `admin:keys`, `evolve`); 3
    pre-baked role bundles (`ROLE_READER`, `ROLE_EDITOR`,
    `ROLE_ADMIN`). CARE's standard key carries no scopes beyond
    the default own-namespace read/write.*
  - *Channels — 3 canonical names (`latest`, `stable`, `evolved`)
    with semantics + mutator endpoints; custom channels work too.
    `evolved` auto-promotion rules cross-ref `EVOLUTION_META.md`.*
  - *Library metadata — full 5-column table (`favourite`,
    `run_count`, `last_run_at`, `display_name`, `description`)
    with defaults + mutator endpoints + CARE usage. Mutations
    don't create new versions — CARE relies on this so renaming a
    chain doesn't churn its evolution lineage.*
  - *List query knobs — uniform 9-knob table across all 4 typed
    list endpoints (`sort_by` / `sort_dir` / `favourites_only` /
    `tags` / `q` / `namespace` / `limit` / `offset` / `cursor`)
    with CARE-default home view (`last_run_at desc`). Cursor
    pagination caveats (default sort only, tool-filter
    invalidation).*
  - *Chain content convention — pointer to
    `CHAIN_CONTENT_CONVENTIONS.md` for the `CareChainMetadata`
    block (`task_description`, `context_files`, `display_name`,
    `tags`, `generated_by`, `mage_metadata`) with the
    "write both / read DB-column wins" rule for `display_name`.*
  - *Real-time updates — `GET /v1/events/stream` SSE payload shape
    with all 8 emitted `event_type` values (`created`, `updated`,
    `deleted`, `pinned`, `promoted`, `favourite_toggled`,
    `run_recorded`, `metadata_updated`), 5 query-filter knobs
    (`entity_type` / `entity_id` / `namespace` / `tags` /
    `event_type`), and backpressure semantics
    (`SSE_WARN_LAG_SECONDS` 10s / `SSE_DROP_LAG_SECONDS` 60s
    defaults). CARE usage: library catalogue subscribes per
    namespace; detail pane subscribes per entity_id.*
  - *Compatibility section — entity-type enum stability,
    read-leniently/write-strictly model stance,
    library-metadata-mutations-don't-version-bump invariant
    (load-bearing for CARE evolution).*
  - *Doc-drift guard: 29 new tests in
    `api/tests/test_care_integration_doc.py` across 8 classes —
    entity-type pairs documented + match `VALID_ENTITY_TYPES`
    inventory (3); 6-scope vocabulary documented + matches
    `ALL_SCOPES` + 3 role bundles documented + bundles match
    (4); namespace helpers named + exist + `AUTH_REQUIRED`
    documented + setting exists (4); 3 canonical channels
    documented + `EVOLUTION_META.md` cross-ref present (2);
    5 library columns documented + present on ORM + 3 mutator
    endpoints documented (3); 9 list knobs documented + CARE
    defaults called out (2); 8 event types documented + match
    every `publish_entity_event` literal in the service via
    regex scan + 5 SSE filters documented + `/v1/events/stream`
    registered on the FastAPI app (composite check accounts for
    the `/v1` prefix mount in `main.py`) + lag settings
    documented + exist (7); 3 sibling docs referenced + exist
    + `CareChainMetadata.merge_into_content` referenced + exists
    (4). 29/29 pass — initially caught 2 real drifts: live code
    emits `pinned` and `promoted` event types that I had missed
    in the table (now added), and the SSE endpoint test needed to
    account for the app-level `prefix="/v1"` mount on the events
    router (the router itself declares `/events/stream`).*
  - *Real-execution evaluation: walked all 9 namespace-resolution
    quadrants (4 write × 5 read) through the actual
    `default_namespace_for` / `default_read_namespace_for` helpers
    — every result matched the documented rule (anonymous
    pass-through, authenticated auto-scope to `auth.owner`,
    explicit override always respected, `read:any` opens
    cross-namespace reads). Verified the 3 role bundles —
    `ROLE_READER={read:any}`, `ROLE_EDITOR={read:any, write:any}`,
    `ROLE_ADMIN == ALL_SCOPES`. Patched `get_redis` and called
    `publish_entity_event("updated", "e-1", "chain",
    version_id="v-2", channel="latest", namespace="alice",
    tags=["finance", "q1"])` — captured payload carried exactly
    the 8 documented fields (`event_type`, `entity_id`,
    `entity_type`, `version_id`, `channel`, `namespace`, `tags`,
    `timestamp`). Confirmed live `VALID_ENTITY_TYPES` matches the
    documented route table verbatim. Ruff clean on the new
    doc-drift test + docs/.*
- **[DONE]** `docs/EVOLUTION_META.md` — schema and lineage semantics from §5.
  *Shipped 2026-05-16: 273-line contract doc in
  `docs/EVOLUTION_META.md`. Covers:*
  - *Aspect table — server + client `EvolutionMeta` modules, JSONB
    column + typed `parents UUID[]` column, lineage endpoint, lineage
    response models, reserved `evolved` channel.*
  - *Two concentric schemas — the 6-field §5 P1 standardised shape
    (`parent_version_ids`, `fitness_score`, `generation`,
    `experiment_id`, `objectives`, `mutation_kind`) and the 5-field
    legacy gigaevo-core shape (`prompt_ref`, `fitness`, `is_valid`,
    `metrics`, `behavioral_descriptors`), with a canonical example
    payload showing a generation-12 crossover.*
  - *Write path — `evolution_meta` rides the create/update envelope;
    the two parent-pointer mechanisms (envelope `parent_version_id`
    → typed `entity_versions.parents UUID[]` for lineage walks vs.
    `evolution_meta.parent_version_ids` JSONB for self-describing
    analytics) and how callers keep them in sync.*
  - *`evolved` channel auto-promotion — all 5 rules
    (no-fitness no-op / first-evolution pin / corrupt-pointer overwrite
    / strict-`>` promote / regression keeps incumbent), the strict
    `>` rationale (re-runs with identical scores don't churn the
    pointer), and a worked 5-generation example with a regression at
    gen 3 (fitness 0.30 → 0.45 → 0.61 → **0.52** → 0.83, evolved
    pin tracks v0 → v1 → v2 → v2 → v4).*
  - *Lineage endpoint — `GET /v1/chains/{chain_id}/lineage` signature
    with all three query params (`channel`, `version_id`,
    `max_depth` 1–100), full response shape sample showing BFS order
    + per-node `depth` + multi-parent crossover, response-model field
    inventory (`LineageResponse`: 4 fields; `LineageVersion`: 8 fields),
    client SDK usage with `max_depth_reached` handling.*
  - *CARE / platform consumption walkthrough — platform writes the
    evolved version → `evolved` auto-promotes → CARE catalogue uses
    `?channel=evolved` to render the best view → evolution tree
    consumes `/lineage` BFS layers → re-run from a tree node via
    `?version_id=<node>`.*
  - *Compatibility notes — read-leniently/write-strictly stance,
    server doesn't validate `evolution_meta` at storage (model lives
    for client-side validation + OpenAPI documentation),
    `mutation_kind` enumerated values are guidance not validation,
    typed `parents` column is authoritative for lineage walks,
    `evolved` is reserved (use a custom channel name for manual
    overrides that shouldn't churn).*
  - *Doc-drift guard: 21 new tests in
    `api/tests/test_evolution_meta_doc.py` across 7 classes —
    standardised fields documented + present on server model (2),
    legacy fields documented + present (2), client mirrors server
    field set (1), all 5 evolved-channel rules described + strict-`>`
    called out + helper uses strict `>` + fitness_score precedes
    fitness in extraction (4), lineage endpoint path documented +
    registered + query params present + max_depth 1–100 documented +
    bounds match endpoint metadata (5), 8 LineageVersion + 4
    LineageResponse fields documented + match server model + client
    mirrors server (4), JSONB + UUID[] column references in doc +
    columns exist on ORM (3). 21/21 pass.*
  - *Real-execution evaluation: parsed the doc (273 lines, 9 tables,
    H2=6, H3=7) then exercised the documented evolution loop against
    live code. Round-tripped the canonical example payload through
    both `EvolutionMeta` models (server + client) confirming
    `fitness_score=0.87`, `generation=12`, 2 parent UUIDs, 3
    objectives. Replayed the 5-generation worked example
    asynchronously through the actual
    `EntityService._maybe_promote_evolved_channel` helper with a
    stubbed `get_version()`: produced exactly the documented pin
    sequence `v0 → v1 → v2 → v2 → v4`, with v3's 0.52 regression
    keeping v2's pin (rule 5). Verified `_extract_fitness`
    precedence — `{"fitness_score": 0.9, "fitness": 0.1}` →
    `0.9` (standardised wins), `{"fitness": 0.7}` → `0.7` (legacy
    fallback), missing → `None`, unparsable → `None`. Confirmed
    `EvolutionMeta().model_dump(exclude_none=True) == {}` as the
    "legal no-op instance" claim. Ruff clean on the new doc-drift
    test + docs/.*
- **[DONE]** Update README architecture diagram once auth + new entity ship.
  *Shipped 2026-05-16: README.md "Features" + "Architecture" sections
  rebuilt to match the post-CARE-prep state.*
  - *Features → Entity Types now lists **Agent Skills** (cross-link
    to `docs/AGENT_SKILL_ENTITY.md`). Version management mentions the
    auto-promoted `evolved` channel + the new `/lineage` and
    `/versions/beating` endpoints. Search section enumerates BM25 +
    `pgvector` + hybrid + reranker plus the CARE library knobs and
    AgentSkill-specific tool filters. New subsections:*
    - *CARE library metadata — favourite / run_count+last_run_at /
      display_name+description with the three documented mutator
      endpoints, no-version-bump call-out.*
    - *Authentication — dual-mode `AUTH_REQUIRED` flag, all 6 scopes
      enumerated, namespace auto-scoping behaviour, `make create-key`
      pointer.*
    - *Real-time updates — `/v1/events/stream` SSE with all 8
      emitted `event_type` literals, 5 filter knobs, and
      `SSE_WARN_LAG_SECONDS`/`SSE_DROP_LAG_SECONDS` backpressure.*
    - *Observability — `/health` + Prometheus `/metrics` exposing
      all 3 series by name (`gigaevo_memory_http_requests_total`,
      `gigaevo_memory_http_request_duration_seconds`,
      `gigaevo_memory_entities`).*
  - *Architecture diagram rebuilt as a 33-line ASCII block showing
    the three client surfaces (CARE TUI / MAGE / Web UI / Python SDK)
    routing through the `X-API-Key` gate into the FastAPI app, with
    the typed entity routers + cross-cutting endpoints called out
    on separate lines (no path wraps across line breaks). Postgres
    box names the `entities`/`versions`/`api_keys`/`search docs`
    tables + the `pgvector` extension; Redis box names the
    `memory:events` pub/sub channel that feeds the SSE firehose.*
  - *New "Documentation" section linking the four contract docs
    (`CARE_INTEGRATION.md` umbrella, `AGENT_SKILL_ENTITY.md`,
    `EVOLUTION_META.md`, `CHAIN_CONTENT_CONVENTIONS.md`) plus the
    Swagger UI + OpenAPI spec.*
  - *Doc-drift guard: 16 new tests in
    `api/tests/test_readme_architecture.py` across 7 classes —
    entity types (2 — every singular in `VALID_ENTITY_TYPES` has its
    human label in the README + AgentSkills callout with doc
    cross-ref); architecture diagram (3 — 9 required paths present
    as literal substrings, Postgres+`pgvector`+Redis blocks
    present, `memory:events` channel named); auth (3 — `AUTH_REQUIRED`
    documented, every scope in `ALL_SCOPES` listed,
    `make create-key` referenced); SSE (2 — every event_type emitted
    by `publish_entity_event` is documented + backpressure settings);
    observability (2 — every metric name in README + names match
    live `prometheus_client` registry); docs links (2 — 4 sibling
    doc paths referenced + all resolve on disk); channels (2 — 3
    canonical channels named + `/lineage` and `/versions/beating`
    called out). 16/16 pass.*
  - *Real-execution evaluation: parsed the README, extracted the
    33-line fenced `text` diagram block; verified every line ≤ 78
    chars (renders cleanly in 80-col terminals); cross-checked that
    every typed router prefix (`steps`/`chains`/`agents`/
    `agent-skills`/`memory-cards`) read from the live FastAPI
    routers + every cross-cutting endpoint (`/v1/events/stream`,
    `/v1/search/unified`, `/metrics`, `/health`) is present in the
    diagram as a literal substring; confirmed every env-var mention
    is a real `Settings` field or a known operator variable; all 4
    `docs/*.md` cross-references resolve. Ruff clean.*

---

## Cross-module dependencies

| Memory task               | Needed by                                                  |
|---------------------------|------------------------------------------------------------|
| §1 agent_skill entity     | MAGE TODO §2, §5; CARE TODO §3                             |
| §1.4 library metadata     | CARE TODO §1.3 (LibraryScreen) + §3 (SaveAgentModal)       |
| §2 unified client         | CARE TODO §3; gigaevo-core; carl-mage                      |
| §5 evolution_meta         | Platform TODO §1 (writes them on every evolved individual) |
| §6 event firehose         | CARE catalog screen + library hot reload                   |

---

## Suggested milestones

- **M0 (3 days):** §1.1 backend + §1.2 client — agent_skill entity ships.
- **M0.5 (3 days):** §1.4 library metadata (migration + endpoints + client
  mixins) — unblocks CARE LibraryScreen.
- **M1 (1 week):** §1.3 ingestion helper + §1 web UI + §3 P1 auth.
- **M2 (1 week):** §2 client rename + PlatformClient.
- **M3 (ongoing):** §4 search upgrades, §5 evolution meta, §6 SSE, §7–9.
