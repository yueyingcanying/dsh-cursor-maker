/**
 * Entry point of the `dsh-cursor-maker` bundle.
 *
 * Three moving parts, mounted once:
 *   1. an inbox listener that remembers the picture the user just sent;
 *   2. a prompt section that asks the model to offer a cursor replacement;
 *   3. four tools, registered per agent so each one sees its own pictures.
 *
 * Every step is wrapped so a missing service or an odd message can never stop
 * the harness from booting.
 */
import { ImageStore } from './store.js';
import { CursorMaker } from './maker.js';
import { createTools } from './tools.js';
import { promptFor } from './prompt.js';

export const name = 'dsh-cursor-maker';

const SECTION = 'dsh-cursor-maker:offer';
const ORDER = 3310;

export function apply(root, config) {
  try {
    mount(root, normalize(config));
  } catch (error) {
    log(root, 'error', `cursor maker did not start: ${message(error)}`);
  }
}

function mount(root, options) {
  if (!options.enabled) return;

  const store = new ImageStore();
  const maker = new CursorMaker(options, root);

  // `global: true` is what makes the root scope hear an event an agent
  // dispatched on its own scope; the payload then carries `agent`.
  root.on(
    'agent/inbox/claimed',
    (payload) => {
      try {
        const { agent, message: claimed } = payload ?? {};
        if (agent === undefined || claimed === undefined) return;
        store.record(agent, claimed, (part) => hostPath(root, part));
      } catch (error) {
        log(root, 'debug', `could not record a picture: ${message(error)}`);
      }
    },
    { global: true },
  );

  mountTools(root, { maker, store });
}

/** Register the four tools against every agent, now and in the future. */
function mountTools(root, deps) {
  root.inject(['tools'], (ctx) => {
    const entries = new Map();
    let stopped = false;

    const attach = async (agent) => {
      if (stopped || agent === undefined || entries.has(agent)) return;
      const entry = { fiber: undefined, disposers: [], section: undefined };
      entries.set(agent, entry);
      try {
        entry.fiber = agent.ctx.plugin({
          // The section and the tools live on the agent's own scope, exactly
          // like dsh-ops does, so both vanish with the agent instead of
          // leaking into a scope that no longer has an inbox.
          inject: ['tools', 'systemPrompt'],
          apply(scoped) {
            entry.section = scoped.systemPrompt.section({
              name: SECTION,
              order: ORDER,
              interpolate: false,
              text: (context) => {
                // A throwing section is fatal to the whole prompt assembly — and
                // the harness calls that assembly while resolving tool
                // availability, so one bad section can make every tool look
                // broken. Swallow anything unexpected and stay silent instead.
                if (context?.scope !== agent) return '';
                try {
                  return promptFor(agent, deps.store);
                } catch (error) {
                  log(root, 'debug', `cursor prompt failed: ${message(error)}`);
                  return '';
                }
              },
            });
            for (const definition of createTools(agent, scoped, deps)) {
              entry.disposers.push(scoped.tools.register(definition));
            }
          },
        });
        await entry.fiber;
      } catch (error) {
        entries.delete(agent);
        log(root, 'warn', `could not publish cursor tools: ${message(error)}`);
      }
    };

    const detach = async (agent) => {
      const entry = entries.get(agent);
      if (entry === undefined) return;
      entries.delete(agent);
      try {
        entry.section?.();
      } catch {
        // The section may already be gone with the scope.
      }
      for (const dispose of entry.disposers) {
        try {
          dispose?.();
        } catch {
          // A tool that already went away needs no cleanup.
        }
      }
      try {
        await entry.fiber?.dispose?.();
      } catch {
        // Ignore teardown races; the agent is going away either way.
      }
    };

    ctx.on('agent/created', ({ agent }) => {
      void attach(agent);
    });
    ctx.on('agent/disposed', ({ agent }) => {
      void detach(agent);
    });
    ctx.effect(
      () => () => {
        stopped = true;
        for (const agent of [...entries.keys()]) void detach(agent);
      },
      'dsh-cursor-maker: tools',
    );

    for (const agent of ctx.get('agents')?.list?.() ?? []) void attach(agent);
  });
}

/** Host path of an image part, when the attachment store can name one. */
function hostPath(ctx, part) {
  if (part?.attachment === undefined) return undefined;
  const host = ctx.attachments?.imageHostPath?.(part.attachment);
  return typeof host === 'string' && host !== '' ? host : undefined;
}

function normalize(config) {
  const value = config !== null && typeof config === 'object' ? config : {};
  return {
    enabled: value.enabled !== false,
    pythonPath: typeof value.pythonPath === 'string' ? value.pythonPath : '',
    dataDir: typeof value.dataDir === 'string' ? value.dataDir : '',
  };
}

function message(error) {
  return error instanceof Error ? error.message : String(error);
}

function log(ctx, level, text) {
  try {
    const logger = ctx?.logger;
    if (logger !== undefined && typeof logger[level] === 'function') logger[level](text);
  } catch {
    // Logging must never be the thing that breaks startup.
  }
}