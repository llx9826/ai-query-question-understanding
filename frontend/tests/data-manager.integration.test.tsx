import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { api } from '../src/api';
import { DataManager } from '../src/components/DataManager';

const guests = {
  dataset_id: 'guests',
  source_name: 'guests.xlsx',
  content_hash: 'abc',
  tables: [{
    sheet: 'Guests', model: 'guest_model', table: 'guest_table', row_count: 2,
    columns: [{ name: 'guest_id', type: 'VARCHAR' }],
  }],
};
const events = {
  dataset_id: 'events',
  source_name: 'events.xlsx',
  content_hash: 'def',
  tables: [{
    sheet: 'Events', model: 'event_model', table: 'event_table', row_count: 3,
    columns: [{ name: 'guest_id', type: 'VARCHAR' }],
  }],
};
const active = {
  workspace_id: 'conference-a', publication_id: 'p2', changed: false,
  datasets: [guests, events], relationships: [],
};

afterEach(() => vi.restoreAllMocks());

async function selectOption(label: string, optionText: string) {
  fireEvent.mouseDown(screen.getByLabelText(label));
  let option: Element | undefined;
  await waitFor(() => {
    const openDropdowns = [...document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden)',
    )];
    const dropdown = openDropdowns.at(-1);
    option = dropdown
      ? [...dropdown.querySelectorAll('.ant-select-item-option')]
        .find(item => item.textContent?.trim() === optionText)
      : undefined;
    expect(Boolean(option)).toBe(true);
  });
  fireEvent.click(option!);
}

test('管理端展示模型状态、上传、按Excel移除和版本回滚', async () => {
  vi.spyOn(api, 'datasets').mockResolvedValue(active);
  vi.spyOn(api, 'publications').mockResolvedValue([
    { publication_id: 'p2', created_at: '2026-09-21T00:00:00Z', active: true, datasets: [guests] },
    { publication_id: 'p1', created_at: '2026-09-20T00:00:00Z', active: false, datasets: [guests] },
  ]);
  const upload = vi.spyOn(api, 'upload').mockResolvedValue({ ...active, publication_id: 'p3', changed: true });
  const remove = vi.spyOn(api, 'removeDataset').mockResolvedValue({ ...active, publication_id: 'p4', changed: true, datasets: [] });
  const activate = vi.spyOn(api, 'activatePublication').mockResolvedValue({ ...active, publication_id: 'p1', changed: true });
  const relationship = vi.spyOn(api, 'addRelationship').mockResolvedValue({
    ...active,
    publication_id: 'p-rel',
    changed: true,
    relationships: [{
      name: 'events_guests', models: ['event_model', 'guest_model'],
      join_type: 'MANY_TO_ONE', condition: 'event_model.guest_id = guest_model.guest_id',
    }],
  });
  const published = vi.fn();

  render(<ConfigProvider locale={zhCN}><AntApp><DataManager
    open workspaceId="conference-a" onClose={() => undefined} onPublished={published}
  /></AntApp></ConfigProvider>);

  await screen.findByText('guests.xlsx');
  expect(screen.getByText('guest_model')).toBeTruthy();
  const file = new File(['xlsx'], 'events.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } });
  fireEvent.click(await screen.findByRole('button', { name: /上传并发布/ }));
  await waitFor(() => expect(upload).toHaveBeenCalledWith('conference-a', [file]));

  fireEvent.click(screen.getByText('表关系 (0)'));
  await selectOption('左表模型', 'Events · event_model');
  await selectOption('左表字段', 'guest_id');
  await selectOption('右表模型', 'Guests · guest_model');
  await selectOption('右表字段', 'guest_id');
  const publishRelationship = screen.getByRole('button', { name: '验证并发布关系' });
  await waitFor(() => expect((publishRelationship as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(publishRelationship);
  await waitFor(() => expect(relationship).toHaveBeenCalledWith('conference-a', {
    left_model: 'event_model', left_column: 'guest_id',
    right_model: 'guest_model', right_column: 'guest_id', join_type: 'MANY_TO_ONE',
  }));

  fireEvent.click(screen.getByText('Excel 数据'));
  fireEvent.click(screen.getAllByRole('button', { name: /移除/ })[0]);
  fireEvent.click(await screen.findByRole('button', { name: '移除并发布' }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith('conference-a', 'guests'));

  fireEvent.click(screen.getByText('版本历史 (2)'));
  fireEvent.click(await screen.findByRole('button', { name: /回滚到此版本/ }));
  fireEvent.click(await screen.findByRole('button', { name: '确认切换' }));
  await waitFor(() => expect(activate).toHaveBeenCalledWith('conference-a', 'p1'));
  expect(published).toHaveBeenCalledTimes(4);
});
