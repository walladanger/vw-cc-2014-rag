import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

// One coordinator runs this builder. The generated JSON is never a state authority.
const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(work);
const outputs = path.join(root, 'outputs');
const previews = path.join(work, 'previews');
const planPath = path.join(outputs, 'CC_Workshop_Implementation_Plan.md');
const xlsxPath = path.join(outputs, 'CC_Workshop_Planning_Tracker.xlsx');
const jsonPath = path.join(outputs, 'CC_Workshop_Implementation_Plan.json');
const inputNames = ['Prompt.md', 'CC_Workshop_RAG_Concept.md', '20260908modelagnosticatomicmediaplatformtracker.xlsx'];
const originalPath = path.join(work, 'inputs', inputNames[2]);
const updatePath = path.join(work, 'tracker-updates.json');
const schemaVersion = '1.0.0';
const now = new Date();
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const exists = async p => { try { await fs.access(p); return true; } catch { return false; } };
const readJSON = async (p, fallback) => await exists(p) ? JSON.parse(await fs.readFile(p, 'utf8')) : fallback;
const json = value => JSON.stringify(value);
const nonblank = value => value !== undefined && value !== null && String(value).trim() !== '';
const dateFields = new Set(['Updated at', 'Observed at', 'Execution started at', 'Execution finished at', 'Decided on']);
function normalizeTimestamp(value, label = 'Timestamp') {
  if (!nonblank(value)) return '';
  let date;
  if (value instanceof Date) date = new Date(value.getTime());
  // This builder emits the Excel 1900 date system. Import returns its date cells as serials.
  else if (typeof value === 'number' && Number.isFinite(value)) date = new Date(Math.round((value - 25569) * 86400000));
  else if (typeof value === 'string') {
    let text = value.trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += 'T00:00:00.000Z';
    else if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
      text = text.replace(' ', 'T');
      if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += 'Z';
    } else throw new Error(`${label}: expected an ISO date/time, not ${JSON.stringify(value)}`);
    date = new Date(text);
  } else throw new Error(`${label}: unsupported timestamp value`);
  if (!Number.isFinite(date.getTime())) throw new Error(`${label}: invalid timestamp`);
  return date;
}
const clean = value => String(value ?? '').replace(/\r/g, '').replace(/`([^`]+)`/g, '$1').replace(/\*\*([^*]+)\*\*/g, '$1').trim();
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const letters = n => { let s = ''; for (n++; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
const anchor = heading => heading.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/g, '-');
const statuses = ['Not started', 'In progress', 'Blocked', 'Done', 'Skipped', 'N/A'];
const decisionStatuses = ['Open', 'Answered', 'Assumed', 'Deferred', 'Noted', 'N/A'];
const workClasses = ['Planning', 'Research', 'Engineering'];
const evidenceKinds = ['Source', 'Research', 'Design', 'Execution', 'Review', 'Release', 'Decision'];
const gates = ['Not evaluated', 'Passed', 'Failed'];
const releases = ['Initial', 'Future'];
const sheetNames = ['README', 'Handover', 'Tasks', 'Steps', 'Decisions', 'Evidence'];
const headers = {
  Tasks: ['Task', 'Phase', 'Task name', 'Where', 'Status', 'Owner', 'Blocked by', 'Phase gate', 'Commit SHA', 'Notes from plan', 'Your notes', 'Work class', 'Release', 'Required task IDs', 'Required decision IDs', 'Required evidence IDs', 'Requirement IDs', 'Priority', 'Plan anchor', 'Definition of done', 'Step total', 'Steps done', 'Steps waived', 'Closed step ratio', 'Verified step ratio', 'Gate state', 'Updated at', 'Consistency check'],
  Steps: ['Step ID', 'Task', 'Step', 'Description', 'Status', 'Owner', 'Command / expected', 'Where', 'Notes', 'Work class', 'Release', 'Required step IDs', 'Required decision IDs', 'Required evidence IDs', 'Acceptance criteria', 'Outputs', 'Plan anchor', 'Updated at', 'Execution started at', 'Execution finished at', 'Executor session ID', 'Observed result', 'Run ID', 'Commit SHA'],
  Decisions: ['ID', 'Question', 'What it blocks', 'Recommendation', 'Answer', 'Status', 'Decided on', 'Decision kind', 'Owner', 'Related task IDs', 'Source/evidence IDs', 'Effective when', 'Supersedes ID', 'Updated at', 'Authority'],
  Evidence: ['#', 'Evidence required', 'Detail', 'Where', 'Status', 'Captured where', 'Notes', 'Evidence kind', 'Related task IDs', 'Related step IDs', 'Artifact SHA256', 'Observed at', 'Environment / tool version', 'Actual command', 'Exit code', 'Expected result', 'Actual result', 'Source revision', 'Run ID', 'Reviewer', 'Supersedes ID'],
};
const keys = { Tasks: 'Task', Steps: 'Step ID', Decisions: 'ID', Evidence: '#' };
const blankRecord = sheet => Object.fromEntries(headers[sheet].map(h => [h, '']));
const parseIDs = (value, label) => { let result; try { result = JSON.parse(value || '[]'); } catch { throw new Error(`${label}: invalid JSON array`); } assert(Array.isArray(result) && result.every(x => typeof x === 'string'), `${label}: expected an array of IDs`); assert(new Set(result).size === result.length, `${label}: duplicate IDs`); return result; };

await fs.mkdir(previews, { recursive: true });
await fs.mkdir(outputs, { recursive: true });
const originalBytes = await fs.readFile(originalPath);
const originalHash = sha(originalBytes);
const sourceWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(originalPath));
console.log((await sourceWorkbook.inspect({ kind: 'workbook,sheet,table', maxChars: 2500, tableMaxRows: 2, tableMaxCols: 4 })).ndjson);
const sourcePreview = await sourceWorkbook.render({ sheetName: 'README', range: 'A1:B15', scale: 1, format: 'png' });
await fs.writeFile(path.join(previews, 'source.png'), new Uint8Array(await sourcePreview.arrayBuffer()));
if (process.argv.includes('--source-preview')) {
  console.log(`Source preview only: ${path.join(previews, 'source.png')}`);
  process.exit(0);
}

let markdown = (await fs.readFile(planPath, 'utf8')).replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
const closing = markdown.indexOf('</proposed_plan>');
if (closing >= 0) markdown = markdown.slice(0, closing);
markdown = markdown.replace(/^<proposed_plan>\s*/m, '').trim() + '\n';
const finalSentence = 'Application implementation begins only after that tracking foundation is saved and validated.';
const finalPosition = markdown.indexOf(finalSentence);
assert(finalPosition >= 0, 'Approved plan closing sentence is missing; inspect the saved plan before building.');
const trailing = markdown.slice(finalPosition + finalSentence.length).trim();
assert(!trailing || /^(?:\*\*|\s)*$/.test(trailing), 'Unexpected content follows the approved plan; possible app footer.');
const planHash = sha(Buffer.from(markdown));
const planVersion = `approved-${planHash.slice(0, 12)}`;
const updates = await readJSON(updatePath, {});
const oldBytes = await exists(xlsxPath) ? await fs.readFile(xlsxPath) : null;
const oldHash = oldBytes ? sha(oldBytes) : null;
const oldJsonBytes = await exists(jsonPath) ? await fs.readFile(jsonPath) : null;
let oldJsonSnapshotId = null;
if (oldJsonBytes) {
  try { oldJsonSnapshotId = JSON.parse(oldJsonBytes.toString('utf8'))?.snapshot?.id ?? null; }
  catch { console.warn('Existing JSON is unreadable and cannot be archived as a matching snapshot. Excel remains the execution-state authority.'); }
}
let previousSnapshot = '';
let priorHandover = {};
let priorRows = {};
if (oldBytes) {
  const old = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
  for (const name of Object.keys(headers)) {
    const values = old.worksheets.getItem(name).getUsedRange().values;
    const hi = name === 'Tasks' ? 1 : 0;
    const actualHeaders = values[hi].slice(0, headers[name].length).map(String);
    assert(json(actualHeaders) === json(headers[name]), `${name}: existing workbook schema differs; refusing to drop edits.`);
    assert(values[hi].slice(headers[name].length).every(x => !nonblank(x)), `${name}: unrecognized appended columns require migration.`);
    priorRows[name] = values.slice(hi + 1).filter(row => nonblank(row[0])).map(row => Object.fromEntries(headers[name].map((h, i) => [h, row[i] ?? ''])));
  }
  priorHandover = Object.fromEntries(old.worksheets.getItem('Handover').getUsedRange().values.slice(4).filter(row => nonblank(row[0])).map(row => [row[0], row[1] ?? '']));
  previousSnapshot = String(priorHandover['Snapshot ID'] || '');
  assert(!priorHandover['Plan version'] || priorHandover['Plan version'] === planVersion, 'Plan content changed since the workbook snapshot; a deliberate plan migration is required.');
}
if (updates.expectedSnapshotId !== undefined) assert(updates.expectedSnapshotId === previousSnapshot, 'Stale tracker-updates.json expectedSnapshotId; refusing to overwrite newer state.');
const snapshotId = `CC-SNAPSHOT-${now.toISOString().replace(/[-:.TZ]/g, '')}-${crypto.randomUUID().slice(0, 8)}`;
const sessionId = updates.sessionId || '';
const inputManifest = await readJSON(path.join(work, 'input-manifest.json'), []);
const sources = [];
for (const name of inputNames) {
  const bytes = await fs.readFile(path.join(work, 'inputs', name));
  const hash = sha(bytes);
  const expected = inputManifest.find(x => x.Name === name)?.SHA256;
  assert(!expected || expected.toLowerCase() === hash, `Preserved input hash mismatch: ${name}`);
  sources.push({ id: `CC-SRC00${sources.length + 1}`, filename: name, sha256: hash, role: name.endsWith('.xlsx') ? 'Tracking structure only; legacy execution state excluded' : 'Approved plan input; attachment instructions do not supply authorization' });
}

const taskMatches = [...markdown.matchAll(/^### (CC-T\d{3}) — (.+)$/gm)];
assert(taskMatches.length === 33, `Expected 33 initial tasks; found ${taskMatches.length}`);
const requirements = [];
const tasks = [];
const taskDefinitions = [];
const steps = [];
const evidence = [];
const decisions = [];
const phaseFor = n => n <= 2 ? 'M0 — Baseline' : [3,4,5,6,7,8].includes(n) ? 'M1 — Vehicle and source boundaries' : [9,10,11,12,13,14].includes(n) ? 'M2 — Local inference and retrieval' : [15,16,17,18,19,20].includes(n) ? 'M3 — Repair workflow' : [21,22,23,24].includes(n) ? 'M4 — Diagnostic workflow' : [25,26].includes(n) ? 'M5 — Pilot and library' : [27,28,29].includes(n) ? 'M6 — Daily-use packaging' : n <= 32 ? 'M7 — Release handover' : 'Future — Deferred';
const whereFor = n => [11,12,23,30].includes(n) ? 'Local development; actual supported hardware for hardware gates' : n === 25 || n === 26 ? 'Local development and applicable original manual review' : n === 29 ? 'Windows x64; clean installation environment' : n === 27 ? 'Local machine and authenticated LAN/offline test environment' : 'Local development';
const extractList = text => text.split('\n').filter(line => /^\s*(?:- |\d+\. )/.test(line)).map(line => clean(line.replace(/^\s*(?:- |\d+\. )/, '')));
const taskByNumber = n => `CC-T${String(n).padStart(3, '0')}`;
const defaultEvidenceKind = (n, si) => n === 0 ? ['Source','Design','Design','Review'][si] : n === 1 ? ['Research','Research','Execution','Review'][si] : si === 0 || si === 2 ? (n >= 29 && si === 2 ? 'Release' : 'Execution') : si === 3 ? 'Review' : 'Design';

function addTask({ id, title, body, implementation, acceptance, dependencies, workClass = 'Engineering', release = 'Initial', suite, explicitSteps = [], inputGate = '', requiredDecisions = [] }) {
  const n = Number(id.slice(-3));
  const taskAnchor = `CC_Workshop_Implementation_Plan.md#${release === 'Future' ? '52-future-work-rows' : anchor(`${id} — ${title}`)}`;
  const reqIds = acceptance.map(text => {
    const requirementId = `CC-R${String(requirements.length + 1).padStart(3, '0')}`;
    requirements.push({ id: requirementId, text, task_ids: [id], release, source: taskAnchor, type: 'acceptance' });
    return requirementId;
  });
  const evidenceIds = [1,2,3,4].map(si => `CC-E${String(n * 4 + si).padStart(3, '0')}`);
  const record = { ...blankRecord('Tasks'), Task: id, Phase: phaseFor(n), 'Task name': title, Where: whereFor(n), Status: n === 0 ? 'In progress' : 'Not started', 'Blocked by': [...dependencies, ...requiredDecisions].join(', ') || 'None', 'Phase gate': `${suite || 'Future activation'}: complete acceptance and review evidence`, 'Notes from plan': implementation.map((v, i) => `${i + 1}. ${v}`).join('\n') + (inputGate ? `\nInput gate: ${inputGate}` : ''), 'Work class': workClass, Release: release, 'Required task IDs': json(dependencies), 'Required decision IDs': json(requiredDecisions), 'Required evidence IDs': json(evidenceIds), 'Requirement IDs': json(reqIds), Priority: n * 10, 'Plan anchor': taskAnchor, 'Definition of done': acceptance.map((v, i) => `${i + 1}. ${v}`).join('\n'), 'Gate state': 'Not evaluated', 'Updated at': now };
  tasks.push(record);
  const definition = { id, title, work_class: workClass, release, phase: record.Phase, priority: record.Priority, dependencies, required_decision_ids: requiredDecisions, suite, implementation, acceptance, input_gate: inputGate, source_markdown: body, plan_anchor: taskAnchor, requirement_ids: reqIds, evidence_ids: evidenceIds, steps: [] };
  const plannedCommand = suite && /^[a-z_]+$/.test(suite) ? `python -m pytest -q tests/acceptance/test_${suite}.py` : n === 0 ? 'Workbook/JSON validation and visual inspection; see CC-T000 acceptance.' : 'Activation is deferred; establish and review the task acceptance suite before implementation.';
  for (let si = 0; si < 4; si++) {
    const stepId = `${id}-S${String(si + 1).padStart(2, '0')}`;
    const description = explicitSteps[si] || [
      `Establish regression and acceptance fixtures for ${title.toLowerCase()}.\n${acceptance.map((v, i) => `${i + 1}. ${v}`).join('\n')}`,
      `Implement ${title.toLowerCase()}.\n${implementation.map((v, i) => `${i + 1}. ${v}`).join('\n')}`,
      `Verify ${title.toLowerCase()} against every acceptance criterion.\n${acceptance.map((v, i) => `${i + 1}. ${v}`).join('\n')}`,
      `Review ${title.toLowerCase()}, reconcile its evidence and handover, and record the commit if one is created.`
    ][si];
    const expected = explicitSteps.length ? `${description}\nTask acceptance:\n${acceptance.join('\n')}` : si === 0 ? `${plannedCommand}\nConfirm the relevant missing or incorrect behavior for the task's acceptance criteria; record the actual failing behavior and command result.` : si === 1 ? 'Implementation covers the task-specific behavior; no claim of verification is made until S03.' : si === 2 ? `${plannedCommand}\nAll applicable acceptance criteria pass; separately record manual-source, hardware or clean-installation observations when required.` : 'Independent review and all required evidence resolve task acceptance; tracker and handover agree. Record only an existing commit.';
    const acceptanceText = explicitSteps.length ? description : si === 0 ? `Fixtures cover these expected behaviors and demonstrate the relevant baseline gap:\n${acceptance.join('\n')}` : si === 1 ? implementation.join('\n') : si === 2 ? acceptance.join('\n') : 'Review findings resolved or explicitly recorded; evidence links valid; tracker consistent; commit field is blank or identifies an actual commit.';
    const expectedOutputs = n === 0 ? [['work/input-manifest.json'], ['outputs/CC_Workshop_Planning_Tracker.xlsx'], ['outputs/CC_Workshop_Implementation_Plan.json'], ['work/tracker-validation.json', 'work/previews/']][si] : si === 0 && suite ? [`tests/acceptance/test_${suite}.py`] : si === 2 || si === 3 ? [`evidence/${id}/${si === 2 ? 'verification' : 'review'}/`] : [];
    const step = { ...blankRecord('Steps'), 'Step ID': stepId, Task: id, Step: si + 1, Description: description, Status: 'Not started', 'Command / expected': expected, Where: record.Where, 'Work class': workClass, Release: release, 'Required step IDs': json(si ? [`${id}-S${String(si).padStart(2, '0')}`] : []), 'Required decision IDs': json(requiredDecisions), 'Required evidence IDs': json([evidenceIds[si]]), 'Acceptance criteria': acceptanceText, Outputs: json(expectedOutputs), 'Plan anchor': taskAnchor, 'Updated at': now };
    steps.push(step);
    definition.steps.push({ id: stepId, ordinal: si + 1, description, expected, acceptance: acceptanceText, dependencies: parseIDs(step['Required step IDs'], stepId), outputs: expectedOutputs, evidence_ids: [evidenceIds[si]] });
    evidence.push({ ...blankRecord('Evidence'), '#': evidenceIds[si], 'Evidence required': `${stepId}: ${clean(explicitSteps[si] || ['Regression fixtures and observed baseline gap', 'Implementation record', 'Acceptance verification', 'Review and handover'][si])}`, Detail: acceptanceText, Where: record.Where, Status: 'Not started', Notes: 'Planned evidence requirement; no result has been observed by this tracker builder.', 'Evidence kind': defaultEvidenceKind(n, si), 'Related task IDs': json([id]), 'Related step IDs': json([stepId]), 'Expected result': expected });
  }
  taskDefinitions.push(definition);
}

