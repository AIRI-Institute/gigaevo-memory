# Changelog

## 0.2.0 (2026-02-20)

- Breaking: client returns typed CARL steps only (LLMStepDescription, ToolStepDescription, etc.)
- Update CARL integration to rely on ReasoningChain.from_dict / to_dict with minimal patching for llm_config and ContextQuery
- Bump dependency to mmar-carl>=0.0.16

## 0.1.0 (2026-02-12)

- Initial release
- MemoryClient with CRUD operations for steps, chains, agents, memory cards
- CARL integration via optional `[carl]` extra (ReasoningChain, StepDescription)
- Cache policies: TTL, Freshness Check, SSE Push
- SSE-based watch/subscription for hot-swap updates
- Raw dict mode for lightweight usage without mmar-carl
- Full version management: list, diff, revert, pin, promote
- Search: full-text + faceted filtering
