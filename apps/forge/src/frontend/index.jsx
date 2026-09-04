/**
 * Docgrity for Confluence — findings dashboard (UI Kit global page).
 *
 * Three levels: stats overview → filtered findings list (sortable) →
 * finding detail (evidence, page links, potential owners).
 *
 * Forge-native: all data comes from resolvers (invoke). Analysis runs in
 * async-event consumers inside the Forge runtime; the tenant brings their
 * own LLM provider + API key (Settings).
 */
import React, { useEffect, useState } from 'react';
import ForgeReconciler, {
  Button,
  ButtonGroup,
  DynamicTable,
  Heading,
  Inline,
  Link,
  Lozenge,
  SectionMessage,
  Select,
  Spinner,
  Stack,
  Text,
  Textfield,
  User,
  xcss,
} from '@forge/react';
import { invoke } from '@forge/bridge';

const SEVERITY_APPEARANCE = {
  CRITICAL: 'removed',
  HIGH: 'moved',
  MEDIUM: 'inprogress',
  LOW: 'default',
};

const STATUS_APPEARANCE = {
  NEW: 'new',
  AWAITING_OWNER: 'inprogress',
  RESOLVED: 'success',
  DISMISSED: 'default',
};

const SEVERITY_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

const TYPE_LABELS = {
  DUPLICATE: 'Duplicates',
  CONTRADICTION: 'Contradictions',
  OPEN_QUESTION: 'Open questions',
};

const CHECKS = ['duplicates', 'contradictions', 'open_questions'];

const cardStyle = xcss({
  backgroundColor: 'elevation.surface.raised',
  boxShadow: 'elevation.shadow.raised',
  borderRadius: 'border.radius.200',
  padding: 'space.200',
  minWidth: '160px',
});

const settingsFormStyle = xcss({
  maxWidth: '480px',
});

const call = (fn, payload) => invoke(fn, payload);

/* ---------- Human-approved actions ---------- */