for (let i = 0; i < taskMatches.length; i++) {
  const match = taskMatches[i];
  const end = i + 1 < taskMatches.length ? taskMatches[i + 1].index : markdown.indexOf('### 5.2 Future work rows', match.index);
  const body = markdown.slice(match.index, end).trim();
  const preAcceptance = body.split('**Acceptance:**')[0];
  const implementation = extractList((preAcceptance.split('**Implementation:**')[1] || preAcceptance.split('Steps:')[1] || ''));
  const acceptance = extractList(body.split('**Acceptance:**')[1]?.split('**Input gate:**')[0] || '');
  const depText = body.match(/\*\*Dependencies:\*\*([^\n]+)/)?.[1] || '';
  const dependencies = [...depText.matchAll(/CC-T\d{3}/g)].map(x => x[0]);
  const workClass = clean(body.match(/\*\*Class:\*\*([^\n]+)/)?.[1] || 'Engineering');
  const suite = clean(body.match(/\*\*Suite:\*\*([^\n]+)/)?.[1] || '');
  assert(implementation.length && acceptance.length, `${match[1]}: implementation or acceptance did not parse`);
  addTask({ id: match[1], title: match[2], body, implementation, acceptance, dependencies, workClass, suite, explicitSteps: workClass !== 'Engineering' ? implementation : [], inputGate: clean(body.split('**Input gate:**')[1] || '') });
}
const futureBlock = markdown.split('### 5.2 Future work rows')[1].split('## 6.')[0];
for (const line of futureBlock.split('\n').filter(line => /^\| CC-T03[345] /.test(line))) {
  const [id, title, activation, acceptance] = line.split('|').slice(1, -1).map(clean);
  const n = Number(id.slice(-3));
  const decisionId = `CC-D${String(n - 22).padStart(3, '0')}`;
  addTask({ id, title, body: line, implementation: [`Activate only when: ${activation}`, title], acceptance: [acceptance], dependencies: n === 33 ? ['CC-T032'] : n === 35 ? ['CC-T020'] : [], release: 'Future', requiredDecisions: [decisionId], inputGate: activation, suite: '' });
  decisions.push({ ...blankRecord('Decisions'), ID: decisionId, Question: `Activate future work: ${title}`, 'What it blocks': id, Recommendation: `Keep deferred until: ${activation}`, Status: 'Deferred', 'Decision kind': 'User choice', 'Related task IDs': json([id]), 'Source/evidence IDs': '[]', 'Effective when': activation, 'Updated at': now, Authority: 'Source' });
}
assert(tasks.length === 36 && steps.length === 144, 'Expected 36 tasks and 144 steps.');

