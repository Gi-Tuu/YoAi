/** 项目面板：创建项目（选宿主机文件夹）/ 在项目内新建会话 / 删除项目。
 *  聊天模式与项目模式并存：普通会话留在沙箱，不发放写能力。
 *  对齐纸墨设计：零圆角、1px 描边、朱红点缀。 */

import { open } from "@tauri-apps/plugin-dialog";
import { ipc } from "../lib/ipc";
import type { ProjectInfo, SessionInfo } from "../types/ipc";

interface Props {
  projects: ProjectInfo[];
  sessions: SessionInfo[];
  currentSessionId: string;
  ready: boolean;
  busy: boolean;
  onError: (message: string) => void;
}

export function ProjectPanel({ projects, sessions, currentSessionId, ready, busy, onError }: Props) {
  const createProject = async () => {
    if (!ready || busy) return;
    try {
      // 原生文件夹选择器：用户明确选择一个宿主机目录作为项目根
      const picked = await open({ directory: true, multiple: false, title: "选择项目文件夹" });
      if (!picked || typeof picked !== "string") return;
      const name = picked.split(/[\\/]/).filter(Boolean).pop() || "项目";
      await ipc.createProject(name, picked, `${name} · 会话`);
    } catch (error) {
      onError(`创建项目失败：${String(error)}`);
    }
  };

  const current = sessions.find((s) => s.id === currentSessionId);
  const isProject = current?.mode === "project";
  const activeProject = projects.find((p) => p.id === current?.project_id);

  return (
    <section className="project-panel" aria-label="项目">
      <header className="project-head">
        <strong>项目</strong>
        <button className="ghost" disabled={!ready || busy} onClick={() => void createProject()}
                title="选择宿主机文件夹，创建可写项目">
          ＋ 创建项目
        </button>
      </header>
      {isProject && activeProject && (
        <div className="project-current" title={activeProject.path}>
          当前：{activeProject.name}
        </div>
      )}
      <ul className="project-list">
        {projects.length === 0 && <li className="project-empty">暂无项目 · 会话默认在沙箱中</li>}
        {projects.map((p) => (
          <li key={p.id}>
            <button className="project-pick" title={p.path} disabled={busy}
                    onClick={() => void ipc.newSessionInProject(p.id).catch((e) => onError(String(e)))}>
              {p.name} <span className="project-hint">＋对话</span>
            </button>
            <button className="project-icon ghost" title="删除项目定义（会话保留）" disabled={busy}
                    onClick={() => void ipc.deleteProject(p.id).catch((e) => onError(String(e)))}>×</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
