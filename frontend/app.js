const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { token: localStorage.getItem('stb_token') || '', user: null, assistantHistory: [], assistantAvailable: false };

function deviceId() {
  let id = localStorage.getItem('stb_device_id');
  if (!id) {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    id = [...bytes].map((x) => x.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('stb_device_id', id);
  }
  return id;
}

function deviceLabel() {
  return `${navigator.platform || 'Browser'} · ${window.matchMedia('(max-width: 700px)').matches ? 'Mobile' : 'Desktop'} App`;
}

function toast(message) {
  const element = $('#toast');
  if (!element) return;
  element.textContent = message;
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), 3800);
}

function showMessage(message, ok = true) {
  const element = $('#authMessage');
  element.textContent = message;
  element.className = `message ${ok ? 'success' : 'error'}`;
  element.classList.remove('hidden');
}

function clearMessage() {
  $('#authMessage').classList.add('hidden');
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let data = {};
  try { data = await response.json(); } catch { /* non-JSON error body */ }
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function hideAll() {
  ['landing', 'authViews', 'customerApp'].forEach((id) => $(`#${id}`).classList.add('hidden'));
  $('#logoutBtn').classList.add('hidden');
}

function showAuth(view = 'register') {
  hideAll();
  $('#authViews').classList.remove('hidden');
  $('#logoutBtn').classList.remove('hidden');
  $$('.form-view').forEach((form) => form.classList.add('hidden'));
  $$('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.view === view));
  const copy = {
    register: ['إنشاء حساب جديد', 'ابدأ دون رسوم اشتراك أو تفعيل.'],
    login: ['مرحبًا بعودتك', 'سجّل الدخول من الجهاز المعتمد.'],
  };
  $('#authTitle').textContent = copy[view][0];
  $('#authDescription').textContent = copy[view][1];
  const formId = { register: 'registerForm', login: 'loginForm' }[view];
  $(`#${formId}`).classList.remove('hidden');
  clearMessage();
}

function showLanding() {
  hideAll();
  $('#landing').classList.remove('hidden');
}

function showSection(sectionId) {
  $$('#customerApp .content-section').forEach((section) => section.classList.toggle('hidden', section.id !== sectionId));
  $$('#customerApp .nav-item').forEach((button) => button.classList.toggle('active', button.dataset.section === sectionId));
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

async function loadCustomer() {
  state.assistantHistory = [];
  $('#assistantMessages').replaceChildren();
  appendAssistantMessage('assistant', 'مرحبًا! يمكنني شرح بيانات حسابك ومساعدتك في فهم الأخبار والصفقات، عندما يتم إعداد مزود الذكاء الاصطناعي.');
  $('#assistantConsent').checked = false;
  hideAll();
  $('#customerApp').classList.remove('hidden');
  $('#logoutBtn').classList.remove('hidden');
  const user = await api('/api/account');
  if (user.role !== 'customer') throw new Error('هذه الواجهة مخصصة لحسابات العملاء.');
  state.user = user;
  $('#userName').textContent = user.full_name;
  $('#userEmail').textContent = user.email;
  $('#userInitial').textContent = (user.full_name || 'ع').trim()[0];
  $('#licenseStatus').textContent = user.license_status || '—';

  const dashboard = await api('/api/customer/dashboard');
  $('#tradeCount').textContent = dashboard.trade_count;
  $('#winningTrades').textContent = dashboard.winning_trades;
  const netValues = Object.entries(dashboard.net_profit_by_currency || {});
  $('#netProfit').textContent = netValues.length
    ? netValues.map(([currency, value]) => `${Number(value).toFixed(2)} ${currency}`).join(' / ')
    : '0.00';
  $('#feesDue').textContent = Object.entries(dashboard.performance_fees_due || {})
    .map(([currency, value]) => `${Number(value).toFixed(2)} ${currency}`).join(' / ') || '0.00';
  $('#mt5State').textContent = dashboard.mt5_connected ? 'متصل' : 'غير متصل';
  $('#autoTradingEnabled').checked = !!dashboard.auto_trading_enabled;
  $('#riskDisclosure').checked = !!dashboard.auto_trading_enabled;
  $('#liveTradingEnabled').checked = !!dashboard.live_trading_customer_consented;
  $('#liveRiskDisclosure').checked = !!dashboard.live_trading_customer_consented;
  const referral = await api('/api/referral').catch(() => null);
  if (referral) $('#referralUrl').value = referral.referral_url;
  await Promise.all([
    loadTrades(), loadSignals(), loadIntelligence(),
    loadAssistantStatus().catch(() => {
      state.assistantAvailable = false;
      $('#assistantStatusText').textContent = 'تعذر التحقق من إعداد المساعد؛ تظل المحادثة معطلة.';
      $('#assistantConsent').disabled = true;
      $('#assistantQuestion').disabled = true;
      $('#assistantSend').disabled = true;
    }),
  ]);
}

async function loadSignals() {
  const rows = await api('/api/customer/signals');
  $('#signalsBody').innerHTML = rows.length ? rows.map((signal) => `
    <tr><td>${esc(signal.symbol)}</td><td>${esc(signal.timeframe)}</td><td>${esc(signal.direction)}</td>
    <td>${Math.round(Number(signal.confidence) * 100)}%</td><td>${Number(signal.entry_price).toFixed(5)}</td>
    <td>${Number(signal.stop_loss).toFixed(5)}</td><td>${Number(signal.take_profit).toFixed(5)}</td>
    <td>${new Date(signal.bar_time).toLocaleString('ar-EG')}</td></tr>`).join('')
    : '<tr><td colspan="8" class="empty">لا توجد إشارات حتى الآن.</td></tr>';
}

async function loadTrades() {
  const rows = await api('/api/customer/trades');
  $('#tradesBody').innerHTML = rows.length ? rows.map((trade) => `
    <tr><td>${esc(trade.symbol)}</td><td>${esc(trade.side)}</td><td>${Number(trade.volume).toFixed(2)}</td>
    <td>${Number(trade.net_profit).toFixed(2)} ${esc(trade.currency)}</td>
    <td>${Number(trade.fee_amount).toFixed(2)} ${esc(trade.currency)}</td>
    <td>${new Date(trade.closed_at).toLocaleString('ar-EG')}</td></tr>`).join('')
    : '<tr><td colspan="6" class="empty">لا توجد صفقات مسجلة بعد.</td></tr>';
}

async function loadIntelligence() {
  const rows = await api('/api/customer/intelligence');
  $('#intelligenceList').innerHTML = rows.length ? rows.map((item) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(item.title)}</h4>
    <p>المصدر: ${esc(item.source)} · ${new Date(item.published_at).toLocaleString('ar-EG')}</p></div>
    <span class="status-tag">${esc(item.type === 'news' ? 'خبر' : item.type === 'market_event' ? 'حدث سوق' : 'رسالة بوت')}</span></div>
    <p>${esc(item.summary || 'لا يوجد ملخص')}</p><p class="muted">محتوى خارجي غير متحقق منه · لا يمكنه تشغيل الصفقات</p>
    ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">فتح المصدر الأصلي</a>` : ''}</article>`).join('')
    : '<div class="surface-card muted">لا توجد أخبار أو رسائل واردة حتى الآن. ستظهر هنا بعد ربط المصادر.</div>';
}

async function loadAssistantStatus() {
  const status = await api('/api/customer/assistant/status');
  state.assistantAvailable = !!status.available;
  $('#assistantStatusText').textContent = status.available
    ? 'المساعد متاح. اطرح سؤالك عن حسابك أو الأخبار والصفقات.'
    : 'المساعد غير مفعّل بعد؛ يحتاج إلى إعداد مزود نموذج ذكاء اصطناعي على الخادم.';
  $('#assistantConsent').disabled = !state.assistantAvailable;
  $('#assistantQuestion').disabled = !state.assistantAvailable;
  $('#assistantSend').disabled = true;
}

function appendAssistantMessage(role, content, sources = []) {
  const container = $('#assistantMessages');
  const bubble = document.createElement('div');
  bubble.className = `assistant-message ${role}`;
  bubble.textContent = content;
  container.appendChild(bubble);
  if (sources.length) {
    const links = document.createElement('div');
    links.className = 'assistant-sources';
    for (const source of sources.slice(0, 5)) {
      if (!source.url) continue;
      try {
        const url = new URL(source.url);
        if (url.protocol !== 'https:') continue;
        const link = document.createElement('a');
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.textContent = `${source.name}: ${source.title}`;
        links.appendChild(link);
      } catch { /* ignore invalid source URLs */ }
    }
    if (links.childNodes.length) container.appendChild(links);
  }
  container.scrollTop = container.scrollHeight;
}

async function afterLogin(data) {
  if (!data.user || data.user.role !== 'customer') throw new Error('تسجيل الدخول العام متاح للعملاء فقط.');
  state.token = data.access_token;
  localStorage.setItem('stb_token', state.token);
  await loadCustomer();
}

$$('[data-view]').forEach((button) => button.addEventListener('click', () => showAuth(button.dataset.view)));
$$('.nav-item').forEach((button) => button.addEventListener('click', () => showSection(button.dataset.section)));
$$('[data-section-link]').forEach((button) => button.addEventListener('click', () => showSection(button.dataset.section)));

$('#registerForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage();
  const body = Object.fromEntries(new FormData(event.target).entries());
  if (body.password !== body.password_confirm) { showMessage('كلمتا المرور غير متطابقتين.', false); return; }
  delete body.password_confirm;
  body.device_id = deviceId(); body.device_label = deviceLabel();
  try {
    await afterLogin(await api('/api/auth/register', { method: 'POST', body: JSON.stringify(body) }));
    toast('تم إنشاء الحساب المجاني بنجاح');
  } catch (error) { showMessage(error.message, false); }
});

$('#loginForm').addEventListener('submit', async (event) => {
  event.preventDefault(); clearMessage();
  const body = Object.fromEntries(new FormData(event.target).entries());
  body.device_id = deviceId(); body.device_label = deviceLabel();
  try { await afterLogin(await api('/api/auth/login', { method: 'POST', body: JSON.stringify(body) })); }
  catch (error) { showMessage(error.message, false); }
});

$('#mt5Form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target).entries());
  try {
    const result = await api('/api/mt5/link', { method: 'POST', body: JSON.stringify(body) });
    $('#mt5LinkResult').textContent = `${result.link_code} · صالح حتى ${new Date(result.expires_at).toLocaleTimeString('ar-EG')}`;
    $('#mt5LinkResult').classList.remove('hidden');
    toast('تم إنشاء رمز ربط MT5');
  } catch (error) { toast(error.message); }
});

$('#assistantConsent').addEventListener('change', () => {
  $('#assistantSend').disabled = !(state.assistantAvailable && $('#assistantConsent').checked);
});

$('#assistantChatForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.assistantAvailable || !$('#assistantConsent').checked) return;
  const question = $('#assistantQuestion').value.trim();
  if (!question) return;
  $('#assistantQuestion').value = '';
  $('#assistantSend').disabled = true;
  appendAssistantMessage('user', question);
  try {
    const result = await api('/api/customer/assistant/chat', {
      method: 'POST',
      body: JSON.stringify({ message: question, history: state.assistantHistory.slice(-8), consent_external_ai: true }),
    });
    appendAssistantMessage('assistant', result.answer, result.sources || []);
    state.assistantHistory.push({ role: 'user', content: question }, { role: 'assistant', content: result.answer });
    state.assistantHistory = state.assistantHistory.slice(-8);
  } catch (error) {
    appendAssistantMessage('error', `تعذر الحصول على إجابة: ${error.message}`);
  } finally {
    $('#assistantSend').disabled = !(state.assistantAvailable && $('#assistantConsent').checked);
  }
});