const decisionBlock = markdown.split('### 1.1 Confirmed product decisions')[1].split('### 1.2')[0];
const decisionTaskMap = { 'CC-D001': [0,1,2,11,29], 'CC-D002': [3,4,17], 'CC-D003': [10,12,30], 'CC-D004': [9,12,27,29], 'CC-D005': [9,11,12,27], 'CC-D006': [2,17,29], 'CC-D007': [3,13,28], 'CC-D008': [8,19,20,35], 'CC-D009': [4,7,25,26,30], 'CC-D010': [0] };
for (const line of decisionBlock.split('\n').filter(line => /^\| CC-D/.test(line))) {
  const [id, answer, authority] = line.split('|').slice(1, -1).map(clean);
  const selected = authority === 'Selected in this conversation';
  decisions.push({ ...blankRecord('Decisions'), ID: id, Question: answer, 'What it blocks': 'Established plan choice; relevant work must remain compatible.', Recommendation: answer, Answer: answer, Status: selected ? 'Answered' : authority.includes('default') ? 'Assumed' : 'Noted', 'Decision kind': selected ? 'User choice' : authority.includes('default') ? 'Engineering default' : 'Source conflict', 'Related task IDs': json((decisionTaskMap[id] || []).map(taskByNumber)), 'Source/evidence IDs': '[]', 'Effective when': 'Approved initial implementation plan', 'Updated at': now, Authority: selected ? 'User session' : authority.includes('default') ? 'Assumption' : 'Source' });
}
decisions.sort((a, b) => a.ID.localeCompare(b.ID));
sources.forEach((source, index) => evidence.push({ ...blankRecord('Evidence'), '#': `CC-E${145 + index}`, 'Evidence required': `Preserved planning input: ${source.filename}`, Detail: source.role, Where: 'Local planning inputs', Status: 'Done', 'Captured where': `work/inputs/${source.filename}`, Notes: 'Builder verified preserved file bytes against the recorded input manifest. This is source provenance, not application execution.', 'Evidence kind': 'Source', 'Related task IDs': '["CC-T000"]', 'Related step IDs': '["CC-T000-S01"]', 'Artifact SHA256': source.sha256, 'Observed at': now, 'Environment / tool version': `Node ${process.version}; SHA-256`, 'Expected result': 'Preserved input bytes match their input-manifest digest.', 'Actual result': 'Digest matches preserved input manifest.', 'Source revision': source.sha256 }));

