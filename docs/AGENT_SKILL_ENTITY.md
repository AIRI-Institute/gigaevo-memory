# AgentSkill entity

A first-class GigaEvo Memory entity type that persists a portable
[AgentSkills](https://agentskills.io)-style folder (a SKILL.md plus its
bundled scripts/assets) so generated chains can reference the skill by
stable `entity_id` and MAGE's capability lookup can search across
SKILL.md descriptions and bodies.

| Aspect | Value |
| --- | --- |
| Singular name | `agent_skill` |
| Plural / route prefix | `/v1/agent-skills` |
| ORM table | `entities` (`entity_type='agent_skill'`) |
| OpenAPI response | `AgentSkillResponse(EntityResponse)` with `entity_type: Literal["agent_skill"]` |
| Content schema (server) | `api/app/models/requests.py::AgentSkillContent` |
| Content schema (client) | `client/python/src/gigaevo_client/models.py::AgentSkillSpec` |
| Search documents | `skill_description`, `skill_instructions`, `skill_full`, `skill_allowed_tools` |

The `entities` table is unchanged — no DDL was needed when this type
was introduced. The 11-char value fits the existing
`entity_type VARCHAR(20)` column. The allowlist is enforced at the
service layer
(`api/app/services/entity_service.py::VALID_ENTITY_TYPES`).

## Content schema

GigaEvo Memory stores `content` as opaque JSON. The CARE/MAGE contract
for `agent_skill` content is `AgentSkillContent`. Both the server-side
model and the client-side `AgentSkillSpec` mirror it field-for-field.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | `str` (1–200 chars) | ✓ | Matches SKILL.md frontmatter `name`. |
| `description` | `str` | ✓ | Human-readable summary of what the skill does. |
| `uri` | `str` | ✓ | Stable identifier the resolver dispatches on. See URI shapes below. |
| `sha256` | `str` (64 hex) | ✓ | SHA-256 hex digest of the SKILL.md file. Pattern `^[0-9a-fA-F]{64}$` (upper- or lower-case accepted). |
| `manifest` | `dict[str, Any]` |   | Parsed SKILL.md frontmatter (YAML). |
| `instructions` | `str` |   | The full SKILL.md body (everything after the frontmatter). |
| `allowed_tools` | `list[str]` |   | Tokens parsed from `allowed-tools` (e.g. `["Bash(git:*)", "Read", "Write"]`). |
| `tags` | `list[str]` |   | User-facing tags. |
| `compatibility` | `dict[str, Any] \| None` |   | Compatibility block from SKILL.md frontmatter. |
| `tarball_url` | `str \| None` |   | For `github://` sources: the resolved `codeload.github.com/.../tar.gz/<ref>` URL. |
| `tarball_sha256` | `str \| None` |   | Optional SHA-256 of the resolved tarball for stronger pinning. |

### URI shapes

`uri` is what the CARL `SkillResolver` matched on. Supported shapes:

* `github://owner/repo[/subpath][@ref]` — remote SKILL bundle hosted on
  GitHub. `tarball_url` + `tarball_sha256` should be populated for these.
* `local://absolute/path` — a path on the operator's machine.
* `https://...` — an HTTP(S) endpoint serving the SKILL bundle.
* `module://pkg` — an importable Python module shipping a SKILL folder.
* A bare skill name — resolved against the local registry.

## Endpoints