const ActionsPanel = ({ finding, pages, onDone }) => {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null); // {label, run}
  const [draft, setDraft] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const run = async (fn, successMsg) => {
    setBusy(true);
    setError(null);
    setConfirm(null);
    try {
      await fn();
      setMessage(successMsg);
      if (onDone) onDone();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const isDuplicate = finding.type === 'DUPLICATE';
  const isContradiction = finding.type === 'CONTRADICTION';
  const hasOwners = (finding.potential_owners ?? []).length > 0;
  const actionable = !['RESOLVED', 'DISMISSED', 'FALSE_POSITIVE'].includes(finding.status);
  if (!actionable || (!isDuplicate && !isContradiction && !hasOwners)) return null;

  return (
    <Stack space="space.100">
      <Heading as="h4">Fix it</Heading>
      {message && (
        <SectionMessage appearance="success" title="Action completed">
          <Text>{message}</Text>
        </SectionMessage>
      )}
      {error && (
        <SectionMessage appearance="error" title="Action failed">
          <Text>{error}</Text>
        </SectionMessage>
      )}

      {hasOwners && !message && (
        <Inline>
          <Button
            isDisabled={busy}
            onClick={() =>
              setConfirm({
                label:
                  'Post a Docgrity comment on the page @-mentioning the inferred owner so they can review this finding?',
                run: () =>
                  run(
                    () => call('notifyOwner', { id: finding.id }),
                    'Owner notification queued — the Docgrity comment will appear on the page shortly.',
                  ),
              })
            }
          >
            Notify potential owner
          </Button>
        </Inline>
      )}

      {isDuplicate && pages.length === 2 && !message && (
        <Inline space="space.100">
          {pages.map((keep) => {
            const other = pages.find((p) => p !== keep);
            return (
              <Button
                key={keep.id}
                isDisabled={busy || !keep.id}
                onClick={() =>
                  setConfirm({
                    label: `Keep “${keep.title}” and archive “${other.title}” (a redirect notice is added first).`,
                    run: () =>
                      run(
                        () =>
                          call('mergeRedirect', {
                            id: finding.id,
                            keep_item_id: keep.id,
                          }),
                        `Archived “${other.title}” with a redirect to “${keep.title}”.`,
                      ),
                  })
                }
              >
                Keep “{keep.title}”
              </Button>
            );
          })}
        </Inline>
      )}

      {isContradiction && !draft && !message && (
        <Inline>
          <Button
            appearance="primary"
            isDisabled={busy}
            onClick={() =>
              run(
                async () =>
                  setDraft(await call('draftFix', { id: finding.id })),
                null,
              )
            }
          >
            {busy ? 'Drafting…' : 'Draft a fix'}
          </Button>
        </Inline>
      )}

      {isContradiction && draft && !message && (
        <Stack space="space.100">
          <Text>{draft.reasoning}</Text>
          {draft.patches.length === 0 && (
            <SectionMessage title="No safe automatic fix">
              <Text>Docgrity could not draft a safe exact-match edit for this contradiction.</Text>
            </SectionMessage>
          )}
          {draft.patches.map((p, i) => (
            <SectionMessage key={i} title={`Proposed edit — ${p.page_title ?? p.page_external_id}`}>
              <Text>Replace: “{p.find_text}”</Text>
              <Text>With: “{p.replace_text}”</Text>
              <Text>
                {p.rationale} ({Math.round(p.confidence * 100)}% confidence)
              </Text>
              <Button
                appearance="primary"
                isDisabled={busy}
                onClick={() =>
                  setConfirm({
                    label: `Apply this edit to “${p.page_title ?? p.page_external_id}”? The page is updated with a new version.`,
                    run: () =>
                      run(
                        () =>
                          call('applyFix', {
                            id: finding.id,
                            page_external_id: p.page_external_id,
                            find_text: p.find_text,
                            replace_text: p.replace_text,
                          }),
                        'Fix applied and finding resolved.',
                      ),
                  })
                }
              >
                Apply fix
              </Button>
            </SectionMessage>
          ))}
        </Stack>
      )}

      {confirm && (
        <SectionMessage appearance="warning" title="Confirm action">
          <Text>{confirm.label}</Text>
          <Inline space="space.100">
            <Button appearance="danger" isDisabled={busy} onClick={confirm.run}>
              {busy ? 'Working…' : 'Yes, do it'}
            </Button>
            <Button appearance="subtle" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
          </Inline>
        </SectionMessage>
      )}
    </Stack>
  );
};

/* ---------- Level 3: finding detail ---------- */

const FindingDetail = ({ findingId, onBack }) => {
  const [finding, setFinding] = useState(null);
  const [error, setError] = useState(null);

  const reload = () => {
    call('getFinding', { id: findingId }).then(setFinding).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    reload();
  }, [findingId]);

  if (error) {
    return (
      <SectionMessage appearance="error" title="Could not load finding">
        <Text>{error}</Text>
      </SectionMessage>
    );
  }
  if (!finding) return <Spinner label="Loading finding…" />;

  const pages = finding.pages?.length ? finding.pages : finding.detail?.pages ?? [];
  const claims = finding.detail?.conflicting_claims ?? [];
  const differences = finding.detail?.differences ?? [];
  const questions = finding.detail?.questions ?? [];

  return (
    <Stack space="space.200">
      <Button appearance="subtle" onClick={onBack}>
        ← Back to findings
      </Button>
      <Heading as="h2">{finding.title}</Heading>
      <Inline space="space.100">
        <Lozenge appearance={SEVERITY_APPEARANCE[finding.severity] ?? 'default'}>
          {finding.severity}
        </Lozenge>
        <Lozenge appearance={STATUS_APPEARANCE[finding.status] ?? 'default'}>
          {finding.status}
        </Lozenge>
        <Lozenge>{`${Math.round(finding.confidence * 100)}% confidence`}</Lozenge>
        {finding.recommended_action ? (
          <Lozenge appearance="new">{finding.recommended_action}</Lozenge>
        ) : null}
      </Inline>
      <Text>{finding.summary}</Text>

      {pages.length > 0 && (
        <Stack space="space.050">
          <Heading as="h4">Pages involved</Heading>
          {pages.map((p) => (
            <Text key={p.external_id ?? p.title}>
              📄{' '}
              {p.url ? (
                <Link href={p.url} openNewTab>
                  {p.title}
                </Link>
              ) : (
                p.title
              )}
            </Text>
          ))}
        </Stack>
      )}

      {claims.length > 0 && (
        <Stack space="space.050">
          <Heading as="h4">Conflicting claims</Heading>
          {claims.map((c, i) => (
            <Text key={i}>⚔️ {c}</Text>
          ))}
        </Stack>
      )}

      {questions.length > 0 && (
        <Stack space="space.050">
          <Heading as="h4">Unresolved questions</Heading>
          {questions.map((q, i) => (
            <Text key={i}>❓ {q}</Text>
          ))}
        </Stack>
      )}

      {differences.length > 0 && (
        <Stack space="space.050">
          <Heading as="h4">Material differences</Heading>
          {differences.map((d, i) => (
            <Text key={i}>• {d}</Text>
          ))}
        </Stack>
      )}

      <ActionsPanel finding={finding} pages={pages} onDone={reload} />

      <Stack space="space.050">
        <Heading as="h4">Why Docgrity flagged this</Heading>
        {(finding.evidence ?? []).length === 0 ? (
          <Text>No evidence recorded.</Text>
        ) : (
          finding.evidence.map((e, i) => (
            <SectionMessage key={i} title={e.source_label}>
              <Text>“{e.excerpt}”</Text>
            </SectionMessage>
          ))
        )}
      </Stack>

      {(finding.potential_owners ?? []).length > 0 && (
        <Stack space="space.050">
          <Heading as="h4">Potential owners (inferred, not asserted)</Heading>
          {finding.potential_owners.map((o, i) => (
            <Inline key={i} space="space.100" alignBlock="center">
              {o.account_id ? (
                <User accountId={o.account_id} />
              ) : (
                <Text>{o.display_name}</Text>
              )}
              <Text>
                — {Math.round(o.confidence * 100)}% ({(o.evidence ?? []).join('; ')})
              </Text>
            </Inline>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

/* ---------- Level 2: findings list ---------- */

const FindingsList = ({ type, onBack, onOpen }) => {
  const [findings, setFindings] = useState(null);
  const [error, setError] = useState(null);
  const [severityFilter, setSeverityFilter] = useState(null);
  const [ignoring, setIgnoring] = useState(null);

  const load = () => {
    call('listFindings', { type: type ?? null, limit: 100 })
      .then(setFindings)
      .catch((e) => setError(String(e)));
  };

  useEffect(load, [type]);

  const ignore = async (id) => {
    setIgnoring(id);
    try {
      await call('setFindingStatus', { id, status: 'DISMISSED' });
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setIgnoring(null);
    }
  };

  if (error) {
    return (
      <SectionMessage appearance="error" title="Could not load findings">
        <Text>{error}</Text>
      </SectionMessage>
    );
  }
  if (!findings) return <Spinner label="Loading findings…" />;

  const visible = severityFilter
    ? findings.filter((f) => f.severity === severityFilter)
    : findings;

  const head = {
    cells: [
      { key: 'title', content: 'Finding', isSortable: true },
      { key: 'severity', content: 'Severity', isSortable: true },
      { key: 'status', content: 'Status', isSortable: true },
      { key: 'confidence', content: 'Confidence', isSortable: true },
      { key: 'owner', content: 'Potential owner', isSortable: true },
      { key: 'action', content: 'Recommended action' },
      { key: 'open', content: '' },
    ],
  };

  const rows = visible.map((f) => ({
    key: f.id,
    cells: [
      { key: f.title, content: f.title },
      {
        key: SEVERITY_ORDER[f.severity] ?? 9,
        content: (
          <Lozenge appearance={SEVERITY_APPEARANCE[f.severity] ?? 'default'}>
            {f.severity}
          </Lozenge>
        ),
      },
      {
        key: f.status,
        content: (
          <Lozenge appearance={STATUS_APPEARANCE[f.status] ?? 'default'}>{f.status}</Lozenge>
        ),
      },
      { key: 1 - f.confidence, content: `${Math.round(f.confidence * 100)}%` },
      {
        key: (f.owner_names ?? []).join(', ') || '~',
        content: (f.owner_names ?? []).length > 0 ? f.owner_names.join(', ') : '—',
      },
      { key: f.recommended_action ?? '', content: f.recommended_action ?? '—' },
      {
        key: 'open',
        content: (
          <Inline space="space.050">
            <Button appearance="link" onClick={() => onOpen(f.id)}>
              View
            </Button>
            {f.status !== 'DISMISSED' && (
              <Button
                appearance="subtle"
                isDisabled={ignoring === f.id}
                onClick={() => ignore(f.id)}
              >
                {ignoring === f.id ? 'Ignoring…' : 'Ignore'}
              </Button>
            )}
          </Inline>
        ),
      },
    ],
  }));

  return (
    <Stack space="space.200">
      <Button appearance="subtle" onClick={onBack}>
        ← Back to overview
      </Button>
      <Heading as="h2">{type ? TYPE_LABELS[type] ?? type : 'All findings'}</Heading>
      <Inline space="space.100" alignBlock="center">
        <Text>Filter severity:</Text>
        <ButtonGroup>
          {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((s) => (
            <Button
              key={s}
              appearance={severityFilter === s ? 'primary' : 'default'}
              onClick={() => setSeverityFilter(severityFilter === s ? null : s)}
            >
              {s}
            </Button>
          ))}
        </ButtonGroup>
      </Inline>
      {rows.length === 0 ? (
        <SectionMessage appearance="success" title="No findings">
          <Text>Nothing detected in this category.</Text>
        </SectionMessage>
      ) : (
        <DynamicTable
          head={head}
          rows={rows}
          rowsPerPage={15}
          defaultSortKey="severity"
          defaultSortOrder="ASC"
        />
      )}
      <Text>{`${visible.length} finding(s)`}</Text>
    </Stack>
  );
};

/* ---------- Level 1: stats overview ---------- */

const StatCard = ({ label, count, emphasis, onClick }) => (
  <Stack xcss={cardStyle} space="space.100">
    <Text>{label}</Text>
    <Heading as="h1">{String(count)}</Heading>
    <Button
      appearance={emphasis ? 'primary' : 'default'}
      onClick={onClick}
      isDisabled={count === 0}
    >
      View
    </Button>
  </Stack>
);

const Overview = ({ onDrill, onSettings }) => {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [scanMessage, setScanMessage] = useState(null);
  const [spaces, setSpaces] = useState([]);
  const [space, setSpace] = useState(null); // { label, value } or null = all spaces

  const loadStats = () => {
    call('getStats').then(setStats).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    loadStats();
    call('getSpaces')
      .then((list) =>
        setSpaces((list ?? []).map((s) => ({ label: `${s.name} (${s.key})`, value: s.id }))),
      )
      .catch(() => setSpaces([]));
  }, []);

  const triggerScan = async () => {
    setScanning(true);
    setScanMessage(null);
    try {
      await call('createScan', {
        checks: CHECKS,
        post_comments: false,
        space_id: space?.value ?? null,
      });
      setScanMessage(
        `Scan started for ${space ? space.label : 'all ingested spaces'} — duplicates, contradictions and open questions. Refresh in a few minutes.`,
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setScanning(false);
    }
  };

  if (error) {
    return (
      <Stack space="space.200">
        <SectionMessage appearance="error" title="Docgrity could not load stats">
          <Text>{error}</Text>
        </SectionMessage>
        <Inline space="space.100">
          <Button onClick={onSettings}>Settings — configure AI provider</Button>
          <Button
            onClick={() => {
              setError(null);
              loadStats();
            }}
          >
            Retry
          </Button>
        </Inline>
      </Stack>
    );
  }
  if (!stats) return <Spinner label="Loading dashboard…" />;

  const types = ['DUPLICATE', 'CONTRADICTION', 'OPEN_QUESTION'];
  const severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

  return (
    <Stack space="space.300">
      <Heading as="h2">Docgrity — knowledge integrity</Heading>
      <Text>
        Where your documentation disagrees with itself. Ownership shown is potential ownership
        inferred from edit signals.
      </Text>
      <Inline space="space.100" alignBlock="stretch">
        <Select
          appearance="default"
          placeholder="All ingested spaces"
          isClearable
          options={spaces}
          value={space}
          onChange={setSpace}
        />
        <Button appearance="primary" isDisabled={scanning} onClick={triggerScan}>
          {scanning ? 'Requesting…' : 'Run full scan'}
        </Button>
        <Button onClick={loadStats}>Refresh</Button>
        <Button onClick={onSettings}>Settings</Button>
      </Inline>
      {scanMessage && (
        <SectionMessage appearance="information">
          <Text>{scanMessage}</Text>
        </SectionMessage>
      )}

      <Heading as="h3">Open findings</Heading>
      <Inline space="space.200" shouldWrap>
        <StatCard
          label="Total open"
          count={stats.total_open}
          emphasis
          onClick={() => onDrill(null)}
        />
        {types.map((t) => (
          <StatCard
            key={t}
            label={TYPE_LABELS[t]}
            count={stats.by_type[t] ?? 0}
            onClick={() => onDrill(t)}
          />
        ))}
      </Inline>

      <Heading as="h3">By severity</Heading>
      <Inline space="space.100" shouldWrap>
        {severities.map((s) => (
          <Lozenge key={s} appearance={SEVERITY_APPEARANCE[s]}>
            {`${s}: ${stats.by_severity[s] ?? 0}`}
          </Lozenge>
        ))}
      </Inline>

      {stats.last_scan_completed_at && (
        <Text>
          {`Last completed scan: ${new Date(stats.last_scan_completed_at).toLocaleString()}`}
        </Text>
      )}
    </Stack>
  );
};

/* ---------- Settings: bring-your-own LLM provider + key ---------- */

const SettingsView = ({ onBack }) => {
  const [data, setData] = useState(null);
  const [provider, setProvider] = useState(null); // {label, value}
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    call('getSettings')
      .then((d) => {
        setData(d);
        if (d.settings) {
          const p = d.providers.find((x) => x.id === d.settings.provider);
          if (p) setProvider({ label: p.label, value: p.id });
          setModel(d.settings.model ?? '');
        }
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <SectionMessage appearance="error" title="Could not load settings">
        <Text>{error}</Text>
      </SectionMessage>
    );
  }
  if (!data) return <Spinner label="Loading settings…" />;

  const selected = provider ? data.providers.find((p) => p.id === provider.value) : null;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await call('saveSettings', {
        provider: provider.value,
        model: model || undefined,
        apiKey: apiKey || undefined,
      });
      setApiKey('');
      setMessage('Settings saved. Your API key is stored encrypted and never leaves your site.');
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack space="space.200">
      <Button appearance="subtle" onClick={onBack}>
        ← Back to overview
      </Button>
      <Heading as="h2">Settings — AI provider</Heading>
      <Text>
        Docgrity runs entirely on your Atlassian site. Analysis uses your own AI provider
        account: choose a provider, pick a model, and paste your API key. The key is stored as an
        encrypted Forge secret and is only used to call the provider you choose.
      </Text>
      {message && (
        <SectionMessage appearance="success">
          <Text>{message}</Text>
        </SectionMessage>
      )}
      {!data.isAdmin && (
        <SectionMessage appearance="warning" title="Admin only">
          <Text>
            Only Confluence site admins can change the AI provider settings. You can view the
            current configuration below.
          </Text>
        </SectionMessage>
      )}
      <Stack space="space.100" xcss={settingsFormStyle}>
        <Text>Provider</Text>
        <Select
          placeholder="Choose a provider"
          options={data.providers.map((p) => ({ label: p.label, value: p.id }))}
          value={provider}
          onChange={(v) => {
            setProvider(v);
            const p = data.providers.find((x) => x.id === v?.value);
            setModel(p?.defaultModel ?? '');
          }}
        />
        <Text>Model</Text>
        <Select
          placeholder="Choose a model"
          isDisabled={!selected}
          options={(selected?.models ?? []).map((m) => ({ label: m, value: m }))}
          value={model ? { label: model, value: model } : null}
          onChange={(v) => setModel(v?.value ?? '')}
        />
        <Text>{data.hasKey ? 'API key (already set — enter to replace)' : 'API key'}</Text>
        <Textfield
          type="password"
          placeholder="paste your provider API key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        {selected && !selected.supportsEmbeddings && (
          <SectionMessage appearance="warning" title="No embeddings on this provider">
            <Text>
              This provider has no embeddings API, so duplicate/contradiction candidate selection
              falls back to comparing a capped number of page pairs directly.
            </Text>
          </SectionMessage>
        )}
        <Inline>
          <Button
            appearance="primary"
            isDisabled={saving || !provider || (!apiKey && !data.hasKey) || !data.isAdmin}
            onClick={save}
          >
            {saving ? 'Saving…' : 'Save settings'}
          </Button>
        </Inline>
      </Stack>
    </Stack>
  );
};

/* ---------- Router ---------- */

const App = () => {
  // view: {level: 'overview'} | {level: 'list', type} | {level: 'detail', findingId, type}
  const [view, setView] = useState({ level: 'overview' });

  if (view.level === 'detail') {
    return (
      <FindingDetail
        findingId={view.findingId}
        onBack={() => setView({ level: 'list', type: view.type })}
      />
    );
  }
  if (view.level === 'settings') {
    return <SettingsView onBack={() => setView({ level: 'overview' })} />;
  }
  if (view.level === 'list') {
    return (
      <FindingsList
        type={view.type}
        onBack={() => setView({ level: 'overview' })}
        onOpen={(findingId) => setView({ level: 'detail', findingId, type: view.type })}
      />
    );
  }
  return (
    <Overview
      onDrill={(type) => setView({ level: 'list', type })}
      onSettings={() => setView({ level: 'settings' })}
    />
  );
};

ForgeReconciler.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

