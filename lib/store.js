/**
 * Per-agent memory of the pictures the user just sent.
 *
 * The plugin only ever needs the newest batch: a cursor is built from one
 * picture, and re-offering an old one a turn later is noise. Keeping the map
 * weak means an agent that goes away takes its pictures with it.
 */

/** How many images of one message are worth remembering. */
const BATCH_LIMIT = 6;

export class ImageStore {
  constructor() {
    this.byAgent = new WeakMap();
  }

  /**
   * Remember one claimed user message.
   * @param agent - the agent the message was claimed for.
   * @param message - the claimed message; only image parts are kept.
   * @param resolve - maps an image part to a host path (may return undefined).
   * @returns the stored batch, or undefined when the message carried no picture.
   */
  record(agent, message, resolve) {
    if (agent === undefined || agent === null) return undefined;
    const images = imagesOf(message);
    if (images.length === 0) return undefined;
    const batch = {
      at: Date.now(),
      images: images.slice(0, BATCH_LIMIT).map((part, index) => {
        let path;
        try {
          path = resolve(part);
        } catch {
          path = undefined;
        }
        return {
          index,
          path,
          ref: part.attachment ?? null,
          inline: typeof part.data === 'string' ? part.data : undefined,
          mediaType: part.mediaType ?? part.attachment?.mediaType ?? 'image/png',
          width: part.width ?? part.attachment?.width,
          height: part.height ?? part.attachment?.height,
          name: part.attachment?.name ?? part.name ?? `image-${index + 1}`,
        };
      }),
    };
    this.byAgent.set(agent, batch);
    return batch;
  }

  /** The newest batch for an agent, if it carried pictures. */
  latest(agent) {
    if (agent === undefined || agent === null) return undefined;
    return this.byAgent.get(agent);
  }

  /** The picture a tool call should fall back to when it names none. */
  last(agent) {
    const batch = this.latest(agent);
    return batch?.images?.[batch.images.length - 1];
  }

  /** Drop the batch once the model acted on it, so the prompt stops asking. */
  clear(agent) {
    if (agent === undefined || agent === null) return;
    this.byAgent.delete(agent);
  }
}

/** Every image part in a message, in message order. */
function imagesOf(message) {
  const content = message?.content;
  if (typeof content === 'string') return [];
  if (!Array.isArray(content)) return [];
  return content.filter((part) => part?.type === 'image');
}