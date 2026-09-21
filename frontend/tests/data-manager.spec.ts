import { expect, test } from '@playwright/test';

const guests = {
  dataset_id: 'guests', source_name: 'guests.xlsx', content_hash: 'abc',
  tables: [{
    sheet: 'Guests', model: 'guest_model', table: 'guest_table', row_count: 2,
    columns: [{ name: 'guest_id', type: 'VARCHAR' }],
  }],
};
const events = {
  dataset_id: 'events', source_name: 'events.xlsx', content_hash: 'def',
  tables: [{
    sheet: 'Events', model: 'event_model', table: 'event_table', row_count: 3,
    columns: [{ name: 'guest_id', type: 'VARCHAR' }],
  }],
};

test('浏览器完成多文件上传、关系发布、按Excel移除和回滚', async ({ page }) => {
  const operations: string[] = [];
  let active: any = {
    workspace_id: 'conference-test', publication_id: 'p2', changed: false,
    datasets: [guests, events], relationships: [],
  };
  await page.route('**/api/v1/workspaces/conference-test/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (method === 'GET' && path.endsWith('/datasets')) {
      return route.fulfill({ json: active });
    }
    if (method === 'GET' && path.endsWith('/publications')) {
      return route.fulfill({ json: [
        { publication_id: active.publication_id, created_at: '2026-09-21T00:00:00Z', active: true, datasets: active.datasets },
        { publication_id: 'p1', created_at: '2026-09-20T00:00:00Z', active: false, datasets: [guests, events] },
      ] });
    }
    if (method === 'POST' && path.endsWith('/uploads')) {
      operations.push('upload');
      active = { ...active, publication_id: 'p3', changed: true };
      return route.fulfill({ json: active });
    }
    if (method === 'POST' && path.endsWith('/relationships')) {
      operations.push('relationship');
      active = { ...active, publication_id: 'p4', changed: true, relationships: [{
        name: 'events_guests', models: ['event_model', 'guest_model'], join_type: 'MANY_TO_ONE',
        condition: 'event_model.guest_id = guest_model.guest_id',
      }] };
      return route.fulfill({ json: active });
    }
    if (method === 'DELETE' && path.endsWith('/datasets/guests')) {
      operations.push('remove');
      active = { ...active, publication_id: 'p5', changed: true, datasets: [events], relationships: [] };
      return route.fulfill({ json: active });
    }
    if (method === 'POST' && path.endsWith('/publications/p1/activate')) {
      operations.push('rollback');
      active = { ...active, publication_id: 'p1', changed: true, datasets: [guests, events] };
      return route.fulfill({ json: active });
    }
    return route.abort();
  });

  await page.goto('/');
  await page.getByRole('button', { name: '管理 Excel 与版本' }).click();
  await expect(page.getByRole('dialog')).toContainText('guests.xlsx');

  await page.locator('input[type="file"]').setInputFiles([
    { name: 'guests.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('xlsx') },
    { name: 'events.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('xlsx') },
  ]);
  await page.getByRole('button', { name: /上传并发布/ }).click();
  await expect.poll(() => operations).toContain('upload');

  await page.getByText('表关系 (0)').click();
  for (const [label, option] of [
    ['左表模型', 'Events · event_model'], ['左表字段', 'guest_id'],
    ['右表模型', 'Guests · guest_model'], ['右表字段', 'guest_id'],
  ]) {
    await page.getByLabel(label).click();
    await page.locator(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option',
    ).filter({ hasText: option }).last().click();
  }
  await page.getByRole('button', { name: '验证并发布关系' }).click();
  await expect.poll(() => operations).toContain('relationship');

  await page.getByRole('tab', { name: 'Excel 数据' }).click();
  await page.locator('.dataset-item').filter({ hasText: 'guests.xlsx' }).getByRole('button', { name: '移除' }).click();
  await page.getByRole('button', { name: '移除并发布' }).click();
  await expect.poll(() => operations).toContain('remove');

  await page.getByText(/版本历史/).click();
  await page.locator('.publication-item').filter({ hasText: 'p1' }).getByRole('button', { name: '回滚到此版本' }).click();
  await page.getByRole('button', { name: '确认切换' }).click();
  await expect.poll(() => operations).toEqual(['upload', 'relationship', 'remove', 'rollback']);
  await expect(page.getByText(/已激活 p1/)).toBeVisible();
});
