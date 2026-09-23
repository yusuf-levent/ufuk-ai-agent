/**
 * IPC handler registration. Every renderer->main call:
 *   1. is checked against the trusted-sender policy (our origin only),
 *   2. has its payload zod-validated,
 *   3. returns an IpcResult envelope (never a bare throw across the bridge).
 */
import { ipcMain, shell, dialog, BrowserWindow } from "electron";
import { z } from "zod";
import {
  ConversationIdRequestSchema,
  ConversationRenameRequestSchema,
  LoginRequestSchema,
  OpenExternalRequestSchema,
  ProjectPathRequestSchema,
  ProjectRootRequestSchema,
  RegisterRequestSchema,
  SettingsPatchSchema,
  type IpcResult,
  type Settings,
} from "@shared/ipc";
import { INVOKE_CHANNELS } from "@shared/channels";
import { isTrustedSender, parseExternalUrl } from "./security";
import type { SettingsStore } from "./settings";
import {
  authErrorCode,
  buildGatewaySession,
  fetchPrivacyInfo,
  fetchSessionInfo,
  type GatewaySession,
} from "./gateway";
import { ProjectManager, ProjectValidationError } from "./projects";

export interface IpcDeps {
  win: () => BrowserWindow | null;
  settings: SettingsStore;
  /** Electron user-data dir (%APPDATA%/ufuk). */
  userDataDir: string;
  /** safeStorage (injected for tests). */
  safe: {
    isEncryptionAvailable(): boolean;
    encryptString(plainText: string): Buffer;
    decryptString(encrypted: Buffer): string;
  };
  /** Rebuilt whenever settings change; also returns the active session. */
  session: () => GatewaySession;
  setSession: (s: GatewaySession) => void;
  versions: () => { version: string; electron: string; node: string };
  /** Project manager (recent projects + conversation stores). */
  projects: ProjectManager;
}

type Handler = (
  event: Electron.IpcMainInvokeEvent,
  payload: unknown,
) => Promise<IpcResult<unknown>>;

function register(
  channel: string,
  schema: z.ZodTypeAny,
  handler: Handler,
): void {
  ipcMain.handle(channel, async (event, payload) => {
    if (!isTrustedSender(event.sender)) {
      return {
        ok: false,
        error: { message: "untrusted sender", code: "forbidden" },
      };
    }
    if (payload !== undefined) {
      const parsed = schema.safeParse(payload);
      if (!parsed.success) {
        return {
          ok: false,
          error: {
            message: `invalid request for ${channel}`,
            code: "invalid_request",
          },
        };
      }
    }
    try {
      return await handler(event, payload);
    } catch (err) {
      if (err instanceof ProjectValidationError) {
        return { ok: false, error: { message: err.message, code: err.code } };
      }
      const mapped = authErrorCode(err);
      return { ok: false, error: mapped };
    }
  });
}