All routes live under `/v1/agent-skills/` and follow the same shape as
`/v1/agents`, `/v1/chains`, `/v1/memory-cards`. Authentication is dual-mode
(`AUTH_REQUIRED=false` allows anonymous reads; writes auto-scope to
`auth.owner` for authenticated callers).

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/agent-skills` | Create a new skill (first version). Body: `EntityCreateRequest`. |
| `GET` | `/v1/agent-skills` | List with CARE-library knobs (see below). |
| `GET` | `/v1/agent-skills/{id}` | Resolve channel → version. Supports `If-None-Match` for `304`. |
| `PUT` | `/v1/agent-skills/{id}` | Append an immutable version. `If-Match` optimistic concurrency. |
| `PATCH` | `/v1/agent-skills/{id}` | Partial update of `display_name`/`description`/`tags`/`favourite`. **Does not** create a new version. |
| `POST` | `/v1/agent-skills/{id}/favourite` | Idempotent set (body: `{"favourite": true\|false}`). |
| `POST` | `/v1/agent-skills/{id}/run-recorded` | Bump `run_count`, set `last_run_at = now()`. |
| `DELETE` | `/v1/agent-skills/{id}` | Soft-delete (sets `deleted_at`). |

### List query knobs

`GET /v1/agent-skills` accepts the same CARE-library knobs as the other
typed entity routers plus two tool-filter parameters:

| Param | Default | Notes |
| --- | --- | --- |
| `limit` | `50` (max `200`) | Page size. |
| `offset` | `0` | Used when cursor pagination isn't viable. |
| `cursor` | — | Keyset-pagination cursor from `X-Next-Cursor`. Only valid with the default sort. |
| `channel` | `latest` | Version channel to resolve. |
| `sort_by` | `last_run_at` | One of `created_at` \| `last_run_at` \| `run_count` \| `display_name`. |
| `sort_dir` | `desc` | `asc` \| `desc`. |
| `favourites_only` | `false` | Restrict to `favourite=TRUE`. |
| `tags` | — | AND-filter — skill's `tags` JSONB array must contain every listed token. |
| `q` | — | Case-insensitive substring across `display_name` / `name` / `description`. |
| `namespace` | auto-scoped to `auth.owner` | Read across namespaces requires the `read:any` scope. |
| `requires_tool` | — | AND-filter — skill's `allowed_tools` array must contain every listed token. |
| `excludes_tool` | — | OR-filter — drop skills mentioning ANY listed token. |

Tool filters operate on `content.allowed_tools`, which the SQL list
query can't push down efficiently. The router fetches a 4× window and
applies the filter in-process, capped at `limit`. When `requires_tool`
or `excludes_tool` is set, **cursor pagination is disabled** for that
walk (`X-Next-Cursor` is omitted, `X-Has-More` returns `false`) — the
client should fall back to `offset` to continue.

Response headers: `X-Has-More: true|false`, `X-Next-Cursor: <opaque>`
when pagination has more rows.

## Search-document indexing

When a skill version is written, `search_document_service` derives up
to four BM25/vector search documents from `content`. They live in
`entity_search_documents` and are rebuilt on every version write.

| `document_kind` | Text content | Purpose |
| --- | --- | --- |
| `skill_description` | `"<name>\n<description>"` | Fast first-pass BM25 match for MAGE capability lookup. |
| `skill_instructions` | SKILL.md body (`instructions`) | Vector search ("extract structured data from PDFs" → Anthropic's `pdf` skill). |
| `skill_full` | `"<name>\n<description>\n<instructions>"` | Default BM25 catch-all. |
| `skill_allowed_tools` | `"Bash(python:*), Read, Write"` (comma-joined) | Tag-style filtering / facet queries. |

The `card_id` column on `entity_search_documents` doubles as a generic
external-id slot — for skills it stores the `name` (or `uri` as a
fallback) so MAGE can look up a skill by SKILL.md name without
round-tripping the `entity_id`. `meta_json` carries
`{skill_name, uri, snippet, document_kind}`.

`INDEXED_ENTITY_TYPES = {"memory_card", "agent_skill"}` controls which
entity types are indexed at version-write time. Adding a new indexed
type means extending this set and providing a `derive_*_search_documents`
function.

## Library metadata

AgentSkills share the CARE library-metadata columns added in
migration 003 with the other typed entities:

| Column | Default | Mutated by |
| --- | --- | --- |
| `favourite` | `FALSE` | `POST /favourite`, `PATCH` |
| `run_count` | `0` | `POST /run-recorded` |
| `last_run_at` | `NULL` | `POST /run-recorded` |
| `display_name` | `name[:200]` on creation | `PATCH` |
| `description` | `when_to_use` on creation | `PATCH` |

These are denormalised on the `entities` row so the catalogue's list
query can sort by recency / favourites without joining `entity_versions`.

## Client SDK surface

```python
from gigaevo_client import GigaEvoClient, AgentSkillSpec

with GigaEvoClient(base_url="http://localhost:8002") as client:
    skill = AgentSkillSpec(
        name="pdf-extract",
        description="Extract text and tables from PDFs.",
        uri="github://anthropic/skill-pdf-extract@v1",
        sha256="0" * 64,
        manifest={"name": "pdf-extract", "license": "MIT"},
        instructions="Use pdfplumber for tables; pypdf for text.",
        allowed_tools=["Read", "Write", "Bash(python:*)"],
        tags=["pdf", "extraction"],
    )

    # Create.
    ref = client.save_agent_skill(skill, name=skill.name, tags=skill.tags)

    # Read.
    same = client.get_agent_skill(ref.entity_id)
    assert same.sha256 == skill.sha256

    # CARE catalogue: recently-used skills first, filtered by tool.
    recent = client.list_agent_skills(
        sort_by="last_run_at", favourites_only=False,
        requires_tools=["Read"],
        excludes_tools=["Bash"],
    )

    # CARE flow: bump run-count after a chain finishes a step using this skill.
    client.record_agent_skill_run(ref.entity_id)

    # CARE catalogue mutations (no new version).
    client.mark_agent_skill_favourite(ref.entity_id, True)
    client.update_agent_skill_metadata(
        ref.entity_id, display_name="PDF Extractor", tags=["pdf", "office"],
    )
