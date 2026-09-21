import React from 'react';
import { test, expect } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import QueryApp from '../src/App';

function start() {
  return render(<ConfigProvider locale={zhCN}><AntApp><QueryApp /></AntApp></ConfigProvider>);
}
async function ask(text: string) {
  fireEvent.change(screen.getByLabelText('输入问题'), { target: { value: text } });
  const send = screen.getByRole('button', { name: '发送', exact: true });
  await waitFor(() => expect((send as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(send);
}

test('React → AgentScope HTTP → Wren结果，连续追问与恢复', async () => {
  let view = start();
  await screen.findAllByText('服务已连接');
  await ask('CHERY有多少人？');
  await waitFor(() => expect(document.querySelector('.scalar strong')?.textContent).toBe('775'), { timeout: 12000 });
  await waitFor(() => expect(document.querySelector('.progress-card')).toBeNull(), { timeout: 12000 });
  const result = document.querySelector('.result-card') as HTMLElement;
  fireEvent.click(within(result).getByText('查看 SQL 与数据来源'));
  await waitFor(() => expect(result.querySelector('.sql-code')?.textContent).toContain('SELECT'));
  expect(result.textContent).toContain('guests.xlsx / Guests');
  expect(result.textContent).toContain('publication-v1');
  const headers = { Authorization: 'Bearer demo-local-key' };
  const base = await fetch('/ui-api/bootstrap', { method: 'POST', headers }).then(r => r.json());
  const sid = localStorage.getItem(`aiq-last-session-${base.agent_id}-${base.workspace_id}`);
  const snapshot = await fetch(`/ui-api/sessions/${sid}/snapshot?agent_id=${base.agent_id}`, { headers }).then(r => r.json());
  expect(snapshot.progress.stages.some((s: { stage: string }) => s.stage === 'call_wren')).toBe(true);
  expect(snapshot.progress.stages.some((s: { module: string }) => s.module === 'query_execution')).toBe(false);
  expect(snapshot.progress.stages.some((s: { module: string }) => s.module === 'question_understanding')).toBe(false);
  view.unmount(); view = start();
  await waitFor(() => expect(document.querySelectorAll('.scalar strong')).toHaveLength(1), { timeout: 10000 });
  expect(document.querySelector('.scalar strong')?.textContent).toBe('775');
  await ask('其中参加主题大会的呢？');
  await waitFor(() => expect(document.querySelector('.progress-card')).toBeNull(), { timeout: 12000 });
  await waitFor(() => expect([...document.querySelectorAll('.scalar strong')].at(-1)?.textContent).toBe('656'), { timeout: 12000 });
  await waitFor(() => expect(document.querySelector('.progress-card')).toBeNull(), { timeout: 12000 });
});

test('动态表格从真实数据取 15 行并分页', async () => {
  start(); await screen.findAllByText('服务已连接');
  await ask('按邀请国家统计报名人数');
  await screen.findByRole('table', {}, { timeout: 12000 });
  await waitFor(() => expect(document.querySelector('.progress-card')).toBeNull(), { timeout: 12000 });
  expect(document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length).toBe(10);
  fireEvent.click(document.querySelector('.ant-pagination-item-2')!);
  await waitFor(() => expect(document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length).toBe(5));
});

test('停止通过原生中断接口结束，不自动重发', async () => {
  start(); await screen.findAllByText('服务已连接'); await ask('停止测试');
  const stop = await screen.findByRole('button', { name: '停止', exact: true });
  await waitFor(() => expect((stop as HTMLButtonElement).disabled).toBe(false));
  await waitFor(() => expect(document.querySelector('.progress-card')).not.toBeNull());
  fireEvent.click(stop);
  await screen.findByText('本次请求已停止。', {}, { timeout: 12000 });
  expect(document.querySelectorAll('.user-bubble').length).toBe(1);
});