let rows = { Tasks: tasks, Steps: steps, Decisions: decisions, Evidence: evidence };
const calculated = new Set(['Step total', 'Steps done', 'Steps waived', 'Closed step ratio', 'Verified step ratio', 'Consistency check']);
for (const name of Object.keys(rows)) {
  const idColumn = keys[name];
  const current = new Map(rows[name].map(row => [row[idColumn], row]));
  for (const saved of priorRows[name] || []) {
    const id = String(saved[idColumn]);
    const existing = current.get(id) || blankRecord(name);
    for (const h of headers[name]) if (!calculated.has(h)) existing[h] = saved[h];
    current.set(id, existing);
  }
  const changeSet = updates[name.toLowerCase()] || {};
  const patches = Array.isArray(changeSet) ? changeSet : Object.entries(changeSet).map(([id, fields]) => ({ [idColumn]: id, ...fields }));
  for (const patch of patches) {
    const id = patch[idColumn];
    assert(nonblank(id), `${name}: update missing ${idColumn}`);
    assert(current.has(id) || name === 'Evidence' || name === 'Decisions', `${name}: cannot invent a task/step without a plan migration: ${id}`);
    const record = current.get(id) || blankRecord(name);
    for (const [key, value] of Object.entries(patch)) {
      assert(headers[name].includes(key), `${name}/${id}: unsupported update field ${key}`);
      assert(!calculated.has(key), `${name}/${id}: ${key} is calculated and cannot be edited`);
      record[key] = value;
    }
    if (headers[name].includes('Updated at')) record['Updated at'] = now;
    current.set(id, record);
  }
  rows[name] = [...current.values()];
}
// Normalize both imported serials and current update strings before JSON serialization.
for (const name of Object.keys(rows)) for (const record of rows[name]) {
  for (const field of headers[name]) if (dateFields.has(field)) record[field] = normalizeTimestamp(record[field], `${record[keys[name]]}/${field}`);
}

