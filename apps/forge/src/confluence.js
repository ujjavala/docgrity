/**
 * Confluence access via Forge asApp() — permission-safe, no tokens to manage.
 * Deterministic code only (architectural principle: no LLM in CRUD paths).
 */
import api, { route } from '@forge/api';

async function json(res, what) {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Confluence ${what} failed ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

export async function listAllPages(spaceId = null) {
  const pages = [];
  let cursor = null;
  do {
    const q = cursor
      ? route`/wiki/api/v2/pages?body-format=storage&limit=50&cursor=${cursor}`
      : spaceId
        ? route`/wiki/api/v2/pages?body-format=storage&limit=50&space-id=${spaceId}`
        : route`/wiki/api/v2/pages?body-format=storage&limit=50`;
    const data = await json(await api.asApp().requestConfluence(q), 'list pages');
    pages.push(...(data.results ?? []));
    const next = data?._links?.next;
    cursor = next ? new URL(`https://x${next}`).searchParams.get('cursor') : null;
  } while (cursor);
  return pages;
}

export async function getPageVersionAuthor(pageId) {
  const data = await json(
    await api
      .asApp()
      .requestConfluence(route`/wiki/api/v2/pages/${pageId}/versions?limit=1&sort=-modified-date`),
    'page versions'
  );
  return data.results?.[0]?.authorId ?? null;
}

export async function getUserDisplayName(accountId) {
  try {
    const data = await json(
      await api.asApp().requestConfluence(route`/wiki/rest/api/user?accountId=${accountId}`),
      'get user'
    );
    return data.displayName || data.publicName || accountId;
  } catch {
    return accountId;
  }
}

const ADMIN_GROUPS = new Set([
  'site-admins',
  'administrators',
  'org-admins',
  'confluence-admins',
  'confluence-administrators',
]);

/** Server-side check: is this account a Confluence/site admin? */
export async function isSiteAdmin(accountId) {
  if (!accountId) return false;
  try {
    const data = await json(
      await api
        .asApp()
        .requestConfluence(route`/wiki/rest/api/user/memberof?accountId=${accountId}&limit=200`),
      'user groups'
    );
    return (data.results ?? []).some((g) => ADMIN_GROUPS.has((g.name || '').toLowerCase()));
  } catch {
    return false;
  }
}

export async function getPage(pageId) {
  return json(
    await api
      .asApp()
      .requestConfluence(route`/wiki/api/v2/pages/${pageId}?body-format=storage`),
    'get page'
  );
}

export async function updatePage(pageId, title, storageHtml, version, message) {
  return json(
    await api.asApp().requestConfluence(route`/wiki/api/v2/pages/${pageId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: pageId,
        status: 'current',
        title,
        body: { representation: 'storage', value: storageHtml },
        version: { number: version, message },
      }),
    }),
    'update page'
  );
}

export async function archivePage(pageId) {
  const res = await api.asApp().requestConfluence(route`/wiki/rest/api/content/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages: [{ id: Number(pageId) }] }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Confluence archive failed ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.status === 204 ? {} : res.json();
}

export async function listSpaces() {
  const data = await json(
    await api.asApp().requestConfluence(route`/wiki/api/v2/spaces?limit=100`),
    'list spaces'
  );
  return (data.results ?? []).map((s) => ({ id: s.id, key: s.key, name: s.name }));
}

export async function addFooterComment(pageId, storageHtml) {
  return json(
    await api.asApp().requestConfluence(route`/wiki/api/v2/footer-comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pageId,
        body: { representation: 'storage', value: storageHtml },
      }),
    }),
    'add comment'
  );
}

export async function getSiteBaseUrl() {
  const data = await json(
    await api.asApp().requestConfluence(route`/wiki/api/v2/spaces?limit=1`),
    'site info'
  );
  const base = data?._links?.base;
  return base || '';
}

/** Strip storage-format XML/HTML to plain text for embedding + LLM input. */
export function storageToText(storage) {
  return (storage || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();
}
