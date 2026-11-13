/**
 * The tool surface.
 *
 * Four small verbs: make one from a picture, switch to one that already
 * exists, go back, and look at the current state. `cursor_from_image` applies
 * by default because "make this my pointer" is the whole point; passing
 * `apply: false` previews without touching the live scheme.
 */
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Every definition is bound to one agent so the tool can find its pictures. */
export function createTools(agent, ctx, deps) {
  const { maker, store } = deps;
  return [
    {
      name: 'cursor_from_image',
      description:
        'Build a complete 16-role Windows mouse-cursor scheme from one picture and, unless apply is false, ' +
        'switch the live pointer to it. Only call this after the user agreed to change their pointer.',
      parameters: {
        type: 'object',
        properties: {
          image: {
            type: 'string',
            description: 'Absolute path of the picture. Omit to use the newest picture the user sent.',
          },
          name: {
            type: 'string',
            description: 'Short label for the generated scheme, e.g. the character name.',
          },
          accent: {
            type: 'string',
            description: 'Hex colour (for example #6f8cff) for the accent glyphs, overriding the colour sampled from the picture.',
          },
          apply: {
            type: 'boolean',
            description: 'Install and switch to the new scheme right away. Defaults to true.',
          },
        },
        additionalProperties: false,
      },
      output: { schema: { type: 'object' }, render: renderValue },
      execute: async (args) => {
        const resolved = await resolveImage(agent, args, ctx, store);
        if (resolved.error) return { status: 'error', error: resolved.error };
        store.clear(agent);
        return maker.build(resolved.path, {
          label: typeof args.name === 'string' ? args.name : undefined,
          accent: typeof args.accent === 'string' ? args.accent : undefined,
          apply: args.apply !== false,
        });
      },
    },
    {
      name: 'cursor_apply',
      description: 'Switch the live pointer to a cursor set this plugin generated earlier.',
      parameters: {
        type: 'object',
        properties: {
          id: {
            type: 'string',
            description: 'Set id from cursor_status. Omit to re-apply the set that was used most recently.',
          },
        },
        additionalProperties: false,
      },
      output: { schema: { type: 'object' }, render: renderValue },
      execute: async (args) => maker.applyById(typeof args.id === 'string' ? args.id : undefined),
    },
    {
      name: 'cursor_restore',
      description: 'Put back the pointer the user had before this plugin first replaced it.',
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: { schema: { type: 'object' }, render: renderValue },
      execute: async () => maker.restore(),
    },
    {
      name: 'cursor_status',
      description:
        'Report the live cursor scheme, every generated set (with ids), and whether the picture pipeline can run.',
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: { schema: { type: 'object' }, render: renderValue },
      execute: async () => maker.status(),
    },
  ];
}

/** Model-facing rendering: compact JSON keeps every field the model may need. */
function renderValue(_args, value) {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }];
}

/** Where the picture lives, or why there is no picture to work from. */
async function resolveImage(agent, args, ctx, store) {
  const named = typeof args?.image === 'string' ? args.image.trim() : '';
  if (named !== '') {
    const absolute = path.resolve(named);
    if (!existsSync(absolute)) {
      return { error: { code: 'IMAGE_NOT_FOUND', message: `there is no file at ${absolute}` } };
    }
    return { path: absolute };
  }

  const last = store.last(agent);
  if (last === undefined) {
    return {
      error: {
        code: 'NO_IMAGE',
        message: 'The user has not sent a picture in this conversation; pass the image path explicitly.',
      },
    };
  }
  if (last.path && existsSync(last.path)) return { path: last.path };

  if (last.ref !== null) {
    try {
      let host = ctx.attachments?.imageHostPath?.(last.ref);
      if (host !== undefined && typeof host.then === 'function') host = await host;
      if (typeof host === 'string' && host !== '' && existsSync(host)) return { path: host };
    } catch {
      // Fall through to the inline copy.
    }
  }
  if (typeof last.inline === 'string' && last.inline !== '') {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'dsh-cursor-image-'));
    const file = path.join(dir, `input.${extensionFor(last.mediaType)}`);
    writeFileSync(file, Buffer.from(last.inline, 'base64'));
    return { path: file };
  }
  return {
    error: {
      code: 'NO_IMAGE_PATH',
      message: 'The picture is in the message but has no readable file yet; ask the user to send it again or pass a path.',
    },
  };
}

function extensionFor(mediaType) {
  const map = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'image/bmp': 'bmp' };
  return map[String(mediaType).toLowerCase()] ?? 'png';
}