# Evolution metadata and lineage

Every immutable version row in `entity_versions` carries an optional
`evolution_meta JSONB` column plus a typed `parents UUID[]` column. The
two together let CARE, MAGE, gigaevo-platform, and gigaevo-core leave
breadcrumbs whenever an evolutionary run produces a new version of a
chain (or any other entity). This document is the contract.

| Aspect | Value |
| --- | --- |
| Server model | `api/app/models/requests.py::EvolutionMeta` |
| Client model | `client/python/src/gigaevo_client/models.py::EvolutionMeta` |
| Storage column | `entity_versions.evolution_meta JSONB` |
| Parent edges | `entity_versions.parents UUID[]` (separate column, faster than JSONB extraction) |
| Lineage endpoint | `GET /v1/chains/{id}/lineage` |
| Lineage models | `LineageResponse` + `LineageVersion` (server + client) |
| Special channel | `evolved` — tracks highest-fitness version, auto-promoted on write |

## Schema

`EvolutionMeta` is a Pydantic model with two concentric shapes. Every
field is optional; `EvolutionMeta()` is a legal (but uninformative)
instance. Writes use the typed model on the create/update envelope;
reads return whatever JSONB shape is stored.

### CARE / Platform standardised shape (§5 P1)

| Field | Type | Notes |
| --- | --- | --- |
| `parent_version_ids` | `list[str] \| None` | UUIDs of the parent versions this version was derived from. Single-parent mutation has length 1; crossover has length ≥ 2. |
| `fitness_score` | `float \| None` | Single-objective scalar. Range depends on the fitness function (commonly `[0, 1]`). Drives `evolved`-channel promotion. |
| `generation` | `int \| None` (≥ 0) | Zero-indexed generation number within the parent experiment. |
| `experiment_id` | `str \| None` | Identifier for the parent gigaevo-platform experiment. |
| `objectives` | `dict[str, float] \| None` | Multi-objective fitness dict — e.g. `{"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200}`. |
| `mutation_kind` | `str \| None` | Free-form kind tag. Typical values: `"step_swap"`, `"prompt_rewrite"`, `"topology_change"`, `"crossover"`, `"manual_edit"`. |

### Legacy gigaevo-core shape (pre-2026-05)

These fields are preserved verbatim so pre-existing JSONB rows decode
without a reshape. New callers should prefer the standardised fields.

| Field | Type | Notes |
| --- | --- | --- |
| `prompt_ref` | `str \| None` | Pointer to the prompt template the run used. |
| `fitness` | `float \| None` | Legacy alias for `fitness_score`. **`fitness_score` wins when both are present**; `fitness` is the fallback for pre-2026 rows. |
| `is_valid` | `bool \| None` | Whether the candidate passed the validation step. |
| `metrics` | `dict[str, Any] \| None` | Free-form metric bag from the runner. |
| `behavioral_descriptors` | `dict[str, Any] \| None` | MAP-Elites behavioural-descriptors block. |

`mutation_kind` is shared between the two shapes — it predates the
standardisation and was kept as-is.

### Example payload

```json
{
  "parent_version_ids": [
    "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "ad7c66f7-9a3a-4d99-9cf0-cfe1bba4f7c1"
  ],
  "fitness_score": 0.87,
  "generation": 12,
  "experiment_id": "exp-2026-05-fin-triage",
  "objectives": {"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200},
  "mutation_kind": "crossover"
}
```

## Writes

`evolution_meta` rides on the version envelope for both creates and
updates:

```python
from gigaevo_client import GigaEvoClient, EvolutionMeta

with GigaEvoClient(base_url="http://localhost:8002") as client:
    ref = client.save_chain(
        chain=chain,
        name="fin-triage",
        evolution_meta=EvolutionMeta(
            parent_version_ids=[parent_v_id],
            fitness_score=0.87,
            generation=12,
            experiment_id="exp-2026-05-fin-triage",
            objectives={"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200},
            mutation_kind="crossover",
        ),
        parent_version_id=parent_v_id,
    )
```

Two parent-pointer mechanisms coexist:

* The **`parent_version_id` field on the create/update envelope** is
  written to the typed `entity_versions.parents UUID[]` column. This is
  what the lineage walker traverses (fast — typed UUID equality, no
  JSONB extraction). For multi-parent crossovers, supply the array
  directly via the lower-level service or extend the envelope; today
  the typed endpoint accepts a single parent and the recommended
  multi-parent path is to mirror the same IDs in `parent_version_ids`
  under `evolution_meta`.
* The **`parent_version_ids` field inside `evolution_meta`** is the
  self-describing duplicate that travels with the JSONB row. CARE and
  the platform consume this for analytics where they don't want to
  re-walk the DAG.

Pydantic auto-coerces a wire-side dict into the typed model, so callers
can send either a typed `EvolutionMeta` instance or a raw dict on the
envelope.

## The `evolved` channel

Channels (`latest`, `stable`, custom names) are pointers on
`entities.channels` mapping to a `version_id`. The reserved `evolved`
channel always tracks the **highest-fitness** version of the entity.
Promotion happens **automatically** on every write, transparent to
callers — no extra API call needed.

Auto-promotion rules (implemented in
`EntityService._maybe_promote_evolved_channel`):

1. **No fitness on the new version → no-op.** `fitness_score` is read
   first, then the legacy `fitness` alias as a fallback.
2. **No `evolved` channel yet → pin it.** First evolution always wins.
3. **Current pin's fitness is missing or unparsable → pin new.**
   Corrupt pointers and missing referenced versions are overwritten
   with the known-good new version.
4. **New fitness > current → pin new.** Strict `>` deliberately — a
   re-run with an identical score does NOT churn the pointer.
5. **Otherwise → leave the pin alone.** A regression keeps the
   incumbent.

