import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { transferableAbortController } from 'node:util';
// 仅替代 jsdom 不具备的布局 API；fetch 连接真实本地后端。
Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(query => ({
  matches: query.includes('min-width: 769px'), media: query, onchange: null,
  addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
})) });
class Observer { observe() {} unobserve() {} disconnect() {} }
Object.defineProperty(window, 'ResizeObserver', { value: Observer });
Object.defineProperty(globalThis, 'ResizeObserver', { value: Observer });
Element.prototype.scrollIntoView = vi.fn();
const originalStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = element => originalStyle(element);
const originalFetch = globalThis.fetch;
globalThis.fetch = (input, init) => {
  // 将 jsdom 的 AbortSignal 转成 Node fetch 接受的原生信号。
  const controller = transferableAbortController();
  if (init?.signal?.aborted) controller.abort();
  init?.signal?.addEventListener('abort', () => controller.abort(), { once: true });
  return originalFetch(new URL(String(input), process.env.WEB_TEST_URL || 'http://127.0.0.1:18081').href, { ...init, signal: controller.signal });
};
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); });
