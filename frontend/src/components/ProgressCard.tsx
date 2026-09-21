import { LoadingOutlined, CheckOutlined } from '@ant-design/icons';
import type { Snapshot } from '../types';

const nodes = [
  ['resolve_publication', '绑定发布'], ['call_wren', 'Wren 问数'], ['finish_turn', '保存会话'],
];

export function ProgressCard({ snapshot, seconds }: { snapshot?: Snapshot; seconds: number }) {
  const stages = snapshot?.progress?.stages || [];
  const active = nodes.reduce((last, [stage], index) => stages.some(s => s.stage === stage) ? index : last, 0);
  return <div className="progress-card" role="status" aria-live="polite">
    <div className="progress-top"><span><LoadingOutlined /> 正在处理你的问题</span><span>{seconds} 秒</span></div>
    <div className="progress-steps">{nodes.map(([key, label], index) => <span key={key}
      className={index < active ? 'done' : index === active ? 'active' : ''}>
      <i>{index < active ? <CheckOutlined /> : index + 1}</i>{label}</span>)}</div>
    <p>{seconds >= 30 ? '模型响应较慢，可以继续等待或停止。本页不会自动重复调用模型。' : '完成的结果会保存在当前会话，刷新页面后可继续查看。'}</p>
  </div>;
}
