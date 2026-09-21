import { test, expect } from '@playwright/test';

test('桌面：Wren结果、SQL来源、历史恢复与重命名', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  await expect(page.getByText('一句话就能查。')).toBeVisible();
  await expect(page.getByText('服务已连接')).toBeVisible();
  await page.screenshot({ path: '../validation-web/desktop-welcome.png', fullPage: true });
  await page.getByRole('button', { name: /嘉宾统计/ }).click();
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.scalar strong').first()).toHaveText('775');
  await page.locator('.result-card').last().getByText('查看 SQL 与数据来源').click();
  await expect(page.locator('.sql-code').last()).toContainText('SELECT');
  await expect(page.locator('.result-card').last()).toContainText('publication-v1');
  await expect(page.locator('.result-card').last()).toContainText('guests.xlsx / Guests');
  const download = page.waitForEvent('download');
  await page.locator('.result-card').last().getByRole('button', { name: '导出 CSV' }).click();
  expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  await page.screenshot({ path: '../validation-web/desktop-query.png', fullPage: true });
  await page.reload();
  await expect(page.locator('.scalar strong').last()).toHaveText('775');
  await page.getByRole('button', { name: /管理会话 CHERY/ }).first().click();
  await page.getByText('重命名', { exact: true }).click();
  await page.getByLabel('会话名称').fill('峰会参会统计');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.locator('.conversation-title')).toContainText('峰会参会统计');
  expect(errors).toEqual([]);
});

test('手机：抽屉会话、多轮追问、停止与布局无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByText('一句话就能查。')).toBeVisible();
  await page.screenshot({ path: '../validation-web/mobile-welcome.png', fullPage: true });
  await page.getByLabel('输入问题').fill('CHERY有多少人？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.scalar strong').last()).toHaveText('775');
  await page.getByLabel('输入问题').fill('其中参加主题大会的呢？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.scalar strong').last()).toHaveText('656');
  await page.screenshot({ path: '../validation-web/mobile-query.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '打开会话菜单' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: '新建会话', exact: true }).click();
  await page.getByLabel('输入问题').fill('停止测试');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '停止', exact: true }).click();
  await expect(page.getByText('本次请求已停止。')).toBeVisible({ timeout: 15000 });
});

test('动态表格分页与服务断连可见', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('输入问题').fill('按邀请国家统计报名人数');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText('共 15 条')).toBeVisible();
  await page.getByTitle('2', { exact: true }).click();
  await expect(page.locator('.ant-table-tbody tr.ant-table-row')).toHaveCount(5);
  await page.route('**/ui-api/**', route => route.abort());
  await expect(page.getByText(/连接暂时中断/)).toBeVisible({ timeout: 15000 });
});