function validateData() {
  const indexes = {};
  for (const name of Object.keys(rows)) {
    indexes[name] = new Map();
    for (const row of rows[name]) {
      const id = row[keys[name]];
      const pattern = name === 'Tasks' ? /^CC-T\d{3}$/ : name === 'Steps' ? /^CC-T\d{3}-S\d{2}$/ : name === 'Decisions' ? /^CC-D\d{3}$/ : /^CC-E\d{3,}$/;
      assert(pattern.test(id), `${name}: invalid ID ${id}`);
      assert(!indexes[name].has(id), `${name}: duplicate ID ${id}`);
      indexes[name].set(id, row);
      assert((name === 'Decisions' ? decisionStatuses : statuses).includes(row.Status), `${id}: invalid Status ${row.Status}`);
      if (name === 'Tasks' || name === 'Steps') {
        assert(workClasses.includes(row['Work class']) && releases.includes(row.Release), `${id}: invalid Work class/Release`);
      }
      if (name === 'Evidence') assert(evidenceKinds.includes(row['Evidence kind']), `${id}: invalid evidence kind`);
    }
  }
  const links = { Tasks: { 'Required task IDs': 'Tasks', 'Required decision IDs': 'Decisions', 'Required evidence IDs': 'Evidence' }, Steps: { 'Required step IDs': 'Steps', 'Required decision IDs': 'Decisions', 'Required evidence IDs': 'Evidence' }, Decisions: { 'Related task IDs': 'Tasks', 'Source/evidence IDs': 'Evidence' }, Evidence: { 'Related task IDs': 'Tasks', 'Related step IDs': 'Steps' } };
  const reqIndex = new Set(requirements.map(x => x.id));
  for (const name of Object.keys(rows)) for (const row of rows[name]) {
    const id = row[keys[name]];
    for (const [field, target] of Object.entries(links[name])) for (const related of parseIDs(row[field], `${id}/${field}`)) assert(indexes[target].has(related), `${id}: unresolved ${field} ${related}`);
    if (name === 'Tasks') {
      for (const req of parseIDs(row['Requirement IDs'], id)) assert(reqIndex.has(req), `${id}: unknown requirement ${req}`);
      assert(gates.includes(row['Gate state']), `${id}: invalid gate state`);
    }
    if (name === 'Steps') {
      const parent = indexes.Tasks.get(row.Task);
      assert(parent && id.startsWith(`${row.Task}-`), `${id}: invalid parent task`);
      assert(row.Release === parent.Release && row['Work class'] === parent['Work class'], `${id}: class/release differs from parent`);
      parseIDs(row.Outputs, `${id}/Outputs`);
      if (row.Status === 'Done') {
        assert(nonblank(row['Observed result']), `${id}: Done requires an observed result`);
        const required = parseIDs(row['Required evidence IDs'], id);
        assert(required.length && required.every(e => indexes.Evidence.get(e).Status === 'Done'), `${id}: Done requires completed evidence`);
      }
    }
    if (['Skipped', 'N/A'].includes(row.Status) && (name === 'Tasks' || name === 'Steps')) {
      assert(nonblank(row['Your notes'] || row.Notes) && parseIDs(row['Required decision IDs'], id).length > 0, `${id}: waiver requires rationale and a linked decision`);
    }
    if (name === 'Evidence' && row.Status === 'Done') {
      assert(nonblank(row['Actual result']) && nonblank(row['Observed at']), `${id}: completed evidence requires actual result and timestamp`);
      if (['Execution','Release'].includes(row['Evidence kind'])) assert(nonblank(row['Captured where']) && nonblank(row['Environment / tool version']) && nonblank(row['Run ID']), `${id}: execution/release evidence requires artifact, environment and Run ID`);
    }
  }
  for (const [name, field] of [['Tasks','Required task IDs'], ['Steps','Required step IDs']]) {
    const active = new Set(), visited = new Set();
    function visit(id) {
      assert(!active.has(id), `${name}: dependency cycle at ${id}`);
      if (visited.has(id)) return;
      active.add(id);
      for (const dep of parseIDs(indexes[name].get(id)[field], id)) visit(dep);
      active.delete(id); visited.add(id);
    }
    for (const id of indexes[name].keys()) visit(id);
  }
  for (const task of rows.Tasks) {
    const child = rows.Steps.filter(step => step.Task === task.Task);
    if (task.Status === 'Done') {
      assert(child.length && child.every(step => ['Done','Skipped','N/A'].includes(step.Status)), `${task.Task}: Done has unfinished steps`);
      assert(task['Gate state'] === 'Passed', `${task.Task}: Done requires Passed gate`);
      const proofs = parseIDs(task['Required evidence IDs'], task.Task).map(id => indexes.Evidence.get(id));
      assert(proofs.length && proofs.every(proof => proof.Status === 'Done'), `${task.Task}: Done requires its complete evidence set`);
      if (task['Work class'] === 'Engineering') assert(proofs.some(proof => ['Execution','Release'].includes(proof['Evidence kind'])), `${task.Task}: research/design cannot complete engineering work`);
    }
  }
  return indexes;
}
const indexes = validateData();
const terminal = row => ['Done','Skipped','N/A'].includes(row.Status);
const decisionReady = id => ['Answered','N/A'].includes(indexes.Decisions.get(id).Status);
const taskReady = task => task.Release === 'Initial' && !terminal(task) && parseIDs(task['Required task IDs'], task.Task).every(id => terminal(indexes.Tasks.get(id)) && (indexes.Tasks.get(id).Status !== 'Done' || indexes.Tasks.get(id)['Gate state'] === 'Passed')) && parseIDs(task['Required decision IDs'], task.Task).every(decisionReady);
const ready = rows.Tasks.filter(taskReady).sort((a, b) => a.Priority - b.Priority);
const active = rows.Tasks.filter(t => t.Status === 'In progress').sort((a, b) => a.Priority - b.Priority)[0] || ready[0];
const activeStep = active ? rows.Steps.find(s => s.Task === active.Task && !terminal(s) && parseIDs(s['Required step IDs'], s['Step ID']).every(id => terminal(indexes.Steps.get(id)))) : null;
const handover = {
  'Plan version': planVersion, 'Workbook schema version': schemaVersion, 'Snapshot ID': snapshotId, 'Previous snapshot ID': previousSnapshot, 'Last update UTC': now,
  'Repository': 'https://github.com/walladanger/vw-cc-2014-rag', 'Inspected baseline': '646df53b3945e8444877480b3976ca3e8b46007b (static planning inspection; not an execution result)', 'Working branch': '', 'Actual HEAD': '',
  'Current task': active?.Task || '', 'Current step': activeStep?.['Step ID'] || '', 'Last verified execution': 'No application execution recorded in the initial tracker.', 'Last verified evidence IDs': '[]',
  'Ready next tasks': json(ready.map(x => x.Task)), 'Blocked tasks and prerequisites': rows.Tasks.filter(x => x.Status === 'Blocked').map(x => `${x.Task}: ${x['Your notes'] || x['Blocked by']}`).join('\n') || 'No task is explicitly marked Blocked. Dependencies still control readiness.',
  'Unresolved source-review items': 'Confirm actual vehicle configuration and applicable original manuals before CC-T025. Validate corpus provenance, missing warnings/figures and mismatched manuals during ingestion.', 'Hardware profiles actually tested': 'None recorded.', 'Files changed this session': 'outputs/CC_Workshop_Planning_Tracker.xlsx; outputs/CC_Workshop_Implementation_Plan.json', 'Uncommitted and unpublished state': 'Record actual repository state in this field after obtaining a checkout.',
  'Next concrete action': 'Validate the tracker and JSON, inspect all six sheet previews, then complete CC-T000 with observed evidence before application implementation.', 'Expected result': 'Tracker IDs, dependencies, tables, formulas and snapshot agree; no engineering completion is claimed.', 'Stop condition': 'Any invalid identifier, dependency, formula, unverified completion claim, snapshot mismatch or unreadable worksheet.',
  ...priorHandover, ...(updates.handover || {}),
};
Object.assign(handover, { 'Plan version': planVersion, 'Workbook schema version': schemaVersion, 'Snapshot ID': snapshotId, 'Previous snapshot ID': previousSnapshot, 'Last update UTC': now, 'Ready next tasks': json(ready.map(x => x.Task)) });
if (!(updates.handover && Object.hasOwn(updates.handover, 'Current task'))) handover['Current task'] = active?.Task || '';
if (!(updates.handover && Object.hasOwn(updates.handover, 'Current step'))) handover['Current step'] = activeStep?.['Step ID'] || '';