$('#refreshTrades').addEventListener('click', () => loadTrades().catch((error) => toast(error.message)));
$('#refreshIntelligence').addEventListener('click', () => loadIntelligence().catch((error) => toast(error.message)));
$('#tradingSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const enabled = $('#autoTradingEnabled').checked;
  const accepted = $('#riskDisclosure').checked;
  const liveEnabled = $('#liveTradingEnabled').checked;
  const liveAccepted = $('#liveRiskDisclosure').checked;
  try {
    const result = await api('/api/customer/trading-settings', {
      method: 'POST', body: JSON.stringify({
        auto_trading_enabled: enabled, accept_risk_disclosure: accepted,
        live_trading_enabled: liveEnabled, accept_live_risk_disclosure: liveAccepted,
      }),
    });
    $('#tradingPolicyNote').textContent = result.live_execution_available
      ? 'موافقتك على التداول الحقيقي محفوظة. لا يبدأ التنفيذ إلا إذا كان خادم المالك وWindows MT5 Agent مفتوحين واجتازت جميع فحوص المخاطر.'
      : liveEnabled
        ? 'تم حفظ موافقتك المستقلة، لكن التداول الحقيقي ما زال مغلقًا على الخادم أو في إعدادات Windows MT5 Agent.'
        : 'تم حفظ إعدادات التداول. يمكن تشغيل DEMO وفق الترخيص والموافقة؛ التداول الحقيقي لم تطلب تفعيله.';
    toast('تم حفظ إعدادات التداول');
  } catch (error) { toast(error.message); }
});

