# CARE ↔ GigaEvo Memory integration

This is the umbrella contract document for CARE's expectations of
GigaEvo Memory. It cross-references the focused specs for individual
subsystems and pins the operational details (namespaces, memory keys,
auth, channels, events) that aren't covered elsewhere.

## Related docs

| Doc | Covers |
| --- | --- |
| [AGENT_SKILL_ENTITY.md](AGENT_SKILL_ENTITY.md) | `agent_skill` content schema, endpoints, search documents, ingestion helper. |
| [EVOLUTION_META.md](EVOLUTION_META.md) | `evolution_meta` shape, `evolved` channel auto-promotion, lineage endpoint. |
| [CHAIN_CONTENT_CONVENTIONS.md](CHAIN_CONTENT_CONVENTIONS.md) | `CareChainMetadata` block inside `chain.content_json["metadata"]`. |

Everything that follows is the CARE-specific contract surface that
sits **on top** of those subsystems.

## Memory keys

CARE references everything in Memory by stable `entity_id` (UUID). The
canonical wire-side flow:

1. CARE writes an entity via `POST /v1/{type}` and stores the returned
   `entity_id` plus the `version_id` of its first version.
2. Subsequent CARE state (`LibraryScreen` rows, the
   `outer_context.allowed_skills` reference list on a chain, the
   `parent_version_id` field on a re-evolution payload) carries the
   stable `entity_id` — never the human-readable `name`.
3. The CARE UI resolves `entity_id` → display via
   `Entity.display_name` (mutable, indexed) with a fallback to the
   immutable `Entity.name`.

The five entity types CARE consumes — and the route prefix for each:

| Entity type | Singular | Route prefix |
| --- | --- | --- |
| Step | `step` | `/v1/steps` |
| Chain | `chain` | `/v1/chains` |
| Agent | `agent` | `/v1/agents` |
| Agent skill | `agent_skill` | `/v1/agent-skills` |
| Memory card | `memory_card` | `/v1/memory-cards` |

The plural/singular mapping is canonicalised in
`api/app/services/entity_service.py::VALID_ENTITY_TYPES`.

## Namespaces

A namespace is a logical isolation boundary — typically one per CARE
user. The server applies it as both a **storage tag** on each entity
row and an automatic **filter** on reads / writes.

### Resolution rules

`api/app/auth.py::default_namespace_for` and
`default_read_namespace_for` implement the canonical resolution:

**Writes** (`POST` / `PUT` / `PATCH`):

* Anonymous caller → pass through whatever `meta.namespace` the
  request body carried (including `None`).
* Authenticated caller with explicit `meta.namespace` → respected.
* Authenticated caller with `meta.namespace = None` → defaults to
  `auth.owner`. **This is the standard CARE flow** — clients don't
  set namespace explicitly; the server auto-scopes.

**Reads** (`GET /v1/{type}` listing endpoints):

* Anonymous caller → pass through whatever `?namespace=` was sent
  (or no filter when omitted).
* Authenticated caller with explicit `?namespace=X` → respected.
* Authenticated caller without `?namespace` **and with the
  `read:any` scope** → returns `None` (sees every namespace).
* Authenticated caller without `?namespace` and without `read:any`
  → defaults to `auth.owner` (mirrors the writes-side auto-scoping).

### CARE convention

CARE's API key carries `owner=<care-user>` and the default scope set
(no `read:any`). All saves auto-scope to that owner; all lists return
just that owner's entities. To see a shared workspace, CARE either
issues a key with `read:any` for the operator account, or sends
`?namespace=<shared>` explicitly.

## Authentication

### Dual-mode

The deployment runs in one of two modes (controlled by
`AUTH_REQUIRED`):

* **Strict mode** (production): missing / invalid `X-API-Key` → 401.
* **Opt-in mode** (dev/CI, default): missing header → anonymous
  context (`owner="anonymous"`, empty scope set, `is_anonymous=True`).
  Invalid keys still 401.

CARE production builds talk to a strict-mode deployment with an
operator-provisioned API key per user.

### Scopes

| Scope | Meaning |
| --- | --- |
| `read:any` | Read across namespaces (default is own-namespace). |
| `write:any` | Write to namespaces other than `auth.owner`. |
| `delete:any` | Soft-delete entities outside the owner's namespace. |
| `clear:all` | Destructive bulk maintenance (`/maintenance/clear-all`). |
| `admin:keys` | Manage API keys for other principals. |
| `evolve` | Promote / pin / mutate the `evolved` channel. (Reserved.) |