const wb = Workbook.create();
for (const name of sheetNames) wb.worksheets.add(name);
const color = { navy: '#1F3864', paleBlue: '#D9E2F3', yellow: '#FFF2CC', ink: '#1D2939', gray: '#F3F4F6', line: '#D0D5DD' };
const dateValue = value => normalizeTimestamp(value);
const tableWidths = {
  Tasks: [18,27,54,34,16,18,34,48,24,76,62,17,13,34,30,40,40,12,58,76,13,13,14,16,17,18,23,28],
  Steps: [23,18,9,80,16,18,80,34,62,17,13,36,30,34,80,64,58,23,23,23,28,72,30,24],
  Decisions: [17,76,52,76,76,16,17,23,18,46,38,66,20,23,20],
  Evidence: [17,64,80,34,16,70,64,18,35,38,70,23,46,76,13,80,80,52,30,22,20],
};
const editable = { Tasks: [4,5,8,10,25,26], Steps: [4,5,8,17,18,19,20,21,22,23], Decisions: [4,5,6,8,13], Evidence: [4,5,6,10,11,12,13,14,16,17,18,19,20] };
const styleBase = (sheet, range) => { const r = sheet.getRange(range); r.format.font = { name: 'Arial', size: 10, color: color.ink }; r.format.verticalAlignment = 'top'; r.format.wrapText = true; sheet.showGridLines = false; };
const styleHeading = range => { range.format.fill = color.navy; range.format.font = { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }; range.format.rowHeight = 34; range.format.verticalAlignment = 'center'; };
function statusFormat(sheet, address, vocabulary) {
  const range = sheet.getRange(address);
  range.dataValidation = { rule: { type: 'list', values: vocabulary } };
  for (const [value, fill] of [['Blocked','#FEE4E2'], ['In progress','#FEF0C7'], ['Done','#DCFCE7'], ['Deferred','#F2F4F7'], ['Assumed','#FEF0C7']]) {
    if (vocabulary.includes(value)) range.conditionalFormats.add('containsText', { text: value, format: { fill } });
  }
}
for (const name of Object.keys(rows)) {
  const sheet = wb.worksheets.getItem(name);
  const headerRow = name === 'Tasks' ? 2 : 1;
  const dataRow = headerRow + 1;
  const lastRow = headerRow + rows[name].length;
  const lastCol = letters(headers[name].length - 1);
  if (name === 'Tasks') sheet.getRange('A1').values = [['Yellow cells record execution state. Reference fields follow the plan; formula columns recalculate from Steps.']];
  const matrix = [headers[name], ...rows[name].map(row => headers[name].map(h => dateFields.has(h) ? dateValue(row[h]) : row[h] ?? ''))];
  sheet.getRange(`A${headerRow}:${lastCol}${lastRow}`).values = matrix;
  sheet.tables.add(`A${headerRow}:${lastCol}${lastRow}`, true, `tbl${name}`);
  styleBase(sheet, `A1:${lastCol}${lastRow}`);
  styleHeading(sheet.getRange(`A${headerRow}:${lastCol}${headerRow}`));
  for (let ci = 0; ci < headers[name].length; ci++) {
    const col = letters(ci), field = headers[name][ci];
    sheet.getRange(`${col}1:${col}${lastRow}`).format.columnWidth = tableWidths[name][ci];
    if (editable[name].includes(ci)) sheet.getRange(`${col}${dataRow}:${col}${lastRow}`).format.fill = color.yellow;
    if (dateFields.has(field)) sheet.getRange(`${col}${dataRow}:${col}${lastRow}`).setNumberFormat(field === 'Decided on' ? 'yyyy-mm-dd' : 'yyyy-mm-dd hh:mm:ss');
  }
  for (let ri = 0; ri < rows[name].length; ri++) {
    const lineCount = Math.max(...headers[name].map((h, ci) => String(rows[name][ri][h] ?? '').split('\n').reduce((sum, s) => sum + Math.max(1, Math.ceil(s.length / (tableWidths[name][ci] * 0.92))), 0)));
    sheet.getRange(`A${dataRow + ri}:${lastCol}${dataRow + ri}`).format.rowHeight = Math.min(405, Math.max(54, lineCount * 12 + 12));
  }
  const statusCol = name === 'Decisions' ? 'F' : 'E';
  statusFormat(sheet, `${statusCol}${dataRow}:${statusCol}${lastRow}`, name === 'Decisions' ? decisionStatuses : statuses);
  if (name === 'Tasks' || name === 'Steps') {
    for (const [field, allowed] of [['Work class',workClasses], ['Release', releases]]) {
      const col = letters(headers[name].indexOf(field)); sheet.getRange(`${col}${dataRow}:${col}${lastRow}`).dataValidation = { rule: { type: 'list', values: allowed } };
    }
  }
  if (name === 'Tasks') sheet.getRange(`Z${dataRow}:Z${lastRow}`).dataValidation = { rule: { type: 'list', values: gates } };
  if (name === 'Evidence') sheet.getRange(`H${dataRow}:H${lastRow}`).dataValidation = { rule: { type: 'list', values: evidenceKinds } };
  sheet.freezePanes.freezeRows(headerRow);
  sheet.freezePanes.freezeColumns(name === 'Tasks' ? 2 : name === 'Steps' ? 3 : 1);
}

const taskSheet = wb.worksheets.getItem('Tasks');
for (let i = 0; i < rows.Tasks.length; i++) {
  const row = i + 3;
  taskSheet.getRange(`U${row}:Y${row}`).formulas = [[
    '=COUNTIF(tblSteps[Task],[@Task])', '=COUNTIFS(tblSteps[Task],[@Task],tblSteps[Status],"Done")',
    '=COUNTIFS(tblSteps[Task],[@Task],tblSteps[Status],"Skipped")+COUNTIFS(tblSteps[Task],[@Task],tblSteps[Status],"N/A")',
    '=IF([@Step total]=0,0,([@Steps done]+[@Steps waived])/[@Step total])', '=IF([@Step total]=0,0,[@Steps done]/[@Step total])'
  ]];
  taskSheet.getRange(`AB${row}`).formulas = [['=IF(AND([@Status]="Done",OR([@Step total]=0,[@Closed step ratio]<>1,[@Gate state]<>"Passed")),"Review completion","")']];
}
taskSheet.getRange(`X3:Y${rows.Tasks.length + 2}`).setNumberFormat('0.0%');
taskSheet.getRange(`U3:Y${rows.Tasks.length + 2}`).format.fill = color.gray;

