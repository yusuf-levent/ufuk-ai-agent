/** Typed renderer-side client over the preload bridge. */
import type { EventChannel } from "@shared/channels";
import { INVOKE_CHANNELS } from "@shared/channels";
import type {
  AppVersionResponse,
  CheckpointInfo,
  ConversationDetail,
  ConversationSummary,
  DiffResponse,
  EventMap,
  IpcResult,
  LoginRequest,
  PrivacyInfo,
  ProjectInfo,
  RegisterRequest,
  SessionInfo,
  SessionSnapshot,
  Settings,
  SettingsPatch,
  TierCatalog,
  TypedInvoke,
  TypedSubscribe,
  UsageInfo,
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
    ) as Promise<SessionSnapshot>,
  privacyInfo: () =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.privacyInfo),
    ) as Promise<PrivacyInfo>,
  openExternal: (url: string) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.openExternal, { url })),
  listProjects: () =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.projectsList)) as Promise<
      ProjectInfo[]
    >,
  addProject: (path: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.projectsAdd, { path }),
    ) as Promise<ProjectInfo>,
  removeProject: (path: string) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.projectsRemove, { path })),
  pickFolder: () =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.projectsPickFolder)) as Promise<
      string | null
    >,
  listConversations: (root: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsList, { root }),
    ) as Promise<ConversationSummary[]>,
  createConversation: (root: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsCreate, { root }),
    ) as Promise<ConversationSummary>,
  loadConversation: (root: string, id: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsLoad, { root, id }),
    ) as Promise<ConversationDetail | null>,
  renameConversation: (root: string, id: string, title: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsRename, {
        root,
        id,
        title,
      }),
    ) as Promise<boolean>,
  deleteConversation: (root: string, id: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsDelete, { root, id }),
    ) as Promise<boolean>,
  sendChat: (req: {
    root: string;
    conversationId: string;
    message: string;
    model?: string;
  }) => unwrap(bridge().invoke(INVOKE_CHANNELS.chatSend, req)),
  stopChat: (conversationId: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.chatStop, { conversationId }),
    ) as Promise<boolean>,
  respondApproval: (req: {
    conversationId: string;
    approvalId: string;
    approved: boolean;
    remember: boolean;
  }) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.approvalsRespond, req),
    ) as Promise<boolean>,
  approvalPreview: (req: { conversationId: string; approvalId: string }) =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.approvalsPreview, req)) as Promise<{
      tool: string;
      pattern?: string;
    } | null>,
  setPermissionMode: (root: string, mode: "ask" | "auto-edits") =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.projectsSetPermissionMode, {
        root,
        mode,
      }),
    ) as Promise<ProjectInfo>,
  listCheckpoints: (root: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.checkpointsList, { root }),
    ) as Promise<CheckpointInfo[]>,
  undoCheckpoint: (root: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.checkpointsUndo, { root }),
    ) as Promise<CheckpointInfo | null>,
  revertCheckpoint: (root: string, id: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.checkpointsRevert, { root, id }),
    ) as Promise<CheckpointInfo | null>,
  diffFile: (req: { root: string; path: string; checkpointId?: string }) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.checkpointsDiff, req),
    ) as Promise<DiffResponse>,
  changedFiles: (root: string, id: string) =>
    unwrap(
      bridge().invoke(INVOKE_CHANNELS.conversationsChangedFiles, {
        root,
        id,
      }),
    ) as Promise<{ path: string; tool: string; ok: boolean; at: string }[]>,
  tierCatalog: () =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.modelsList)) as Promise<{
      allowed: {
        id: string;
        displayName?: string;
        upstreamProvider?: string;
        upstreamModel?: string;
        maxOutputTokens?: number;
        contextWindow?: number;
      }[];
      locked: { id: string; reason: string }[];
    }>,
  usage: () =>
    unwrap(bridge().invoke(INVOKE_CHANNELS.usageGet)) as Promise<{
      planName: string;
      creditLimit: number;
      creditsUsed: number;
      creditsRemaining: number;
      requestsPerMinute: number;
      periodEnd?: string;
    }>,
  subscribe: (<C extends EventChannel>(
    channel: C,
    listener: (payload: EventMap[C]) => void,
  ) => bridge().subscribe(channel, listener)) as TypedSubscribe,
};

export type {
  AppVersionResponse,
  SessionInfo,
  SessionSnapshot,
  Settings,
  PrivacyInfo,
  ProjectInfo,
  ConversationSummary,
  ConversationDetail,
  CheckpointInfo,
  DiffResponse,
  TierCatalog,
  UsageInfo,
};