```

## CARE / MAGE consumption

The end-to-end flow MAGE drives during chain generation:

1. **MAGE generates a chain.** During reasoning it surfaces sub-goals
   such as *"extract text from a PDF"*.
2. **Capability lookup.** MAGE calls
   `client.search(query=sub_goal, entity_type="agent_skill", search_type="hybrid")`.
   The hybrid search combines BM25 over `skill_description` + vector
   similarity over `skill_instructions`, optionally pre-filtered with
   `excludes_tools=["Bash"]` when the deployment is sandboxed.
3. **Capability resolution.** Top hits map back to `entity_id`s. MAGE
   embeds the chosen skills' `entity_id`s into the chain's
   `metadata.allowed_skills`.
4. **CARE picks up the chain.** Before running, CARE resolves each
   `entity_id` via `client.get_agent_skill(eid)` and downloads the
   referenced bundle through the SKILL resolver
   (the `uri` + `tarball_url` + `tarball_sha256` give the resolver
   everything it needs).
5. **Run-record.** When the chain finishes a step that exercised the
   skill, CARE calls `client.record_agent_skill_run(eid)`. The next
   `list_agent_skills(sort_by="last_run_at")` then shows the skill at
   the top of the catalogue.
6. **User catalogue actions** (rename, tag, favourite) hit `PATCH
   /v1/agent-skills/{id}` and the `/favourite` toggle — none of these
   create a new version.

## Ingestion helper

The client SDK ships
`MemoryClient.ingest_skill_from_carl(resolved_skill, *, entity_id=None, ...)`
which is the one-call helper MAGE and CARE use:

```python
from gigaevo_client import GigaEvoClient

with GigaEvoClient() as client:
    # First-time ingestion — creates new entity, returns its entity_id.
    ref = client.ingest_skill_from_carl(
        resolved_skill,         # CARL ResolvedSkill, AgentSkillSpec, or dict
        author="mage",
        namespace="glazkov",
    )

    # Re-ingestion of a newer SKILL.md — appends a new version.
    ref_v2 = client.ingest_skill_from_carl(
        resolved_v2,
        entity_id=ref.entity_id,  # upsert onto the existing skill
    )
```

The helper is **duck-typed** — it doesn't take a hard dependency on
`mmar_carl`. It pulls `manifest`/`instructions`/`allowed_tools`/`sha256`/
`uri`/`tarball_url`/`tarball_sha256` from the input via documented
fallback chains:

* `source_uri` → `uri`
* `sha256` → `skill_md_sha256`
* `instructions` → `body`
* `manifest.get_allowed_tools()` → `manifest.allowed_tools`
* `manifest.tags` → `manifest.metadata["tags"]`

Validation runs **before any HTTP traffic**: missing `sha256`,
`source_uri`, or `manifest` raises `ValueError`. Idempotency is
caller-driven via `entity_id`: pass it to update, omit it to create.

The internal projection helper `_extract_skill_spec(resolved)` is
exposed at module level for callers that want the same coercion
without the persistence side-effect.

## Compatibility notes

* `AgentSkillContent` is **read-leniently / write-strictly** — clients
  tolerate missing optional fields (`manifest`, `compatibility`,
  `tarball_*` may all be absent on older entries) but emit only the
  documented shape on writes.
* Memory does not validate `content` against `AgentSkillContent` server-side.
  The model is exposed via OpenAPI so clients can validate locally. The
  server will accept a malformed body — it's the caller's responsibility
  to send well-formed JSON.
* The `tarball_*` fields exist for `github://` sources whose `@ref` was
  resolved to a specific tarball at ingestion time. They are
  informational — Memory never fetches them. CARE / MAGE re-resolve
  through the SKILL resolver, which may re-fetch the tarball.
* Forward-compatible additions go into `manifest` (already a free-form
  dict) without bumping any schema version.
