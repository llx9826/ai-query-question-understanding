import { Alert, Button, Collapse, Empty, Space, Table, Tag, Typography, App } from 'antd';
import { CheckCircleFilled, CopyOutlined, DownloadOutlined, CodeOutlined } from '@ant-design/icons';
import type { Reply, WrenResult } from '../types';

function csvValue(value: unknown) {
  let text = value == null ? '' : String(value);
  if (/^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function ResultCard({ result, reply }: { result: WrenResult; reply?: Reply }) {
  const { message } = App.useApp();
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text); message.success('已复制');
    } catch { message.warning('浏览器限制了复制，请手动复制。'); }
  };
  if (result.status !== 'answered') {
    return <Alert type={result.status === 'needs_clarification' ? 'info' : 'warning'} showIcon
      title={result.status === 'needs_clarification' ? '需要补充信息' : '当前问题暂不支持'}
      description={result.answer} />;
  }
  const exportCsv = () => {
    const rows = [result.columns, ...result.rows.map(row => result.columns.map(name => row[name]))];
    const blob = new Blob(['\uFEFF' + rows.map(row => row.map(csvValue).join(',')).join('\r\n')],
      { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = `问数结果-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const scalar = result.rows.length === 1 && result.columns.length === 1;
  return <section className="result-card" aria-label="查询结果">
    <div className="result-heading"><Space><CheckCircleFilled className="success-icon" />
      <span>查询结果</span><Tag color="success">已完成</Tag></Space>
      <span className="result-count">{result.rows.length} 条结果</span></div>
    <Typography.Paragraph className="narrative">{result.answer}</Typography.Paragraph>
    {!result.rows.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有返回表格数据" /> :
      scalar ? <div className="scalar"><span>{result.columns[0]}</span>
        <strong>{String(result.rows[0][result.columns[0]] ?? '—')}</strong></div> :
      <Table size="middle" rowKey="__row_key"
        dataSource={result.rows.map((row, i) => ({ ...row, __row_key: i }))}
        columns={result.columns.map(name => ({ title: name, dataIndex: name, key: name,
          render: (value: unknown) => <span className="cell-text">{value == null ? '—' : String(value)}</span> }))}
        scroll={{ x: 'max-content' }} pagination={{ pageSize: 10, showSizeChanger: false,
          hideOnSinglePage: true, showTotal: total => `共 ${total} 条` }} />}
    {result.truncated && <Alert type="warning" showIcon title="结果达到查询行数上限，请缩小范围。" />}
    <div className="result-actions"><Space wrap>
      <Button size="small" type="text" aria-label="导出 CSV" icon={<DownloadOutlined />} onClick={exportCsv}>导出 CSV</Button>
      <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(result.answer)}>复制回答</Button>
    </Space><span className="muted">Wren · 发布 {result.publication_id}</span></div>
    <Collapse ghost size="small" items={[{ key: 'sql', label: <Space><CodeOutlined />查看 SQL 与数据来源</Space>, children: <>
      <div className="sql-toolbar"><Tag>DuckDB · Wren</Tag>{result.dialect_sql && <Button size="small"
        icon={<CopyOutlined />} onClick={() => copy(result.dialect_sql!)}>复制 SQL</Button>}</div>
      <pre className="sql-code">{result.dialect_sql || result.logical_sql || '本次回答未执行 SQL'}</pre>
      <div className="evidence"><span>发布版本</span><code>{result.publication_id}</code>
        <span>来源</span><span>{result.sources.map(source =>
          `${source.source_name || source.dataset_id || source.model}${source.sheet ? ` / ${source.sheet}` : ''}`).join('；') || 'Wren 项目知识'}</span>
        <span>Wren 追踪</span><code>{result.trace_id}</code>
        {reply?.trace_id && <><span>平台追踪</span><code>{reply.trace_id}</code></>}
      </div></> }]} />
  </section>;
}
