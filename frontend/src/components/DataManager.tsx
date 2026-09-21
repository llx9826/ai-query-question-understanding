import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Upload,
  Typography,
} from 'antd';
import {
  CloudUploadOutlined,
  DeleteOutlined,
  FileExcelOutlined,
  HistoryOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { api } from '../api';
import type { DatasetSummary, PublicationResult, PublicationSummary } from '../types';

type JoinType = 'ONE_TO_ONE' | 'ONE_TO_MANY' | 'MANY_TO_ONE' | 'MANY_TO_MANY';

interface Props {
  open: boolean;
  workspaceId: string;
  onClose: () => void;
  onPublished: (publication: PublicationResult) => void;
}

function DatasetList({
  datasets,
  busy,
  onRemove,
}: {
  datasets: DatasetSummary[];
  busy: boolean;
  onRemove: (dataset: DatasetSummary) => void;
}) {
  if (!datasets.length) return <Empty description="这个大会还没有 Excel 数据" />;
  return <div className="dataset-list">
    {datasets.map(dataset => <section className="dataset-item" key={dataset.dataset_id}>
      <FileExcelOutlined className="dataset-icon" />
      <div className="dataset-content">
        <Space wrap><strong>{dataset.source_name}</strong><Tag>{dataset.tables.length} 个 Sheet</Tag></Space>
        <div className="dataset-models">
          {dataset.tables.map(table => <div key={table.model}>
            <strong>{table.sheet}</strong>
            <span>{table.row_count} 行 · {table.columns.length} 列</span>
            <code>{table.model}</code>
          </div>)}
        </div>
      </div>
      <Popconfirm
        title={`从新版本移除 ${dataset.source_name}？`}
        description="历史发布不会修改，可以随时回滚。"
        okText="移除并发布"
        cancelText="取消"
        onConfirm={() => onRemove(dataset)}
      >
        <Button danger type="text" disabled={busy} icon={<DeleteOutlined />}>移除</Button>
      </Popconfirm>
    </section>)}
  </div>;
}

export function DataManager({ open, workspaceId, onClose, onPublished }: Props) {
  const [active, setActive] = useState<PublicationResult | null>(null);
  const [publications, setPublications] = useState<PublicationSummary[]>([]);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [leftModel, setLeftModel] = useState('');
  const [leftColumn, setLeftColumn] = useState('');
  const [rightModel, setRightModel] = useState('');
  const [rightColumn, setRightColumn] = useState('');
  const [joinType, setJoinType] = useState<JoinType>('MANY_TO_ONE');

  const refresh = useCallback(async () => {
    setBusy('正在读取数据状态'); setError('');
    try {
      const [datasets, history] = await Promise.all([
        api.datasets(workspaceId),
        api.publications(workspaceId),
      ]);
      setActive(datasets); setPublications(history);
    } catch (reason) {
      setError((reason as Error).message);
    } finally { setBusy(''); }
  }, [workspaceId]);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);

  const publishFiles = async () => {
    const selected = files.flatMap(item => item.originFileObj ? [item.originFileObj as File] : []);
    if (!selected.length) return;
    setBusy('正在导入 Excel、构建 Wren Project 并发布'); setError('');
    try {
      const result = await api.upload(workspaceId, selected);
      setFiles([]); onPublished(result); await refresh();
    } catch (reason) { setError((reason as Error).message); setBusy(''); }
  };

  const remove = async (dataset: DatasetSummary) => {
    setBusy(`正在移除 ${dataset.source_name} 并构建新版本`); setError('');
    try {
      const result = await api.removeDataset(workspaceId, dataset.dataset_id);
      onPublished(result); await refresh();
    } catch (reason) { setError((reason as Error).message); setBusy(''); }
  };

  const activate = async (publication: PublicationSummary) => {
    setBusy(`正在切换到 ${publication.publication_id}`); setError('');
    try {
      const result = await api.activatePublication(workspaceId, publication.publication_id);
      onPublished(result); await refresh();
    } catch (reason) { setError((reason as Error).message); setBusy(''); }
  };

  const models = (active?.datasets || []).flatMap(dataset => dataset.tables);
  const columns = (model: string) => models.find(item => item.model === model)?.columns || [];

  const addRelationship = async () => {
    if (!leftModel || !leftColumn || !rightModel || !rightColumn) return;
    setBusy('正在验证字段匹配并构建 Wren Relationship'); setError('');
    try {
      const result = await api.addRelationship(workspaceId, {
        left_model: leftModel,
        left_column: leftColumn,
        right_model: rightModel,
        right_column: rightColumn,
        join_type: joinType,
      });
      onPublished(result); await refresh();
    } catch (reason) { setError((reason as Error).message); setBusy(''); }
  };

  return <Drawer
    className="data-manager"
    size="large"
    open={open}
    onClose={onClose}
    title={<span><FileExcelOutlined /> 数据与发布管理</span>}
  >
    <div className="manager-workspace">大会空间 <code>{workspaceId}</code></div>
    {error && <Alert type="error" showIcon title={error} closable onClose={() => setError('')} />}
    {busy && <Alert type="info" showIcon icon={<Spin size="small" />} title={busy} />}
    <Tabs items={[
      {
        key: 'datasets',
        label: 'Excel 数据',
        children: <>
          <Upload.Dragger
            accept=".xlsx"
            multiple
            beforeUpload={() => false}
            fileList={files}
            onChange={({ fileList }) => setFiles(fileList.slice(0, 20))}
            disabled={Boolean(busy)}
          >
            <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
            <p>选择或拖入一个或多个 Excel</p>
            <p className="ant-upload-hint">同名文件会更新原数据集，其他文件会新增。</p>
          </Upload.Dragger>
          <Button
            className="publish-button"
            type="primary"
            block
            disabled={!files.length || Boolean(busy)}
            loading={busy.startsWith('正在导入')}
            onClick={() => void publishFiles()}
          >上传并发布 {files.length ? `(${files.length})` : ''}</Button>
          <div className="manager-section-title">
            <span>当前版本 <code>{active?.publication_id || '尚未发布'}</code></span>
            <Button type="text" icon={<ReloadOutlined />} onClick={() => void refresh()}>刷新</Button>
          </div>
          <DatasetList datasets={active?.datasets || []} busy={Boolean(busy)} onRemove={remove} />
        </>,
      },
      {
        key: 'relationships',
        label: `表关系 (${active?.relationships?.length || 0})`,
        children: <div className="relationship-panel">
          <Alert type="info" showIcon title="关系由管理员确认，Wren负责后续多表规划和JOIN执行。" />
          <div className="relationship-form">
            <Select aria-label="左表模型" placeholder="选择左表" value={leftModel || undefined}
              options={models.map(item => ({ value: item.model, label: `${item.sheet} · ${item.model}` }))}
              onChange={value => { setLeftModel(value); setLeftColumn(''); }} />
            <Select aria-label="左表字段" placeholder="选择左表字段" value={leftColumn || undefined}
              options={columns(leftModel).map(item => ({ value: item.name, label: item.name }))}
              onChange={setLeftColumn} />
            <Select aria-label="关系类型" value={joinType} onChange={setJoinType}
              options={[
                { value: 'MANY_TO_ONE', label: '多对一' },
                { value: 'ONE_TO_MANY', label: '一对多' },
                { value: 'ONE_TO_ONE', label: '一对一' },
                { value: 'MANY_TO_MANY', label: '多对多' },
              ]} />
            <Select aria-label="右表模型" placeholder="选择右表" value={rightModel || undefined}
              options={models.filter(item => item.model !== leftModel).map(item => ({ value: item.model, label: `${item.sheet} · ${item.model}` }))}
              onChange={value => { setRightModel(value); setRightColumn(''); }} />
            <Select aria-label="右表字段" placeholder="选择右表字段" value={rightColumn || undefined}
              options={columns(rightModel).map(item => ({ value: item.name, label: item.name }))}
              onChange={setRightColumn} />
          </div>
          <Button type="primary" block disabled={Boolean(busy) || !leftColumn || !rightColumn}
            onClick={() => void addRelationship()}>验证并发布关系</Button>
          <div className="manager-section-title"><span>已发布关系</span></div>
          {(active?.relationships || []).length ? <div className="relationship-list">
            {active!.relationships!.map(item => <div key={item.name}>
              <Tag color="blue">{item.join_type}</Tag><code>{item.condition}</code>
            </div>)}
          </div> : <Empty description="尚未配置表关系" />}
        </div>,
      },
      {
        key: 'history',
        label: `版本历史 (${publications.length})`,
        children: publications.length ? <div className="publication-list">
          {publications.map(publication => <section className="publication-item" key={publication.publication_id}>
            <div>
              <Space wrap><code>{publication.publication_id}</code>{publication.active && <Tag color="green">当前</Tag>}</Space>
              <p>{new Date(publication.created_at).toLocaleString()} · {publication.datasets.length} 个 Excel</p>
            </div>
            {!publication.active && <Popconfirm
              title="切换到这个历史版本？"
              description="之后的新问题会使用该版本，已有问数记录不变。"
              okText="确认切换"
              cancelText="取消"
              onConfirm={() => activate(publication)}
            >
              <Button disabled={Boolean(busy)} icon={<HistoryOutlined />}>回滚到此版本</Button>
            </Popconfirm>}
          </section>)}
        </div> : <Empty description="还没有发布历史" />,
      },
    ]} />
    <Typography.Paragraph type="secondary" className="manager-note">
      移除 Excel 会生成新版本，不修改历史 DuckDB；回滚只切换活动版本。
    </Typography.Paragraph>
  </Drawer>;
}