$('#copyReferral').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#referralUrl').value); toast('تم نسخ رابط الإحالة'); }
  catch { toast('تعذر النسخ من المتصفح'); }
});

$('#logoutBtn').addEventListener('click', async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* local logout still proceeds */ }
  state.token = ''; state.user = null; state.assistantHistory = []; $('#assistantMessages').replaceChildren(); $('#assistantConsent').checked = false; localStorage.removeItem('stb_token'); showLanding(); toast('تم تسجيل الخروج');
});

async function boot() {
  const referralCode = new URLSearchParams(location.search).get('ref');
  if (referralCode) $('#referralCode').value = referralCode;
  const health = await fetch('/api/health').then((response) => response.json()).catch(() => null);
  if (!health) $('#connection').innerHTML = '<i style="background:#ff7481"></i> تعذر الاتصال';
  if (state.token) {
    try {
      const user = await api('/api/account');
      if (user.role === 'customer') { await loadCustomer(); return; }
    } catch { /* invalid token */ }
    state.token = ''; localStorage.removeItem('stb_token');
  }
  showLanding();
}

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
boot();


// SUPER_TRADING_INSTALL_V1
(() => {
  let installPrompt = null;
  const button = document.getElementById('installAppBtn');
  const help = document.getElementById('installHelp');
  if (!button) return;

  const isInstalled = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

  if (isInstalled()) button.classList.add('hidden');

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installPrompt = event;
    button.classList.remove('hidden');
    button.textContent = '⬇ تثبيت التطبيق';
  });

  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    button.classList.add('hidden');
    if (help) {
      help.textContent = 'تم تثبيت التطبيق بنجاح.';
      help.classList.remove('hidden');
    }
  });

  button.addEventListener('click', async () => {
    if (installPrompt) {
      installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      installPrompt = null;
      if (help) {
        help.textContent = choice.outcome === 'accepted'
          ? 'تم قبول طلب التثبيت.'
          : 'لم يتم التثبيت. يمكنك المحاولة لاحقًا من قائمة Chrome.';
        help.classList.remove('hidden');
      }
      return;
    }

    if (help) {
      help.textContent = 'لتثبيت التطبيق: افتح قائمة Chrome (⋮)، ثم اختر "تثبيت التطبيق" أو "إضافة إلى الشاشة الرئيسية" إذا ظهر الخيار. إذا لم يظهر، تأكد من فتح الموقع عبر HTTPS أو localhost وأن التطبيق مستوفٍ لشروط التثبيت.';
      help.classList.remove('hidden');
    }
  });
})();
