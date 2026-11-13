/**
 * What the four cursor tools actually do.
 *
 * A "set" is one folder holding the sixteen roles plus the preview and a
 * meta.json that records how the picture was cropped. Sets are never deleted,
 * so switching back to an older look is just another apply.
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { buildCursors, resolvePython, templateRoot } from './python.js';
import { ROLE_FILES, SCHEME_PREFIX, registry, valuesFor } from './registry.js';

/** Everything the tools need, resolved once per plugin instance. */
export class CursorMaker {
  constructor(options, logger) {
    this.options = options;
    this.log = logger;
    this.root = options.dataDir && options.dataDir.trim() !== '' ? options.dataDir.trim() : defaultRoot();
    this.setsDir = path.join(this.root, 'sets');
    this.backupPath = path.join(this.root, 'backup.json');
    this.currentPath = path.join(this.root, 'current.json');
  }

  ensureDirs() {
    mkdirSync(this.setsDir, { recursive: true });
  }

  /** Build a set from a picture and, by default, switch the pointer to it. */
  build(imagePath, { label, accent, apply }) {
    this.ensureDirs();
    const python = resolvePython(this.options);
    if (python.error) return { status: 'error', error: python.error };

    const id = `${stamp()}-${slug(label || path.basename(imagePath, path.extname(imagePath)) || 'cursor')}`;
    const out = path.join(this.setsDir, id);
    mkdirSync(out, { recursive: true });

    const built = buildCursors(python.python, {
      image: imagePath,
      out,
      template: templateRoot(),
      accent,
      label: label || 'Picture',
    });
    if (!built.ok) return { status: 'error', error: built.error };

    const record = {
      id,
      dir: out,
      label: label || path.basename(imagePath, path.extname(imagePath)),
      created: new Date().toISOString(),
      source: imagePath,
      accent: built.meta.accent,
      preview: existsSync(path.join(out, 'preview.png')) ? path.join(out, 'preview.png') : undefined,
    };
    writeFileSync(path.join(out, 'set.json'), JSON.stringify(record, null, 2), 'utf8');

    if (apply === false) return { status: 'ok', built: record, applied: false };

    const applied = this.apply(out, `DSH Cursor ${record.label}`);
    if (applied.status === 'error') return applied;
    return { status: 'ok', built: record, applied: true, scheme: applied.scheme, backup: applied.backup };
  }

  /** Point the live scheme at every role in one folder. */
  apply(dir, schemeName) {
    const mapped = valuesFor(dir);
    if (mapped.error) return { status: 'error', error: { code: 'INCOMPLETE_SET', message: mapped.error } };
    const result = registry('apply', {
      name: schemeName,
      values: mapped.values,
      backup: this.backupPath,
    });
    if (!result.ok) return { status: 'error', error: { code: 'REGISTRY', message: result.error } };
    const record = { scheme: schemeName, dir, at: new Date().toISOString() };
    writeFileSync(this.currentPath, JSON.stringify(record, null, 2), 'utf8');
    return {
      status: 'ok',
      scheme: result.scheme,
      arrow: result.values?.Arrow,
      backup: existsSync(this.backupPath) ? this.backupPath : undefined,
    };
  }

  /** Put the pointer that was live before the first install back. */
  restore() {
    const result = registry('restore', { backup: this.backupPath });
    if (!result.ok) return { status: 'error', error: { code: 'REGISTRY', message: result.error } };
    return { status: 'ok', scheme: result.scheme, arrow: result.values?.Arrow };
  }

  /** Live scheme, every generated set, and whether the rasteriser can run. */
  status() {
    const live = registry('status', { backup: this.backupPath });
    const sets = [];
    if (existsSync(this.setsDir)) {
      for (const entry of readdirSync(this.setsDir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const dir = path.join(this.setsDir, entry.name);
        const record = readJson(path.join(dir, 'set.json')) ?? { id: entry.name, dir };
        const complete = Object.values(ROLE_FILES).every((file) => existsSync(path.join(dir, file)));
        sets.push({ ...record, complete });
      }
    }
    sets.sort((a, b) => String(b.created ?? '').localeCompare(String(a.created ?? '')));

    const active = readJson(this.currentPath);
    const python = resolvePython(this.options);
    return {
      status: 'ok',
      scheme: live.ok ? live.scheme : `unavailable: ${live.error}`,
      liveArrow: live.ok ? live.values?.Arrow : undefined,
      backup: existsSync(this.backupPath) ? this.backupPath : undefined,
      active: active?.scheme ?? null,
      dataDir: this.root,
      python: python.error ? { ok: false, message: python.error.message } : { ok: true, path: python.python },
      sets,
    };
  }

  /** Resolve a set id (or the active one) to its folder. */
  setDir(id) {
    if (id && id.trim() !== '') {
      const direct = path.join(this.setsDir, id.trim());
      return existsSync(direct) ? direct : undefined;
    }
    const active = readJson(this.currentPath);
    if (active?.dir && existsSync(active.dir)) return active.dir;
    const dirs = existsSync(this.setsDir)
      ? readdirSync(this.setsDir, { withFileTypes: true }).filter((d) => d.isDirectory())
      : [];
    return dirs.length === 0 ? undefined : path.join(this.setsDir, dirs[dirs.length - 1].name);
  }

  applyById(id) {
    const dir = this.setDir(id);
    if (dir === undefined) return { status: 'error', error: { code: 'NO_SET', message: 'no generated cursor set matches that id' } };
    const record = readJson(path.join(dir, 'set.json'));
    return this.apply(dir, `DSH Cursor ${record?.label ?? path.basename(dir)}`);
  }
}

/** `%LOCALAPPDATA%\DshCursorMaker`, or a home-relative folder off Windows. */
function defaultRoot() {
  const local = process.env.LOCALAPPDATA;
  if (local) return path.join(local, 'DshCursorMaker');
  return path.join(os.homedir(), 'DshCursorMaker');
}

function readJson(file) {
  try {
    if (!existsSync(file)) return undefined;
    return JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  } catch {
    return undefined;
  }
}

function stamp() {
  const d = new Date();
  const pad = (v) => String(v).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

/** A folder-safe token from a user-supplied label. */
function slug(text) {
  const cleaned = String(text)
    .normalize('NFKD')
    .replace(/[^\p{L}\p{N}._-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return cleaned === '' ? 'cursor' : cleaned;
}

export { SCHEME_PREFIX, copyFileSync };