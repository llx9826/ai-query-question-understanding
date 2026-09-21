// 截取实际运行页面；不替换接口、不注入演示查询结果。
import { chromium } from 'playwright';
const browser = await chromium.launch({ executablePath: process.env.PW_EXECUTABLE_PATH,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote', '--single-process'] });
try {
  const page = await browser.newPage();
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.goto(process.env.WEB_TEST_URL || 'http://127.0.0.1:18081');
    await page.getByText('一句话就能查。').waitFor();
    await page.getByText('已连接', { exact: true }).waitFor();
    await page.screenshot({ path: `../validation-web/${name}-welcome.png`, fullPage: true });
    console.log(`saved ${name} screenshot`);
  }
} finally { await browser.close(); }