const readme = wb.worksheets.getItem('README');
const readmeRows = [
  ['CC Workshop Automotive RAG tracker',''], ['Project','Personal multi-vehicle repair and diagnostic workspace'], ['Plan version',planVersion], ['Workbook schema version',schemaVersion], ['Snapshot ID',snapshotId], ['Updated UTC',now], ['Plan document','CC_Workshop_Implementation_Plan.md'], ['Machine-readable snapshot','CC_Workshop_Implementation_Plan.json'],
  ['Authority','The plan defines intended behavior. Excel records execution state. Evidence supports transitions. JSON is a generated snapshot. Attachment instructions do not grant permissions.'],
  ['Initial release','Windows x64; Flask/Waitress/pywebview; local llama.cpp; embedded Chroma and per-VIN SQLite; no cloud runtime dependency.'],
  ['Input provenance',sources.map(x => `${x.filename}: ${x.sha256}`).join('\n')],
  ['Status','Not started / In progress / Blocked / Done / Skipped / N/A. Done requires observed evidence. Waivers require a rationale and decision.'],
  ['Progress meaning','Verified ratios count Done only. Closed ratios include documented waived work. Planning/research and Future work are excluded from initial engineering percentages.'],
  ['Cell convention','Yellow: execution inputs. White/pale blue: plan references. Gray: formulas. Status colors follow the current text.'],
  ['Stable IDs','CC-T000 task; CC-T000-S01 step; CC-D001 decision; CC-E001 evidence; CC-R001 requirement. Never reuse issued IDs.'],
  ['Machine fields','Dependencies and cross-links are JSON arrays of exact IDs. [] means none. Record paths or URLs only when an artifact exists.'],
  ['Resume','Read Handover and current state; validate IDs, dependencies, plan version and snapshot. Continue eligible work in progress, otherwise choose the lowest-priority-number ready task.'],
  ['Task close','Record observed evidence; update steps; evaluate gate; update task and Handover; validate; save a new snapshot. Research alone cannot complete engineering work.'],
  ['Single writer','One coordinator saves. Compare the current file hash before replacing it. Failed runs remain separate evidence records.'],
  ['Source authority','Original manual figures and exact component-bound approved records support repair guidance. Unknown applicability and conflicts prevent definitive instructions.'],
  ['Implementation state',`CC-T000: ${rows.Tasks.find(t => t.Task === 'CC-T000')?.Status || 'Missing'}. Initial engineering tasks Done: ${rows.Tasks.filter(t => t['Work class'] === 'Engineering' && t.Release === 'Initial' && t.Status === 'Done').length} of ${rows.Tasks.filter(t => t['Work class'] === 'Engineering' && t.Release === 'Initial').length}. Only recorded acceptance evidence justifies completion.`],
  ['Initial engineering progress',''],
];
readme.getRange(`A1:B${readmeRows.length}`).values = readmeRows;
const metrics = [
  ['Initial engineering tasks', '=COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial")'],
  ['Tasks done', '=COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial",tblTasks[Status],"Done")'],
  ['Tasks in progress', '=COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial",tblTasks[Status],"In progress")'],
  ['Tasks blocked', '=COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial",tblTasks[Status],"Blocked")'],
  ['Tasks waived', '=COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial",tblTasks[Status],"Skipped")+COUNTIFS(tblTasks[Work class],"Engineering",tblTasks[Release],"Initial",tblTasks[Status],"N/A")'],
  ['Verified task completion', '=IF(B23=0,0,B24/B23)'],
  ['Initial engineering steps', '=COUNTIFS(tblSteps[Work class],"Engineering",tblSteps[Release],"Initial")'],
  ['Steps done', '=COUNTIFS(tblSteps[Work class],"Engineering",tblSteps[Release],"Initial",tblSteps[Status],"Done")'],
  ['Steps waived', '=COUNTIFS(tblSteps[Work class],"Engineering",tblSteps[Release],"Initial",tblSteps[Status],"Skipped")+COUNTIFS(tblSteps[Work class],"Engineering",tblSteps[Release],"Initial",tblSteps[Status],"N/A")'],
  ['Verified step completion', '=IF(B29=0,0,B30/B29)'],
  ['Planning tasks done', '=COUNTIFS(tblTasks[Work class],"Planning",tblTasks[Release],"Initial",tblTasks[Status],"Done")'],
  ['Research tasks done', '=COUNTIFS(tblTasks[Work class],"Research",tblTasks[Release],"Initial",tblTasks[Status],"Done")'],
  ['Future tasks (excluded)', '=COUNTIF(tblTasks[Release],"Future")'],
  ['Open decisions', '=COUNTIF(tblDecisions[Status],"Open")'],
  ['Assumed decisions', '=COUNTIF(tblDecisions[Status],"Assumed")'],
  ...evidenceKinds.map(kind => [`${kind} evidence done`, `=COUNTIFS(tblEvidence[Evidence kind],"${kind}",tblEvidence[Status],"Done")`]),
];
metrics.forEach(([label, formula], index) => { const row = index + 23; readme.getRange(`A${row}`).values = [[label]]; readme.getRange(`B${row}`).formulas = [[formula]]; });
const readmeLast = 22 + metrics.length;
styleBase(readme, `A1:B${readmeLast}`);
readme.getRange(`A1:A${readmeLast}`).format.columnWidth = 34;
readme.getRange(`B1:B${readmeLast}`).format.columnWidth = 118;
readme.getRange('A1').format.font = { name:'Arial', size:14, bold:true, color:color.navy };
readme.getRange('A1:B1').format.rowHeight = 48;
readme.getRange(`A2:A${readmeLast}`).format.font = { name:'Arial', size:10, bold:true, color:color.ink };
readmeRows.slice(1).forEach((row, i) => readme.getRange(`A${i+2}:B${i+2}`).format.rowHeight = Math.max(26, String(row[1]).split('\n').reduce((n,s) => n+Math.max(1,Math.ceil(s.length/115)),0)*13+10));
readme.getRange(`A23:B${readmeLast}`).format.rowHeight = 24;
readme.getRange(`B23:B${readmeLast}`).format.fill = color.gray;
readme.getRange('B6').setNumberFormat('yyyy-mm-dd hh:mm:ss');
readme.getRange('B28').setNumberFormat('0.0%'); readme.getRange('B32').setNumberFormat('0.0%');
styleHeading(readme.getRange('A22:B22'));

const hand = wb.worksheets.getItem('Handover');
const handRows = [['CC Workshop handover',''], ['Continue from verified tracker state.',''], ['',''], ['Item','Current value'], ...Object.entries(handover).map(([k,v]) => [k, k === 'Last update UTC' ? dateValue(v) : v])];
hand.getRange(`A1:B${handRows.length}`).values = handRows;
styleBase(hand, `A1:B${handRows.length}`);
hand.getRange(`A1:A${handRows.length}`).format.columnWidth = 35;
hand.getRange(`B1:B${handRows.length}`).format.columnWidth = 116;
hand.getRange('A1').format.font = { name:'Arial',size:14,bold:true,color:color.navy };
styleHeading(hand.getRange('A4:B4'));
hand.getRange(`A5:A${handRows.length}`).format.fill = color.paleBlue;
hand.getRange(`B5:B${handRows.length}`).format.fill = color.yellow;
handRows.forEach((row,i) => { if(i!==3) hand.getRange(`A${i+1}:B${i+1}`).format.rowHeight = Math.max(26, String(row[1]).split('\n').reduce((n,s)=>n+Math.max(1,Math.ceil(s.length/112)),0)*13+12); });
const updateRow = handRows.findIndex(row => row[0] === 'Last update UTC') + 1;
hand.getRange(`B${updateRow}`).setNumberFormat('yyyy-mm-dd hh:mm:ss');
hand.freezePanes.freezeRows(4);

const expectedEngineering = rows.Tasks.filter(t => t['Work class'] === 'Engineering' && t.Release === 'Initial');
const expectedSteps = rows.Steps.filter(s => s['Work class'] === 'Engineering' && s.Release === 'Initial');
const progress = { initial_engineering_tasks: expectedEngineering.length, engineering_tasks_done: expectedEngineering.filter(t => t.Status === 'Done').length, initial_engineering_steps: expectedSteps.length, engineering_steps_done: expectedSteps.filter(t => t.Status === 'Done').length, future_tasks: rows.Tasks.filter(t => t.Release === 'Future').length, total_tasks: rows.Tasks.length, total_steps: rows.Steps.length };
const computedCounts = readme.getRange('B23:B35').values.map(row => row[0]);
assert(computedCounts[0] === progress.initial_engineering_tasks, `Task formula mismatch: ${computedCounts[0]} != ${progress.initial_engineering_tasks}`);
assert(computedCounts[1] === progress.engineering_tasks_done, 'Done task formula mismatch');
assert(computedCounts[6] === progress.initial_engineering_steps, 'Step total formula mismatch');
assert(computedCounts[7] === progress.engineering_steps_done, 'Done step formula mismatch');
assert(computedCounts[12] === progress.future_tasks, 'Future count formula mismatch');
for (let i = 0; i < rows.Tasks.length; i++) {
  const values = taskSheet.getRange(`U${i+3}:Y${i+3}`).values[0];
  const children = rows.Steps.filter(s => s.Task === rows.Tasks[i].Task);
  assert(values[0] === children.length && values[1] === children.filter(s=>s.Status==='Done').length, `${rows.Tasks[i].Task}: child count formula mismatch`);
}
const formulaErrorPattern = /#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A\b|NUM!|NULL!|SPILL!|CALC!)/;
for (const name of sheetNames) {
  const values = wb.worksheets.getItem(name).getUsedRange().values;
  for (let ri=0;ri<values.length;ri++) for(let ci=0;ci<values[ri].length;ci++) assert(!formulaErrorPattern.test(String(values[ri][ci] ?? '')), `${name}!${letters(ci)}${ri+1}: formula error`);
}
console.log((await wb.inspect({ kind: 'table', range: 'README!A23:B38', include: 'values,formulas', tableMaxRows:16, tableMaxCols:2, maxChars:5000 })).ndjson);
console.log((await wb.inspect({ kind:'match', searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options:{useRegex:true,maxResults:50}, summary:'final formula error scan', maxChars:1500 })).ndjson);

