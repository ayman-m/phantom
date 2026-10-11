/**
 * Server-side helper for fetching the live skills registry to inject
 * into the chat system prompt. Used by `app/api/chat/route.ts` to
 * make the model aware of available skills WITHOUT shipping their
 * full bodies in the prompt — just metadata (name, displayName,
 * category, description, ATT&CK tactics).
 *
 * Why a dedicated helper:
 * - Centralizes the fetch shape so route.ts doesn't grow another
 *   inline call.
 * - Catches errors so a transient MCP hiccup degrades to "no skills
 *   block" rather than failing the whole chat turn.
 * - Maps the broad LiveSkillRow shape (which has filesystem-level
 *   fields the model doesn't need) down to the SkillSummary shape
 *   the prompt builder expects. Extra fields would be wasted tokens.
 */

import { PhantomMCPClient } from '@/lib/mcp-client';
import { getEffectiveRuntimeConfig } from '@/lib/runtime-config';
import type { SkillSummary } from '@/lib/system-prompt';

interface SkillsListResponse {
  // Shape from skills_crud.py::get_all_skills (frontmatter
  // fields). We only consume a subset here.
  name: string;
  displayName?: string;
  category: string;
  description?: string;
  attack?: string[];
}

/**
 * Fetch the skills registry from the embedded MCP and return the
 * minimal metadata shape the prompt builder needs. Returns an empty
 * array on any failure — callers should treat that as "no skills
 * block in the prompt this turn" rather than escalating.
 */
export async function fetchSkillsForPrompt(): Promise<SkillSummary[]> {
  try {
    const config = await getEffectiveRuntimeConfig();
    const mcpToken =
      (config.MCP_TOKEN || '').trim() || process.env.MCP_TOKEN?.trim() || '';
    const mcpUrl =
      (config.MCP_URL || '').trim() ||
      process.env.MCP_URL?.trim() ||
      'http://localhost:8080/api/v1/stream/mcp';
    if (!mcpToken || !mcpUrl) return [];

    const client = new PhantomMCPClient(mcpUrl, mcpToken);
    const result = await client.callTool('skills_list_all', {});
    const raw = result.content?.[0]?.text || '[]';
    const rows = JSON.parse(raw) as SkillsListResponse[];
    if (!Array.isArray(rows)) return [];

    return rows.map((row) => ({
      name: row.name,
      displayName: row.displayName || row.name,
      category: row.category,
      description:
        row.description ||
        '(no description in frontmatter — operator should add one)',
      attack: row.attack && row.attack.length > 0 ? row.attack : undefined,
    }));
  } catch (err) {
    // Silent failure on purpose — a chat turn without the skills
    // block is still a useful turn. We log to server stderr so
    // operators can see drift via docker logs, but the chat
    // continues.
    if (typeof console !== 'undefined') {
      // eslint-disable-next-line no-console
      console.warn(
        '[skills-registry] failed to fetch skills for system prompt:',
        err instanceof Error ? err.message : err,
      );
    }
    return [];
  }
}
