/**
 * Ufuk preload — the ONLY bridge between the sandboxed renderer and main.
 * Two functions, both channel-allowlisted:
 *   - invoke(channel, payload): request/response, zod-validated in main
 *   - subscribe(channel, listener): main->renderer push events
 * No node APIs, no electron APIs, no raw ipcRenderer are ever exposed.
 */
import { contextBridge, ipcRenderer } from "electron";
import { EVENT_CHANNEL_SET, INVOKE_CHANNEL_SET } from "@shared/channels";

const invoke = (channel: string, payload?: unknown): Promise<unknown> => {
  if (!INVOKE_CHANNEL_SET.has(channel)) {
    return Promise.reject(new Error(`invoke: channel not allowed: ${channel}`));
  }
  return ipcRenderer.invoke(channel, payload);
};

const subscribe = (
  channel: string,
  listener: (payload: unknown) => void,
): (() => void) => {
  if (!EVENT_CHANNEL_SET.has(channel)) {
    throw new Error(`subscribe: channel not allowed: ${channel}`);
  }
  const wrapped = (_event: unknown, payload: unknown): void =>
    listener(payload);
  ipcRenderer.on(channel, wrapped);
  return () => {
    ipcRenderer.removeListener(channel, wrapped);
  };
};

contextBridge.exposeInMainWorld("ufuk", { invoke, subscribe });
