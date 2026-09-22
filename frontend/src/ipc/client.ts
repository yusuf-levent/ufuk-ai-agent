/** Typed renderer-side client over the preload bridge. */
import type {
  EventMap,
  IpcResult,
  TypedInvoke,
  TypedSubscribe,
} from "@shared/ipc";
import type { EventChannel } from "@shared/channels";
import { INVOKE_CHANNELS } from "@shared/channels";
import type {
  AppVersionResponse,
  LoginRequest,
  PrivacyInfo,
  RegisterRequest,
  SessionInfo,
  Settings,
  SettingsPatch,
} from "@shared/ipc";

interface UfukBridge {
  invoke: TypedInvoke;
  subscribe: TypedSubscribe;
}

declare global {
  interface Window {
    ufuk: UfukBridge;
  }
}

const bridge = (): UfukBridge => {
  if (!window.ufuk) {
    throw new Error("preload bridge missing (window.ufuk)");
  }
  return window.ufuk;
};

const unwrap = async <T>(p: Promise<IpcResult<T>>): Promise<T> => {
  const result = await p;
  if (!result.ok) {
    throw Object.assign(new Error(result.error.message), {
      code: result.error.code,
    });
  }
  return result.value;
};

export const api = {
  getVersion: () => unwrap(bridge().invoke(INVOKE_CHANNELS.appVersion)),
  getSettings: () => unwrap(bridge().invoke(INVOKE_CHANNELS.settingsGet)),
  setSettings: (patch: SettingsPatch) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.settingsSet, patch)),
  login: (req: LoginRequest) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.authLogin, req)),
  register: (req: RegisterRequest) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.authRegister, req)),
  logout: () => unwrap(bridge().invoke(INVOKE_CHANNELS.authLogout)),
  session: () =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.authSession),
    ) as Promise<SessionInfo | null>,
  privacyInfo: () =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.privacyInfo),
    ) as Promise<PrivacyInfo>,
  openExternal: (url: string) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.openExternal, { url })),
  subscribe: (<C extends EventChannel>(
    channel: C,
    listener: (payload: EventMap[C]) => void,
  ) => bridge().subscribe(channel, listener)) as TypedSubscribe,
};

export type { AppVersionResponse, SessionInfo, Settings, PrivacyInfo };
