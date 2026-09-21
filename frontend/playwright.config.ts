import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: '**/*.spec.ts', timeout: 45000, workers: 1,
  use: { baseURL: process.env.WEB_TEST_URL || 'http://127.0.0.1:18081', trace: 'retain-on-failure',
    launchOptions: process.env.PW_EXECUTABLE_PATH ? {
      executablePath: process.env.PW_EXECUTABLE_PATH,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote', '--single-process'],
    } : {},
  },
  reporter: [['list'], ['json', { outputFile: '../validation-web/browser-results.json' }]],
});