const renderRanges = { README: 'A1:B22', Handover: 'A1:B17', Tasks: 'A1:F7', Steps: 'A1:F5', Decisions: 'A1:C6', Evidence: 'A1:E5' };
for (const name of sheetNames) {
  const preview = await wb.render({ sheetName:name, range:renderRanges[name], scale:1, format:'png' });
  await fs.writeFile(path.join(previews, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const progressPreview = await wb.render({ sheetName:'README', range:`A22:B${readmeLast}`, scale:1, format:'png' });
await fs.writeFile(path.join(previews, 'README-progress.png'), new Uint8Array(await progressPreview.arrayBuffer()));

const evidenceReferenceReview = [];
for (const record of rows.Evidence.filter(row => nonblank(row['Captured where']))) {
  const capture = String(record['Captured where']).trim();
  const review = { evidence_id:record['#'], captured_where:capture, expected_sha256:record['Artifact SHA256'] || null, superseded_by:rows.Evidence.filter(row => row['Supersedes ID'] === record['#']).map(row => row['#']) };
  if (/^https?:\/\//i.test(capture)) review.result = 'Remote reference recorded; not fetched by workbook authoring';
  else {
    const capturePath = path.resolve(root, capture);
    try {
      const stat = await fs.stat(capturePath);
      if (!stat.isFile()) review.result = 'Capture exists but is not a file; no content hash checked';
      else {
        review.actual_sha256 = sha(await fs.readFile(capturePath));
        review.result = !nonblank(record['Artifact SHA256']) ? 'Capture exists; no recorded hash' : review.actual_sha256 === String(record['Artifact SHA256']).toLowerCase() ? 'Capture hash matches' : 'Capture hash differs from recorded historical hash';
      }
      if ([xlsxPath,jsonPath].includes(capturePath)) review.note = 'This mutable output is replaced by the new snapshot. Use an immutable checkpoint for durable execution evidence.';
    } catch (error) { review.result = `Capture unavailable: ${error.code || error.message}`; }
  }
  evidenceReferenceReview.push(review);
}
// Report historical evidence mismatches without deleting or rejecting superseded records.
await fs.writeFile(path.join(work,'evidence-reference-review.json'), JSON.stringify({snapshot_id:snapshotId,records:evidenceReferenceReview},null,2)+'\n');
const snapshot = { id:snapshotId, previous_id:previousSnapshot || null, schema_version:schemaVersion, plan_version:planVersion, plan_sha256:planHash, updated_at:now.toISOString(), session_id:sessionId || null, authority:'Excel is the execution-state authority; JSON is a generated snapshot.', source_workbook_sha256:originalHash, progress, handover };
const machine = { schema_version:schemaVersion, snapshot, plan_markdown:markdown, sources, requirements, decisions:rows.Decisions, tasks:taskDefinitions.map(def => ({...def, state: rows.Tasks.find(t=>t.Task===def.id)})), steps:rows.Steps, evidence:rows.Evidence, workbook_tables:rows, validation:{status:'passed', checks:['six exact tabs','approved leading and appended headers','36 planned tasks and 144 planned steps','unique IDs','resolved JSON dependencies','acyclic task and step dependencies','class and release alignment','evidence-backed completion','initial/future formula denominators','independently reconciled formula totals','no formula errors','original input hashes preserved','UTC timestamp normalization'], evidence_reference_review:evidenceReferenceReview, visual_review:'Six worksheet previews generated; coordinator must inspect before completing CC-T000.'} };
const serialized = JSON.stringify(machine, (_key, value) => value instanceof Date ? value.toISOString() : value, 2) + '\n';
assert(JSON.parse(serialized).snapshot.id === snapshotId, 'JSON snapshot serialization failed');
assert(sha(await fs.readFile(originalPath)) === originalHash, 'Original preserved workbook unexpectedly changed');
const outputBlob = await SpreadsheetFile.exportXlsx(wb);
const tempXlsx = path.join(work, 'tracker-pending.xlsx');
const tempJson = path.join(work, 'tracker-pending.json');
await outputBlob.save(tempXlsx);
await fs.writeFile(tempJson, serialized, 'utf8');
assert((await exists(xlsxPath) ? sha(await fs.readFile(xlsxPath)) : null) === oldHash, 'Workbook changed during build; pending outputs retained, existing state not overwritten');
if (oldBytes) {
  const archiveDir = path.join(work,'tracker-snapshots');
  const archiveId = /^[A-Za-z0-9_.-]+$/.test(previousSnapshot) ? previousSnapshot : oldHash;
  await fs.mkdir(archiveDir,{recursive:true});
  await fs.writeFile(path.join(archiveDir,`${archiveId}.xlsx`),oldBytes);
  if (oldJsonBytes && oldJsonSnapshotId === previousSnapshot) await fs.writeFile(path.join(archiveDir,`${archiveId}.json`),oldJsonBytes);
  else if (oldJsonBytes) console.warn('Prior JSON snapshot does not match the prior workbook and was not archived as a pair.');
}
await fs.rename(tempXlsx, xlsxPath);
await fs.rename(tempJson, jsonPath);
const validation = { snapshot_id:snapshotId, previous_snapshot_id:previousSnapshot || null, workbook_sha256:sha(await fs.readFile(xlsxPath)), json_sha256:sha(await fs.readFile(jsonPath)), original_workbook_sha256:originalHash, plan_sha256:planHash, task_count:rows.Tasks.length, step_count:rows.Steps.length, decision_count:rows.Decisions.length, evidence_count:rows.Evidence.length, requirement_count:requirements.length, progress, formula_count: rows.Tasks.length*6+metrics.length, status:'passed', visual_review:'pending coordinator inspection' };
await fs.writeFile(path.join(work,'tracker-validation.json'), JSON.stringify(validation,null,2)+'\n');
console.log(JSON.stringify(validation,null,2));
console.log(`Saved ${xlsxPath}\nSaved ${jsonPath}\nPreviews: ${previews}`);