Routes call `auth.require_scope(SCOPE_X)` after the base
authentication check; anonymous contexts always 403 there. CARE's
standard per-user key carries **no scopes** beyond the default
own-namespace read/write — sufficient for the full library workflow.

### Roles (convenience bundles)

`api/app/auth.py` exports three pre-baked role sets:

* `ROLE_READER` = `{read:any}`
* `ROLE_EDITOR` = `{read:any, write:any}`
* `ROLE_ADMIN` = every scope

CARE doesn't pin to these — they're operator tools for
`make create-key OWNER=... SCOPES=...`.

## Channels

Channels are pointers from `entities.channels` (JSONB) to a specific
`version_id`. CARE relies on three canonical names:

| Channel | Semantics | Mutated by |
| --- | --- | --- |
| `latest` | Always tracks the most recently written version. | Every successful write. |
| `stable` | Human-blessed version. Pinned manually. | `POST /v1/chains/{id}/pin`, `POST /v1/chains/{id}/promote`. |
| `evolved` | Highest-fitness version. **Auto-pinned**. | Every write that carries `evolution_meta.fitness_score`. |

`evolved` semantics are documented in
[EVOLUTION_META.md](EVOLUTION_META.md#the-evolved-channel). CARE reads
the catalogue's best-evolved view via
`GET /v1/chains/{id}?channel=evolved`.

Custom channel names work too — CARE may pin a per-user
`my-pinned-favourite` channel without disturbing the reserved names.

## Library metadata

CARE's `LibraryScreen` renders the user's entities as a
sortable/filterable table. The denormalised columns powering that view
were added in Alembic migration 003:

| Column | Default | Mutated by | CARE usage |
| --- | --- | --- | --- |
| `favourite` | `FALSE` | `POST /favourite`, `PATCH` | Star pinning. |
| `run_count` | `0` | `POST /run-recorded` | Sort key "most used". |
| `last_run_at` | `NULL` | `POST /run-recorded` | Default sort key "recently used". |
| `display_name` | `name[:200]` on creation | `PATCH` | The pretty name the catalogue renders. |
| `description` | `when_to_use` on creation | `PATCH` | Tooltip / detail pane. |

These are entity-level (mutating them does **not** create a new
version). CARE flows that hit them:

* **Save Agent modal** — sets `display_name`, `description`, `tags`
  via `PATCH /v1/agents/{id}`.
* **Star toggle** — `POST /v1/{type}/{id}/favourite`.
* **Chain finish hook** — `POST /v1/{type}/{id}/run-recorded` bumps
  `run_count` + `last_run_at`. Idempotency hook: optional
  `run_id` body field deduplicates double-recordings via an in-memory
  LRU.

### List query knobs

All four typed list endpoints (`/v1/agents`, `/v1/chains`,
`/v1/agent-skills`, `/v1/memory-cards`) expose the same library knobs:

| Param | Default | Notes |
| --- | --- | --- |
| `sort_by` | `last_run_at` | One of `created_at` \| `last_run_at` \| `run_count` \| `display_name`. |
| `sort_dir` | `desc` | `asc` \| `desc`. |
| `favourites_only` | `false` | Restrict to `favourite=TRUE`. |
| `tags` | — | AND-filter — every listed tag must appear in the entity's `tags` array. |
| `q` | — | Case-insensitive substring across `display_name` / `name` / `description`. |
| `namespace` | auto-scoped (see above) | Explicit override; `read:any` required for cross-namespace. |
| `limit` | `50` (max `200`) | Page size. |
| `offset` / `cursor` | — | Offset-style or keyset pagination. `cursor` is only valid with the default sort. |

CARE's default home view is `sort_by=last_run_at, sort_dir=desc` with
no other filters — i.e. "my recently-used stuff first".

`/v1/agent-skills` adds two extra knobs (`requires_tool`,
`excludes_tool`) for capability-aware filtering. See
[AGENT_SKILL_ENTITY.md](AGENT_SKILL_ENTITY.md#list-query-knobs).

### Pagination

* **Cursor** (`?cursor=...`) — keyset pagination, stable past 10k
  entities. Server returns `X-Next-Cursor` + `X-Has-More` headers.
  Only valid with the default sort (`created_at asc`). When the
  current request uses a non-default sort or a tool filter that
  invalidates the cursor's row position, the server omits
  `X-Next-Cursor` and the client must fall back to `offset`.
* **Offset** (`?offset=...`) — always works, slower at scale.

## Chain content convention

When CARE saves a chain, the `metadata` block inside `content_json`
follows the convention documented in
[CHAIN_CONTENT_CONVENTIONS.md](CHAIN_CONTENT_CONVENTIONS.md). Key
points:

* The block lives at `content["metadata"]`. Other clients may add
  their own keys alongside — `CareChainMetadata.merge_into_content()`
  preserves them.
* CARE writes `display_name` in **both** places: the entity column
  (mutable, indexed) and the content `metadata.display_name` (travels
  with the chain on export / evolution). The DB column is
  authoritative on read.
* `context_files` lets CARE re-run a chain with the same inputs.
  Each entry carries `path`, `sha256` (required, 64 hex), `size_bytes`,
  optional `mime_type`.
* `generated_by` + `mage_metadata` record provenance ("generated by
  MAGE", "generated by user").

## Real-time updates

CARE subscribes to entity changes via Server-Sent Events on
`GET /v1/events/stream`. Payloads are emitted as
`event: entity_changed` lines whose `data:` is the JSON event.

### Event payload

```json
{
  "event_type": "updated",
  "entity_id": "...",
  "entity_type": "chain",
  "version_id": "...",
  "channel": "latest",
  "namespace": "alice",
  "tags": ["finance", "q1"],
  "timestamp": "2026-05-16T11:42:00+00:00"
}
```

### Emitted event_type values

| `event_type` | When |
| --- | --- |
| `created` | New entity (first version written). |
| `updated` | New version appended to existing entity. |
| `deleted` | Entity soft-deleted. |
| `pinned` | A channel was pinned to a specific version via `POST /v1/{type}/{id}/pin`. |
| `promoted` | A channel was promoted (one channel's pointer copied to another) via `POST /v1/{type}/{id}/promote`. |
| `favourite_toggled` | `POST /favourite` flipped the flag. |
| `run_recorded` | `POST /run-recorded` bumped counters. |
| `metadata_updated` | `PATCH` mutated `display_name` / `description` / `tags` / `favourite`. |

### Filters

`/v1/events/stream` accepts (all optional, AND-combined; `tags` is OR
within itself):

* `?entity_type=` — exact match.
* `?entity_id=` — exact match (single-entity subscription).
* `?namespace=` — exact match (library-wide subscription).
* `?tags=pdf&tags=q1` — repeated query param; matches when the event's
  tag set intersects.
* `?event_type=run_recorded` — filter on event kind.

### Backpressure

A laggy subscriber gets a `lag_warning` event injected when the
publisher-to-forwarder gap exceeds `SSE_WARN_LAG_SECONDS` (default
10s). Beyond `SSE_DROP_LAG_SECONDS` (default 60s) the connection is
closed. CARE's `LibraryScreen` reconnects on disconnect after a short
back-off.

### CARE consumption

* **Library catalogue** subscribes to
  `?namespace=<auth.owner>` and refreshes affected rows on
  `created` / `updated` / `metadata_updated` / `deleted`.
* **Single-entity detail pane** subscribes to
  `?entity_id=<eid>` while the user has the entity open, so
  external mutations (e.g. an MAGE-driven evolved version landing)
  surface immediately.

## Cross-references

The CARE-specific subsystems on top of Memory have their own focused
docs:

* `agent_skill` entity, MAGE capability lookup, ingestion helper →
  [AGENT_SKILL_ENTITY.md](AGENT_SKILL_ENTITY.md).
* `evolution_meta` schema, `evolved`-channel auto-promotion, lineage
  endpoint, evolution-tree rendering →
  [EVOLUTION_META.md](EVOLUTION_META.md).
* `CareChainMetadata` block (`task_description`, `context_files`,
  `display_name`, `tags`, `generated_by`, `mage_metadata`) →
  [CHAIN_CONTENT_CONVENTIONS.md](CHAIN_CONTENT_CONVENTIONS.md).

## Compatibility & versioning

* The `entity_type` enum is governed by
  `VALID_ENTITY_TYPES`. Adding a new type means updating that mapping
  AND adding a typed router; `entities.entity_type VARCHAR(20)`
  accommodates names up to 20 chars.
* `EvolutionMeta` and `AgentSkillContent` are **read-leniently /
  write-strictly**: clients tolerate missing optional fields but
  emit only the documented shape.
* Library-metadata mutations (`PATCH`, `/favourite`, `/run-recorded`)
  are entity-level and do NOT create new versions. CARE depends on
  this so renaming a chain doesn't churn its evolution lineage.
* Namespacing defaults are stable — new auth scopes may be added but
  existing scopes will keep their semantics.