Consumers read the highest-fitness version like any other channel:

```python
best = client.get_chain(entity_id, channel="evolved")
```

CARE uses this to surface "show only best-evolved chains" in its
catalogue filter.

### Worked example: 5-generation run with a regression

| Generation | Fitness | `evolved` pin after write |
| --- | --- | --- |
| 0 | 0.30 | v0 (first-evolution rule 2) |
| 1 | 0.45 | v1 (rule 4: 0.45 > 0.30) |
| 2 | 0.61 | v2 (rule 4: 0.61 > 0.45) |
| 3 | 0.52 | **v2** (rule 5: 0.52 ≤ 0.61, regression — keep incumbent) |
| 4 | 0.83 | v4 (rule 4: 0.83 > 0.61) |

The `latest` channel still tracks v4 throughout. The `evolved` channel
tracks the local maximum: v0 → v1 → v2 → v2 → v4.

## Lineage endpoint

```
GET /v1/chains/{chain_id}/lineage
```

Returns the ancestry DAG starting at a specific version (the "root" of
the walk — usually the channel-resolved version). The walker does
breadth-first traversal of `entity_versions.parents`, de-dupes by
`version_id` so diamond crossovers appear once, and stops at
`max_depth`.

| Query param | Default | Notes |
| --- | --- | --- |
| `channel` | `latest` | Channel to resolve as the walk root. |
| `version_id` | — | Override: walk from a specific version (descendants are excluded). |
| `max_depth` | `10` (range `1`–`100`) | BFS depth cap. When reached, `max_depth_reached: true` flags partial expansion. |

### Response shape

```json
{
  "entity_id": "...",
  "root_version_id": "...",
  "max_depth_reached": false,
  "versions": [
    {
      "version_id": "...",
      "version_number": 5,
      "parents": ["...v4..."],
      "evolution_meta": {"fitness_score": 0.83, "generation": 4, "mutation_kind": "prompt_rewrite"},
      "change_summary": "...",
      "author": "mage",
      "created_at": "2026-05-16T11:42:00Z",
      "depth": 0
    },
    { "version_id": "...v4...", "depth": 1, "parents": ["...v2...", "...v3..."], "...": "..." }
  ]
}
```

`versions` is in BFS order (root first, depth 1, depth 2, …) — clients
can render layered evolution trees without re-walking. Each
`LineageVersion` carries its own `parents` array, so a client that
needs the full DAG topology has everything it needs in one response.

### Response model fields

`LineageResponse` carries `entity_id`, `root_version_id`, `versions`,
`max_depth_reached`.

Each `LineageVersion` carries `version_id`, `version_number`, `parents`,
`evolution_meta`, `change_summary`, `author`, `created_at`, `depth`.

### Client usage

```python
lineage = client.get_chain_lineage(
    entity_id, channel="latest", max_depth=20,
)
print(f"Root v{lineage.versions[0].version_number}, walked {len(lineage.versions)} versions")
if lineage.max_depth_reached:
    print("  ⚠️  hit max_depth — re-issue with a larger cap to walk further")
```

Today only chains expose `/lineage`. Same shape can be added to other
typed routers if MAGE/CARE start evolving agents, agent_skills, or
memory_cards.

## CARE / Platform consumption

The end-to-end flow gigaevo-platform drives:

1. **Platform writes a new evolved version.**
   `PUT /v1/chains/{id}` with `evolution_meta.fitness_score`,
   `generation`, `experiment_id`, plus `parent_version_id` on the
   envelope. The server appends a new `entity_versions` row, persists
   the JSONB, pushes the UUID into `parents`, and runs
   `_maybe_promote_evolved_channel` — silently pinning `evolved` if
   the new fitness beats the incumbent.
2. **CARE's library catalog shows the best-evolved view.**
   `GET /v1/chains/{id}?channel=evolved` returns the version with the
   highest recorded fitness. The catalogue defaults to this channel
   when the user toggles "show best".
3. **CARE renders the evolution tree.**
   `GET /v1/chains/{id}/lineage?max_depth=20`. The response's BFS
   ordering + `depth` field map directly onto CARE's
   `LibraryScreen.EvolutionTree` widget: layer N stacks all nodes
   with `depth == N`. Multi-parent crossover nodes are detected via
   `len(parents) > 1`.
4. **Re-run from a specific generation.** The user picks a node in the
   tree; CARE issues `GET /v1/chains/{id}?version_id=<node>` to fetch
   that exact version's `content` and re-runs it with the same inputs
   from `metadata.context_files`.

## Compatibility notes

* `EvolutionMeta` is **read-leniently / write-strictly**. Old rows with
  only `fitness` / `prompt_ref` / `metrics` decode without reshape.
  New callers should write `fitness_score` (not `fitness`), even
  though the auto-promotion helper accepts both as input.
* The Memory server **never validates `evolution_meta` against
  `EvolutionMeta`** at the storage layer. The model exists so clients
  can validate locally and OpenAPI documents the agreed shape. A
  malformed value will land in JSONB; `_extract_fitness` is defensive
  about unparsable types.
* `mutation_kind` is a free string — the enumerated typical values
  in the table above are guidance, not validation. CARE / platform may
  introduce additional values without breaking the schema.
* `parent_version_ids` (inside `evolution_meta`) is the self-describing
  copy of the parent pointers; the authoritative copy for lineage
  walking is the typed `entity_versions.parents` column. Keep them in
  sync on writes — the lineage walker won't consult `evolution_meta`.
* The `evolved` channel is reserved. Pinning it manually via
  `PUT /v1/chains/{id}/pin` works, but the next write that carries a
  higher fitness will overwrite the manual pin. Use a custom channel
  name (e.g. `human-blessed-best`) if you need a manual override that
  doesn't churn.
