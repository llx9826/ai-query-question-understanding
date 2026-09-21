import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, App as AntApp, Avatar, Badge, Button, Drawer, Dropdown, Input, Modal, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { ArrowRightOutlined, BarChartOutlined, CalendarOutlined, CheckCircleFilled, DatabaseOutlined, EditOutlined, FileExcelOutlined, FolderOpenOutlined, GlobalOutlined, HistoryOutlined, MenuOutlined, MessageOutlined, MoreOutlined, PlusOutlined, SearchOutlined, SendOutlined, SettingOutlined, StopOutlined, TeamOutlined, ThunderboltFilled } from '@ant-design/icons';
import { api, ApiError, getToken, messageId, setToken } from './api';
import type { ChatMessage, Session, Snapshot, Workspace } from './types';
import { ResultCard } from './components/ResultCard';
import { ProgressCard } from './components/ProgressCard';
import { DataManager } from './components/DataManager';

const examples = [
  { icon: <TeamOutlined />, label: '嘉宾统计', text: 'CHERY 有多少人？', color: 'blue' },
  { icon: <CalendarOutlined />, label: '活动安排', text: '有哪些会议和活动？', color: 'purple' },
  { icon: <GlobalOutlined />, label: '国家分布', text: '按邀请国家统计报名人数，取前 10 名。', color: 'green' },
  { icon: <BarChartOutlined />, label: '品牌对比', text: '各品牌分别有多少人？', color: 'orange' },
];
const emptySnapshot: Snapshot = { messages: [], is_running: false, has_more: false };
const previewOnly = document.querySelector('meta[name="aiq-preview"]')?.getAttribute('content') === 'true';