export function registerIpcHandlers(deps: IpcDeps): void {
  register(INVOKE_CHANNELS.appVersion, z.void(), async () => ({
    ok: true,
    value: deps.versions(),
  }));

  register(INVOKE_CHANNELS.settingsGet, z.void(), async () => ({
    ok: true,
    value: deps.settings.load(),
  }));

  register(
    INVOKE_CHANNELS.settingsSet,
    SettingsPatchSchema,
    async (_e, payload) => {
      const settings: Settings = deps.settings.patch(
        SettingsPatchSchema.parse(payload),
      );
      // backend URL changes rebuild the gateway session (new token namespace)
      deps.setSession(
        buildGatewaySession(settings, deps.userDataDir, deps.safe),
      );
      return { ok: true, value: settings };
    },
  );

  register(
    INVOKE_CHANNELS.authLogin,
    LoginRequestSchema,
    async (_e, payload) => {
      const { email, password } = LoginRequestSchema.parse(payload);
      await deps.session().auth.login(email, password);
      return { ok: true, value: null };
    },
  );

  register(
    INVOKE_CHANNELS.authRegister,
    RegisterRequestSchema,
    async (_e, payload) => {
      const { email, password, displayName } =
        RegisterRequestSchema.parse(payload);
      await deps.session().auth.register(email, password, displayName);
      return { ok: true, value: null };
    },
  );

  register(INVOKE_CHANNELS.authLogout, z.void(), async () => {
    await deps.session().auth.logout();
    return { ok: true, value: null };
  });

  register(INVOKE_CHANNELS.authSession, z.void(), async () => {
    const info = await fetchSessionInfo(deps.session());
    return { ok: true, value: info };
  });

  register(INVOKE_CHANNELS.privacyInfo, z.void(), async () => {
    const info = await fetchPrivacyInfo(deps.session());
    return { ok: true, value: info };
  });

  register(
    INVOKE_CHANNELS.openExternal,
    OpenExternalRequestSchema,
    async (_e, payload) => {
      const { url } = OpenExternalRequestSchema.parse(payload);
      const parsed = parseExternalUrl(url);
      if (!parsed) {
        return {
          ok: false,
          error: {
            message: "only http(s) links can be opened",
            code: "invalid_request",
          },
        };
      }
      const win = deps.win();
      if (win) {
        const choice = await dialog.showMessageBox(win, {
          type: "question",
          buttons: ["Open in browser", "Cancel"],
          defaultId: 1,
          cancelId: 1,
          title: "Open link",
          message: "Open this link in your system browser?",
          detail: url,
          noLink: true,
        });
        if (choice.response !== 0) {
          return { ok: true, value: false };
        }
      }
      await shell.openExternal(parsed.toString());
      return { ok: true, value: true };
    },
  );

  // -----------------------------------------------------------------------
  // projects & conversations (Milestone 5)
  // -----------------------------------------------------------------------

  register(INVOKE_CHANNELS.projectsList, z.void(), async () => ({
    ok: true,
    value: deps.projects.list(),
  }));

  register(
    INVOKE_CHANNELS.projectsAdd,
    ProjectPathRequestSchema,
    async (_e, payload) => {
      const { path } = ProjectPathRequestSchema.parse(payload);
      // throws ProjectValidationError -> coded envelope
      return { ok: true, value: deps.projects.add(path) };
    },
  );

  register(
    INVOKE_CHANNELS.projectsRemove,
    ProjectPathRequestSchema,
    async (_e, payload) => {
      const { path } = ProjectPathRequestSchema.parse(payload);
      deps.projects.remove(path);
      return { ok: true, value: null };
    },
  );

  register(INVOKE_CHANNELS.projectsPickFolder, z.void(), async () => {
    const win = deps.win();
    const result = win
      ? await dialog.showOpenDialog(win, {
          title: "Add project folder",
          properties: ["openDirectory"],
        })
      : { canceled: true, filePaths: [] as string[] };
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: true, value: null };
    }
    return { ok: true, value: result.filePaths[0] ?? null };
  });

  register(
    INVOKE_CHANNELS.conversationsList,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      deps.projects.touch(root);
      return { ok: true, value: await deps.projects.listConversations(root) };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsCreate,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      const workspace = deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      const model = deps.settings.load().defaultTier;
      const id = await opened.store.createConversation(workspace.root, model);
      const created = await opened.store.loadConversation(id);
      if (!created) {
        return {
          ok: false,
          error: { message: "conversation vanished", code: "internal" },
        };
      }
      return { ok: true, value: created.summary };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsLoad,
    ConversationIdRequestSchema,
    async (_e, payload) => {
      const { root, id } = ConversationIdRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return { ok: true, value: await opened.store.loadConversation(id) };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsRename,
    ConversationRenameRequestSchema,
    async (_e, payload) => {
      const { root, id, title } =
        ConversationRenameRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return {
        ok: true,
        value: await opened.store.renameConversation(id, title),
      };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsDelete,
    ConversationIdRequestSchema,
    async (_e, payload) => {
      const { root, id } = ConversationIdRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return {
        ok: true,
        value: await opened.store.deleteConversation(id),
      };
    },
  );
}
