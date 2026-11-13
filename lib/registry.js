/**
 * Reading and writing `HKCU\Control Panel\Cursors`.
 *
 * The registry work happens in `assets/registry.ps1` and communicates through
 * UTF-8 files: a Chinese Windows profile turns console output into mojibake,
 * while a JSON file round-trips every path exactly as written.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { scriptRoot } from './python.js';

/** Role key in the registry -> file name inside a generated set. */
export const ROLE_FILES = {
  Arrow: 'arrow.cur',
  Help: 'help.cur',
  AppStarting: 'appstarting.ani',
  Wait: 'busy.ani',
  Crosshair: 'cross.cur',
  IBeam: 'ibeam.cur',
  NWPen: 'pen.cur',
  No: 'no.cur',
  SizeNS: 'sizens.cur',
  SizeWE: 'sizewe.cur',
  SizeNWSE: 'sizenwse.cur',
  SizeNESW: 'sizenesw.cur',
  SizeAll: 'sizeall.cur',
  UpArrow: 'uparrow.cur',
  Hand: 'hand.cur',
  Pin: 'pin.cur',
};

/** Scheme names this plugin owns; anything else is worth backing up. */
export const SCHEME_PREFIX = 'DSH Cursor';

/** absolute path of the PowerShell host that ships with Windows. */
function powershell() {
  const root = process.env.SystemRoot || 'C:\\Windows';
  const full = path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  return existsSync(full) ? full : 'powershell.exe';
}

/**
 * Run one registry action.
 * @param action - `"status" | "apply" | "restore"`.
 * @param payload - extra fields merged into the command file.
 * @returns `{ ok: true, ... }` or `{ ok: false, error }`.
 */
export function registry(action, payload = {}) {
  const script = path.join(scriptRoot(), 'registry.ps1');
  if (!existsSync(script)) {
    return { ok: false, error: `registry helper is missing: ${script}` };
  }
  const dir = mkdtempSync(path.join(os.tmpdir(), 'dsh-cursor-'));
  const specPath = path.join(dir, 'cmd.json');
  const resultPath = path.join(dir, 'result.json');
  try {
    writeFileSync(specPath, JSON.stringify({ action, result: resultPath, ...payload }), 'utf8');
    execFileSync(
      powershell(),
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-Spec', specPath],
      { encoding: 'utf8', timeout: 60000, windowsHide: true },
    );
    if (!existsSync(resultPath)) return { ok: false, error: 'registry helper returned no result' };
    const text = readFileSync(resultPath, 'utf8').replace(/^\uFEFF/, '');
    return JSON.parse(text);
  } catch (error) {
    return { ok: false, error: String(error?.stderr || error?.message || error) };
  } finally {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // A leftover temp folder is harmless.
    }
  }
}

/**
 * Map a generated set directory to registry values.
 * @param dir - folder holding the sixteen files.
 * @returns role -> absolute path, or an error when a role is missing.
 */
export function valuesFor(dir) {
  const missing = [];
  const values = {};
  for (const [role, file] of Object.entries(ROLE_FILES)) {
    const full = path.join(dir, file);
    if (!existsSync(full)) {
      missing.push(file);
      continue;
    }
    values[role] = full;
  }
  if (missing.length > 0) return { error: `cursor set is incomplete, missing: ${missing.join(', ')}` };
  return { values };
}