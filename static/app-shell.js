/* ZEEP shared application shell.
 *
 * Owns route presentation, in-app navigation and fullscreen/focus mode for
 * every role. Device controls remain in index.html until their APIs are split
 * into dedicated modules; keeping this shell independent makes that later
 * refactor incremental rather than a risky all-at-once rewrite.
 */
(function initialiseZeepAppShell(window, document) {
  'use strict';

  // DOM markers make field diagnostics possible without exposing internals or
  // relying on console access from the tablet browser.
  document.documentElement.dataset.appShell = 'loading';

  const USER_APP_VIEWS = new Set(['dashboard', 'control', 'sessions']);
  const FULLSCREEN_APP_VIEWS = new Set([
    'dashboard', 'control', 'monitor', 'sessions',
  ]);
  const PAGE_DEFINITIONS = Object.freeze({
    dashboard: {
      title: 'สุขภาพและสภาพแวดล้อม',
      subtitle: 'ดูสุขภาพผู้ใช้งานและสภาพแวดล้อมภายในตู้',
      document: 'Dashboard',
    },
    control: {
      title: 'ศูนย์ควบคุม ZEEP',
      subtitle: 'เลือกและควบคุมอุปกรณ์ภายในตู้จากจุดเดียว',
      document: 'Environment Control',
    },
    control_debug: {
      title: 'Control Debug',
      subtitle: 'ทดสอบคำสั่งอุปกรณ์และตรวจ Request, ACK และ Response',
      document: 'Control Debug',
    },
    monitor: {
      title: 'สถานะระบบ',
      subtitle: 'ตรวจความพร้อมของระบบ Sensor และเหตุการณ์ผิดปกติ',
      document: 'Monitor & Logs',
    },
    sessions: {
      title: 'ประวัติการนอน',
      subtitle: 'ดู Session และผลการนอนย้อนหลังของผู้ใช้งาน',
      document: 'Sessions & Reports',
    },
  });

  let fullscreenManaged = false;

  function setIcon(svg, name) {
    const use = svg?.querySelector('use');
    if (use) use.setAttribute('href', `#ui-icon-${name}`);
  }

  function notify(message, type = 'info', duration = 2000) {
    if (typeof window.toast === 'function') window.toast(message, type, duration);
  }

  function syncFullscreenButton() {
    const button = document.getElementById('appFullscreenBtn');
    if (!button) return;
    const active = document.body.classList.contains('control-focus-mode');
    setIcon(button.querySelector('.ui-icon'), active ? 'fullscreen-exit' : 'fullscreen');
    const label = button.querySelector('[data-fullscreen-label]');
    if (label) label.textContent = active ? 'ย่อจอ' : 'เต็มจอ';
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    button.setAttribute('aria-label', active ? 'ออกจากแอปแบบเต็มจอ' : 'เปิดแอปแบบเต็มจอ');
    button.title = active ? 'แสดง Header และออกจากเต็มจอ' : 'เปิดทุกหน้าแบบเต็มจอ';
  }

  async function toggleFullscreen() {
    const entering = !document.body.classList.contains('control-focus-mode');
    if (entering) {
      document.body.classList.add('control-focus-mode');
      syncFullscreenButton();
      const request = document.documentElement.requestFullscreen
        || document.documentElement.webkitRequestFullscreen;
      if (!request) {
        notify('ซ่อน Header แล้ว', 'ok', 1600);
        return;
      }
      try {
        await request.call(document.documentElement, {navigationUI: 'hide'});
        fullscreenManaged = true;
        notify('เปิดมุมมองเต็มจอแล้ว', 'ok', 1600);
      } catch (_error) {
        // Focus Mode is still useful when an embedded browser rejects the
        // native fullscreen request.
        fullscreenManaged = false;
        notify('ซ่อน Header แล้ว · เบราว์เซอร์ไม่อนุญาตเต็มจอ', 'warning', 2400);
      }
      return;
    }

    document.body.classList.remove('control-focus-mode');
    fullscreenManaged = false;
    syncFullscreenButton();
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if ((document.fullscreenElement || document.webkitFullscreenElement) && exit) {
      try { await exit.call(document); } catch (_error) { /* no-op */ }
    }
  }

  function requestedView() {
    const path = window.location.pathname.replace(/^\/+|\/+$/g, '');
    const preview = new URLSearchParams(window.location.search).get('view');
    const routeView = path === 'admin' || path === 'admin/login'
      ? 'control'
      : path === 'login' ? 'dashboard'
      : path === 'control-debug' ? 'control_debug' : path;
    const previewView = preview === 'control-debug' ? 'control_debug' : preview;
    const candidate = PAGE_DEFINITIONS[previewView] ? previewView : routeView;
    return PAGE_DEFINITIONS[candidate] ? candidate : 'dashboard';
  }

  function applyPageView() {
    const view = requestedView();
    document.body.dataset.view = view;
    document.querySelectorAll('[data-pages]').forEach((element) => {
      const visible = element.dataset.pages.split(/\s+/).includes(view);
      element.classList.toggle('page-hidden', !visible);
    });
    const navView = view === 'control_debug' ? 'control' : view;
    document.querySelectorAll('.main-nav a').forEach((anchor) => {
      anchor.classList.toggle('active', anchor.dataset.view === navView);
    });
    const page = PAGE_DEFINITIONS[view];
    document.title = `${page.document} · ZEEP`;
    const heading = document.getElementById('pageTitle');
    const subtitle = document.getElementById('pageSubtitle');
    if (heading) heading.textContent = page.title;
    if (subtitle) subtitle.textContent = page.subtitle;
    syncFullscreenButton();
    if (typeof window.updateAlertButton === 'function') window.updateAlertButton();
    return view;
  }

  function switchAppView(path, {replace = false} = {}) {
    const target = String(path || '').replace(/^\/+|\/+$/g, '') || 'dashboard';
    if (!FULLSCREEN_APP_VIEWS.has(target)) return false;
    const method = replace ? 'replaceState' : 'pushState';
    window.history[method]({zeepView: target}, '', `/${target}`);
    applyPageView();
    if (target === 'sessions' && typeof window.refreshHistory === 'function') {
      window.refreshHistory();
    }
    window.scrollTo({top: 0, left: 0, behavior: 'auto'});
    return true;
  }

  document.querySelector('.main-nav')?.addEventListener('click', (event) => {
    const link = event.target.closest('a[data-view]');
    if (!link || event.defaultPrevented || event.button !== 0
        || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const userRoute = document.body.dataset.role === 'user'
      && USER_APP_VIEWS.has(link.dataset.view);
    const fullscreenRoute = document.body.classList.contains('control-focus-mode')
      && FULLSCREEN_APP_VIEWS.has(link.dataset.view);
    if (!userRoute && !fullscreenRoute) return;
    event.preventDefault();
    switchAppView(new URL(link.href, window.location.href).pathname);
  });

  window.addEventListener('popstate', () => {
    const view = applyPageView();
    if (view === 'sessions' && typeof window.refreshHistory === 'function') {
      window.refreshHistory();
    }
  });

  document.addEventListener('fullscreenchange', () => {
    if (fullscreenManaged && !document.fullscreenElement) {
      fullscreenManaged = false;
      document.body.classList.remove('control-focus-mode');
    }
    syncFullscreenButton();
  });

  // Backward-compatible globals keep existing inline handlers and tests small.
  window.applyPageView = applyPageView;
  window.switchAppView = switchAppView;
  window.syncAppFullscreenButton = syncFullscreenButton;
  window.toggleAppFullscreen = toggleFullscreen;
  window.ZeepAppShell = Object.freeze({
    applyPageView,
    switchAppView,
    syncFullscreenButton,
    toggleFullscreen,
    pageDefinitions: PAGE_DEFINITIONS,
  });
  document.documentElement.dataset.appShell = 'ready';
}(window, document));