export default function App() {
  const { message } = AntApp.useApp();
  const [workspace, setWorkspace] = useState<Workspace>();
  const [workspaceId, setWorkspaceId] = useState('');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState<string>();
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [older, setOlder] = useState<ChatMessage[]>([]);
  const [hasOlder, setHasOlder] = useState<boolean>();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<{ sid: string; id: string; text: string; at: number }>();
  const [draft, setDraft] = useState('');
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [drawer, setDrawer] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const [token, setTokenValue] = useState(getToken);
  const [renaming, setRenaming] = useState<Session>();
  const [newName, setNewName] = useState('');
  const [seconds, setSeconds] = useState(0);
  const [pollKey, setPollKey] = useState(0);
  const bottom = useRef<HTMLDivElement>(null);
  const pendingRef = useRef(pending);
  const activeRef = useRef(active);
  const sendingRef = useRef(false);
  pendingRef.current = pending;
  activeRef.current = active;

  const refreshSessions = useCallback(async (agent: string) => {
    const data = await api.sessions(agent);
    setSessions(data.sessions.sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    return data.sessions;
  }, []);

  const connect = useCallback(async () => {
    setInitializing(true); setError(''); setSnapshot(emptySnapshot); setOlder([]); setHasOlder(undefined);
    if (previewOnly) { setInitializing(false); return; }
    try {
      const info = await api.bootstrap(); setWorkspace(info); setWorkspaceId(info.workspace_id);
      const list = await refreshSessions(info.agent_id);
      const remembered = localStorage.getItem(`aiq-last-session-${info.agent_id}-${info.workspace_id}`);
      setActive(list.some(s => s.id === remembered && s.workspace_id === info.workspace_id) ? remembered! : undefined);
      setSettingsOpen(false); setPollKey(k => k + 1);
    } catch (e) {
      setError((e as Error).message); setWorkspace(undefined);
      if (e instanceof ApiError && e.status === 401) setSettingsOpen(true);
    } finally { setInitializing(false); }
  }, [refreshSessions]);

  useEffect(() => { void connect(); }, [connect]);

  // 轮询只读接口，不增加模型调用；切换会话时废弃旧请求的响应。
  useEffect(() => {
    if (!active || !workspace) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let lastRunning = false;
    setLoadingHistory(true);
    const poll = async () => {
      try {
        const value = await api.snapshot(active, workspace.agent_id);
        if (cancelled) return;
        setSnapshot(value); setLoadingHistory(false); setError('');
        const current = pendingRef.current;
        if (current?.sid === active && !value.is_running) {
          const index = value.messages.findIndex(m => m.id === current.id);
          if (index >= 0 && value.messages.slice(index + 1).some(m => m.role === 'assistant')) {
            setPending(undefined); void refreshSessions(workspace.agent_id);
          } else if (Date.now() - current.at > 20000 && index < 0) {
            setPending(undefined); setDraft(current.text);
            setError('没有查到本次消息的投递记录。请确认连接后再发送。');
          }
        }
        if (lastRunning && !value.is_running) void refreshSessions(workspace.agent_id);
        lastRunning = value.is_running;
        timer = setTimeout(poll, document.hidden ? 10000 : value.is_running || pendingRef.current ? 1200 : 5000);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message); setLoadingHistory(false);
        if (e instanceof ApiError && e.status === 401) { setSettingsOpen(true); return; }
        timer = setTimeout(poll, 4000);
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, workspace, pollKey, refreshSessions]);

  const busy = sending || snapshot.is_running || Boolean(pending && pending.sid === active);
  useEffect(() => {
    if (!busy) { setSeconds(0); return; }
    const start = pending?.at || Date.now();
    const tick = () => setSeconds(Math.floor((Date.now() - start) / 1000));
    tick(); const timer = setInterval(tick, 1000); return () => clearInterval(timer);
  }, [busy, pending?.at]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [snapshot.messages.length, pending?.id]);

  const select = (id?: string) => {
    setActive(id); setSnapshot(emptySnapshot); setOlder([]); setHasOlder(undefined); setDrawer(false); setError('');
    setLoadingHistory(Boolean(id));
    if (workspace) {
      if (id) localStorage.setItem(`aiq-last-session-${workspace.agent_id}-${workspaceId}`, id);
      else localStorage.removeItem(`aiq-last-session-${workspace.agent_id}-${workspaceId}`);
    }
  };

  const send = async (question = draft) => {
    const text = question.trim();
    if (!text || !workspace || busy || sendingRef.current || loadingHistory || !workspace.wren_configured) return;
    sendingRef.current = true; setSending(true); setError('');
    let sid = active;
    try {
      if (!sid) {
        sid = (await api.create(workspace.agent_id, text.slice(0, 36), workspaceId)).session_id;
        select(sid); void refreshSessions(workspace.agent_id);
      }
      const id = messageId();
      setPending({ sid, id, text, at: Date.now() }); setDraft('');
      await api.send(sid, workspace.agent_id, text, id);
      setPollKey(k => k + 1);
    } catch (e) {
      setError((e as Error).message);
      // 网络不确定时继续读取服务端状态，绝不自动重新投递模型请求。
      if (!(e instanceof ApiError) || e.status !== 0) { setPending(undefined); setDraft(text); }
      setPollKey(k => k + 1);
    } finally { setSending(false); sendingRef.current = false; }
  };

  const loadOlder = async () => {
    if (!active || !workspace) return;
    const sid = active; setLoadingOlder(true);
    try {
      const value = await api.snapshot(sid, workspace.agent_id, older[0]?.id || snapshot.messages[0]?.id);
      if (activeRef.current !== sid) return;
      setOlder(old => [...value.messages, ...old]); setHasOlder(value.has_more);
    } catch (e) { message.error((e as Error).message); }
    finally { setLoadingOlder(false); }
  };

  const messages = [...new Map([...older, ...snapshot.messages].map(m => [m.id, m])).values()];
  if (pending && pending.sid === active && !messages.some(m => m.id === pending.id)) {
    messages.push({ id: pending.id, role: 'user', text: pending.text });
  }
  const activeSession = sessions.find(s => s.id === active);
  const workspaceSessions = sessions.filter(s => s.workspace_id === workspaceId);
  const isWelcome = !messages.length && !busy && !loadingHistory;
  const sidebar = <div className="sidebar-inner">
    <a className="brand" href="/" onClick={e => { e.preventDefault(); select(); }}>
      <div className="brand-mark"><BarChartOutlined /></div><div><strong>峰会问数</strong><span>SUMMIT INSIGHT</span></div>
    </a>
    <Button className="new-chat" type="primary" aria-label="新建会话" icon={<PlusOutlined />} disabled={sending}
      onClick={() => select()}>新建会话</Button>
    <div className="sidebar-section"><HistoryOutlined /> 会话记录 <span>{workspaceSessions.length}</span></div>
    <Input className="session-search" placeholder="搜索会话" aria-label="搜索会话" prefix={<SearchOutlined />} allowClear
      variant="filled" value={filter} onChange={e => setFilter(e.target.value)} />
    <div className="session-list">{workspaceSessions.filter(s => s.name.toLowerCase().includes(filter.toLowerCase())).map(s => <div
      className={`session-row ${s.id === active ? 'selected' : ''}`} key={s.id}>
      <button className="session-select" onClick={() => select(s.id)}><MessageOutlined />
        <span>{s.name}</span>{s.is_running && <Badge status="processing" />}</button>
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'rename', label: '重命名', icon: <EditOutlined /> }],
        onClick: () => { setRenaming(s); setNewName(s.name); } }}>
        <Button type="text" size="small" icon={<MoreOutlined />} aria-label={`管理会话 ${s.name}`} />
      </Dropdown>
    </div>)}{!workspaceSessions.length && <div className="history-empty">开始提问后，会话会保存在这里。</div>}</div>
    <div className="source-card"><div className="source-title"><DatabaseOutlined /> 当前数据源<Tag>Excel</Tag></div>
      <div className="source-file"><FileExcelOutlined /><span>{workspaceId || '尚未选择大会'}</span></div>
      <div className="source-note">基于已导入的数据快照查询</div></div>
    <Button className="manage-data-button" icon={<FolderOpenOutlined />} disabled={!workspaceId}
      onClick={() => setManagerOpen(true)}>管理 Excel 与版本</Button>
    <button className="sidebar-footer" onClick={() => setSettingsOpen(true)}><Avatar size={30} className="user-avatar">会</Avatar>
      <span>峰会工作台<small>{workspace ? '服务已连接' : '等待连接'}</small></span><SettingOutlined /></button>
  </div>;

  return <div className="app-shell">
    <aside className="desktop-sidebar">{sidebar}</aside>
    <Drawer placement="left" size={280} open={drawer} onClose={() => setDrawer(false)} title="会话与数据源"
      styles={{ body: { padding: 0 } }}>{sidebar}</Drawer>
    <main className="main-panel">
      <header className="topbar"><div className="topbar-left"><Button className="mobile-menu" type="text"
        icon={<MenuOutlined />} aria-label="打开会话菜单" onClick={() => setDrawer(true)} />
        <span className="workspace-label">大会</span><span className="breadcrumb-divider">/</span>
        <Select
          className="workspace-select"
          aria-label="选择大会"
          variant="borderless"
          value={workspaceId || undefined}
          options={(workspace?.workspaces || []).map(item => ({ value: item.workspace_id, label: item.name }))}
          onChange={value => {
            setWorkspaceId(value); setActive(undefined); setSnapshot(emptySnapshot); setOlder([]); setHasOlder(undefined); setError('');
            const remembered = localStorage.getItem(`aiq-last-session-${workspace?.agent_id}-${value}`);
            const restored = sessions.find(item => item.id === remembered && item.workspace_id === value);
            if (restored) setActive(restored.id);
          }}
        />
        <strong>智能问数</strong><Tag className="ai-tag" color="blue">AI</Tag></div>
        <Space className="topbar-right"><span className="connection"><Badge status={workspace ? 'success' : 'default'} />
          {previewOnly ? '界面预览' : workspace ? '已连接' : '未连接'}</span><Tooltip title="连接设置"><Button type="text" icon={<SettingOutlined />}
            aria-label="连接设置" onClick={() => setSettingsOpen(true)} /></Tooltip></Space></header>
      <div className="conversation-scroll">
        <div className="content-column">
          {initializing && <div className="initial-loading"><Spin /> <span>正在连接问数服务…</span></div>}
          {error && <Alert className="top-alert" type="error" showIcon title={error}
            action={!workspace ? <Button size="small" onClick={() => void connect()}>重新连接</Button> : undefined} />}
          {workspace && !workspace.wren_configured && <Alert className="top-alert" type="warning" showIcon
            title="Wren 尚未配置" description="请配置问数平台到 Wren HTTP 的服务 Token。百炼模型只在 Wren 服务中配置。" />}
          {isWelcome ? <section className="welcome">
            <div className="welcome-eyebrow"><span /> 2026 GLOBAL PARTNER SUMMIT</div>
            <div className="welcome-icon"><ThunderboltFilled /></div>
            <h1>你的峰会数据，<br className="mobile-break" /><span>一句话就能查。</span></h1>
            <p className="welcome-description">从嘉宾名单到活动安排，直接提问，获取有据可查的答案。</p>
            <div className="welcome-source"><FileExcelOutlined /><span>全球合作伙伴商务峰会 · 外宾名单</span><CheckCircleFilled /></div>
            <div className="examples-title"><span>试试这样问</span><span>也可以在下方输入你的问题</span></div>
            <div className="example-grid">{examples.map(example => <button className="example-card" key={example.label}
              onClick={() => { setDraft(example.text); document.getElementById('question-input')?.focus(); }}>
              <div className={`example-icon ${example.color}`}>{example.icon}</div><span className="example-label">{example.label}</span>
              <p>{example.text}</p><ArrowRightOutlined className="example-arrow" /></button>)}</div>
            <div className="welcome-tip"><MessageOutlined /> 支持连续追问，例如：“其中参加主题大会的呢？”</div>
          </section> : <section className="conversation" aria-label="问数会话">
            <div className="conversation-title"><span>{activeSession?.name || '新的问数'}</span><Tag>当前会话</Tag></div>
            {(hasOlder ?? snapshot.has_more) && <div className="load-older"><Button type="link" loading={loadingOlder}
              onClick={() => void loadOlder()}>加载更早的消息</Button></div>}
            {loadingHistory && !messages.length && <div className="initial-loading"><Spin /> 正在恢复会话…</div>}
            {messages.map(m => m.role === 'user' ? <article className="user-message" key={m.id}>
              <div className="user-bubble">{m.text}</div><Avatar className="user-avatar" size={32}>我</Avatar></article> :
              <article className="assistant-message" key={m.id}>
                <Avatar className="assistant-avatar" icon={<ThunderboltFilled />} size={32} />
                <div className="assistant-body"><div className="assistant-label">峰会数据助手
                  {m.reply?.context_saved && <span><CheckCircleFilled /> 已保存</span>}</div>
                  {m.reply?.result ? <ResultCard result={m.reply.result} reply={m.reply} /> :
                    <div className="text-answer"><Typography.Paragraph>{m.reply?.failure?.message || m.text || '本轮已结束。'}</Typography.Paragraph></div>}
                  {m.finished_reason === 'interrupted' && <p className="muted">本次请求已停止。</p>}
                  {m.reply && !m.reply.context_saved && <Alert type="warning" showIcon title="本轮会话状态未完整保存，下次追问请明确查询条件。" />}
                </div>
              </article>)}
            {busy && <div className="working-area"><ProgressCard snapshot={snapshot.is_running ? snapshot : undefined} seconds={seconds} /></div>}
          </section>}
          <div ref={bottom} />
        </div>
      </div>
      <footer className="composer-area"><div className="composer-column">
        <div className={`composer ${busy ? 'busy' : ''}`}>
          <Input.TextArea id="question-input" aria-label="输入问题" placeholder="问问嘉宾、活动或参会安排…"
            value={draft} onChange={e => setDraft(e.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} maxLength={4000}
            variant="borderless" onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && window.matchMedia('(min-width: 769px)').matches) {
                e.preventDefault(); void send();
              }
            }} />
          <div className="composer-toolbar"><span className="composer-source"><DatabaseOutlined /> {workspaceId || '大会数据'}
            <span className="desktop-only"> · Excel 数据</span></span><Space>
            <span className="input-hint">Enter 发送 · Shift + Enter 换行</span>
            {busy ? <Button danger aria-label="停止" icon={<StopOutlined />} disabled={!active || sending}
              onClick={async () => {
                try { await api.interrupt(active!, workspace!.agent_id); message.info('已请求停止，正在保存会话状态。'); }
                catch (e) { message.error((e as Error).message); }
              }}>停止</Button> : <Button type="primary" className="send-button" aria-label="发送" icon={<SendOutlined />}
                disabled={!draft.trim() || initializing || !workspace?.wren_configured || loadingHistory}
                onClick={() => void send()}>发送</Button>}
          </Space></div>
        </div>
        <p className="composer-disclaimer">表格中的“1”表示计划出席；默认人数按报名记录统计。结果可展开 SQL 核对。</p>
      </div></footer>
    </main>
    {workspaceId && <DataManager open={managerOpen} workspaceId={workspaceId} onClose={() => setManagerOpen(false)}
      onPublished={result => { message.success(result.changed ? `已激活 ${result.publication_id}` : '数据没有变化'); setPollKey(key => key + 1); }} />}
    <Modal title="连接设置" open={settingsOpen} onCancel={() => setSettingsOpen(false)} okText="连接服务"
      confirmLoading={initializing} onOk={() => { setToken(token.trim()); setPending(undefined); void connect(); }}>
      <Typography.Paragraph type="secondary">输入管理员提供的访问凭证。百炼模型密钥只配置在 Wren 服务。</Typography.Paragraph>
      <label htmlFor="access-token">访问凭证</label><Input.Password id="access-token" value={token}
        onChange={e => setTokenValue(e.target.value)} autoComplete="off" style={{ marginTop: 8 }} />
      <p className="muted" style={{ marginTop: 12 }}>访问凭证仅保留在当前浏览器标签页。</p>
    </Modal>
    <Modal title="重命名会话" open={Boolean(renaming)} onCancel={() => setRenaming(undefined)} okText="保存"
      okButtonProps={{ disabled: !newName.trim(), "aria-label": "保存" }} onOk={async () => {
        try { await api.rename(renaming!.id, workspace!.agent_id, newName.trim()); setRenaming(undefined); await refreshSessions(workspace!.agent_id); }
        catch (e) { message.error((e as Error).message); }
      }}><Input aria-label="会话名称" value={newName} onChange={e => setNewName(e.target.value)} maxLength={80} /></Modal>
  </div>;
}
