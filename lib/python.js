/**
 * Locating and driving the Python rasteriser.
 *
 * The heavy lifting lives in `assets/build_cursors.py` because alpha
 * compositing, 8x supersampling and RIFF/ACON serialisation are far less
 * error-prone with Pillow + numpy than with hand-rolled Node buffers. The
 * script is deliberately self-contained: one file, two well-known imports.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PROBE = 'import sys, PIL, numpy; sys.stdout.write("ok")';

/** Candidate interpreters, most specific first. */
function candidates(config) {
  const list = [];
  if (typeof config?.pythonPath === 'string' && config.pythonPath.trim() !== '') {
    list.push(config.pythonPath.trim());
  }
  if (typeof process.env.DSH_CURSOR_PYTHON === 'string' && process.env.DSH_CURSOR_PYTHON !== '') {
    list.push(process.env.DSH_CURSOR_PYTHON);
  }
  for (const root of runtimeRoots()) {
    for (const name of ['python.exe', 'python3.exe', 'python']) {
      const candidate = path.join(root, name);
      if (existsSync(candidate)) list.push(candidate);
    }
  }
  return list;
}

/** Every `<dsh home>/dsh-runtimes/*​/dependencies/python` directory on this machine. */
function runtimeRoots() {
  const homes = [];
  if (process.env.DSH_HOME) homes.push(process.env.DSH_HOME);
  homes.push(path.join(os.homedir(), '.dsh'));
  const roots = [];
  for (const home of homes) {
    const base = path.join(home, 'dsh-runtimes');
    if (!existsSync(base)) continue;
    let entries;
    try {
      entries = readdirSync(base, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      roots.push(path.join(base, entry.name, 'dependencies', 'python'));
      roots.push(path.join(base, entry.name, 'dependencies', 'python', 'bin'));
    }
  }
  return roots;
}

/**
 * Pick an interpreter that can actually import Pillow and numpy.
 * @returns `{ python }` on success, `{ error }` when nothing usable exists.
 */
export function resolvePython(config) {
  const tried = [];
  for (const python of candidates(config)) {
    tried.push(python);
    try {
      const out = execFileSync(python, ['-c', PROBE], {
        encoding: 'utf8',
        timeout: 20000,
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      });
      if (String(out).trim() === 'ok') return { python };
    } catch {
      // Try the next candidate.
    }
  }
  return {
    error: {
      code: 'NO_PYTHON',
      message:
        'No Python with Pillow and numpy was found. Set pythonPath in the plugin configuration, ' +
        'or DSH_CURSOR_PYTHON in the environment.',
      tried,
    },
  };
}

/**
 * Run the rasteriser.
 * @param python - interpreter path from `resolvePython`.
 * @param options - `{ image, out, template, accent, label }`.
 * @returns `{ ok: true, meta }` or `{ ok: false, error }`.
 */
export function buildCursors(python, options) {
  const script = path.join(scriptRoot(), 'build_cursors.py');
  if (!existsSync(script)) {
    return { ok: false, error: { code: 'NO_SCRIPT', message: `bundled rasteriser is missing: ${script}` } };
  }
  const args = [script, '--image', options.image, '--out', options.out, '--template', options.template];
  if (options.accent) args.push('--accent', options.accent);
  if (options.label) args.push('--label', options.label);

  try {
    execFileSync(python, args, {
      encoding: 'utf8',
      timeout: 180000,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
  } catch (error) {
    const tail = String(error?.stderr ?? '').trim().split('\n').slice(-4).join(' ');
    return {
      ok: false,
      error: { code: 'BUILD_FAILED', message: `rasteriser failed: ${tail || error?.message || 'unknown error'}` },
    };
  }

  const metaPath = path.join(options.out, 'meta.json');
  if (!existsSync(metaPath)) {
    return { ok: false, error: { code: 'NO_META', message: 'rasteriser produced no meta.json' } };
  }
  try {
    const meta = JSON.parse(readFileSync(metaPath, 'utf8'));
    return { ok: true, meta };
  } catch (error) {
    return { ok: false, error: { code: 'BAD_META', message: `cannot read meta.json: ${error?.message}` } };
  }
}

/** `assets/` sits next to `lib/`. */
export function scriptRoot() {
  // fileURLToPath, not url.pathname: the profile lives under a Chinese user
  // name, and pathname would hand back percent-encoded UTF-8.
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.join(path.dirname(here), 'assets');
}

/** The folder holding the twelve glyph roles that ship with the plugin. */
export function templateRoot() {
  return path.join(scriptRoot(), 'template');
}