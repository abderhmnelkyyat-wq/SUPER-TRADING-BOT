const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { token: localStorage.getItem('stb_owner_token') || '' };

// Admin-only PWA installation; isolated from the customer application's PWA.
let ownerInstallPrompt = null;
const ownerInstallButton = $('#installOwnerAppBtn');
const ownerInstallHelp = $('#ownerInstallHelp');
window.addEventListener('beforeinstallprompt', (event) => { event.preventDefault(); ownerInstallPrompt = event; });
window.addEventListener('appinstalled', () => { ownerInstallPrompt = null; if (ownerInstallButton) { ownerInstallButton.textContent = '✓ تطبيق الأدمن مثبت'; ownerInstallButton.disabled = true; } toast('تم تثبيت تطبيق الأدمن بنجاح'); });
ownerInstallButton?.addEventListener('click', async () => {
  if (ownerInstallPrompt) {
    const installEvent = ownerInstallPrompt;
    ownerInstallPrompt = null;
    ownerInstallButton.disabled = true;
    ownerInstallButton.textContent = 'جارٍ التثبيت...';
    toast('جارٍ تجهيز تثبيت تطبيق الأدمن...');
    installEvent.prompt();
    const choice = await installEvent.userChoice;
    if (choice?.outcome === 'accepted') {
      toast('تم قبول طلب التثبيت. أكمل التأكيد في نافذة المتصفح.');
    } else {
      ownerInstallButton.disabled = false;
      ownerInstallButton.textContent = '⇩ تثبيت تطبيق الأدمن';
      toast('تم إلغاء التثبيت. يمكنك المحاولة مرة أخرى.');
    }
    return;
  }
  toast('التثبيت المباشر غير متاح في هذا المتصفح حاليًا.');
  if (ownerInstallHelp?.showModal) ownerInstallHelp.showModal();
  else alert('افتح قائمة المتصفح واختر تثبيت التطبيق أو إضافة إلى الشاشة الرئيسية.');
});
function closeOwnerInstallDialog() { if (ownerInstallHelp?.open) ownerInstallHelp.close(); }
$('#closeOwnerInstallHelp')?.addEventListener('click', closeOwnerInstallDialog);
$('#closeOwnerInstallHelpBtn')?.addEventListener('click', closeOwnerInstallDialog);
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/owner-console/sw.js', {scope:'/owner-console/'}).catch(() => toast('تعذر تفعيل وضع تثبيت تطبيق الأدمن؛ تحقق من HTTPS.')), {once:true});
}



function ownerDeviceId() {
  let value = localStorage.getItem('stb_owner_device');
  if (!value) {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    value = [...bytes].map((x) => x.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('stb_owner_device', value);
  }
  return value;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function money(value, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value || 0));
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), 4200);
}

function authMessage(message, ok = false) {
  const element = $('#ownerAuthMessage');
  element.textContent = message;
  element.className = `message ${ok ? 'success' : 'error'}`;
  element.classList.remove('hidden');
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let data = {};
  try { data = await response.json(); } catch { /* no JSON response */ }
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function showOwnerLogin() {
  $('#ownerAuth').classList.remove('hidden');
  $('#ownerApp').classList.add('hidden');
  $('#ownerLogoutBtn').classList.add('hidden');
}

function showOwnerConsole() {
  $('#ownerAuth').classList.add('hidden');
  $('#ownerApp').classList.remove('hidden');
  $('#ownerLogoutBtn').classList.remove('hidden');
}

function showOwnerSection(sectionId) {
  $$('#ownerApp .content-section').forEach((section) => section.classList.toggle('hidden', section.id !== sectionId));
  $$('#ownerApp .nav-item').forEach((button) => button.classList.toggle('active', button.dataset.section === sectionId));
}

async function loadOwner() {
  const user = await api('/api/account');
  if (user.role !== 'owner') throw new Error('هذه البوابة مخصصة لمالك التطبيق فقط.');
  showOwnerConsole();
  const dashboard = await api('/api/owner/dashboard');
  $('#ownerUsers').textContent = dashboard.users_total;
  $('#ownerActive').textContent = dashboard.active_users;
  $('#ownerPending').textContent = dashboard.pending_requests;
  $('#ownerSubsRevenue').textContent = money(dashboard.subscription_revenue_usd);
  $('#ownerLiveConsentCount').textContent = dashboard.live_customer_consent_count ?? 0;
  $('#ownerLiveTradingState').textContent = dashboard.live_trading_enabled ? 'بوابة الخادم مفتوحة' : 'مغلق — DEMO فقط';
  const currencyText = (values) => Object.entries(values || {}).map(([c, v]) => `${c} ${Number(v).toFixed(2)}`).join(' · ') || '0.00';
  $('#ownerFeesDue').textContent = currencyText(dashboard.performance_fees_due);
  $('#ownerFeesPaid').textContent = currencyText(dashboard.performance_fees_collected);
  await Promise.all([loadOwnerRequests(), loadOwnerLicenses(), loadOwnerReferrals(), loadOwnerFees(), loadSecurity(), loadIntegrations()]);
}

async function loadOwnerRequests(statusFilter = null) {
  const filter = statusFilter || $('#requestFilter').value || 'pending';
  const rows = await api(`/api/owner/subscription-requests?status_filter=${encodeURIComponent(filter)}`);
  $('#requestsList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(row.name)} — ${esc(row.email)}</h4>
    <p>الهاتف: ${esc(row.phone || '—')} · ${esc(row.payment_method)} · مرجع: ${esc(row.payment_reference)}</p>
    <p>القيمة: $${row.amount_usd} · ${new Date(row.created_at).toLocaleString('ar-EG')}</p></div><span class="status-tag">${esc(row.status)}</span></div>
    <p>${esc(row.payment_proof_note || 'لا توجد ملاحظات إضافية')}</p>
    <p class="muted">سجل تاريخي للقراءة فقط — لا يتم اعتماد مدفوعات أو رسوم تفعيل في الإصدار المجاني.</p></article>`).join('')
    : '<div class="surface-card muted">لا توجد طلبات في هذا التصنيف.</div>';
}

async function loadOwnerLicenses() {
  const rows = await api('/api/owner/licenses');
  $('#licensesList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(row.customer)} — ${esc(row.email)}</h4>
    <p>الجهاز: ${esc(row.device_label || 'غير مربوط')} · التفعيل: ${row.activated_at ? new Date(row.activated_at).toLocaleString('ar-EG') : 'لم يتم'}</p>
    </div><span class="status-tag">${esc(row.status)}</span></div>
    <div class="list-actions"><button class="btn btn-small btn-danger" data-license="suspend" data-id="${row.id}">تعليق</button>
    <button class="btn btn-small btn-success" data-license="release" data-id="${row.id}">فك التعليق</button>
    <button class="btn btn-small btn-outline" data-license="reset-device" data-id="${row.id}">إعادة ربط الجهاز</button>
    <button class="btn btn-small btn-outline" data-license="regenerate-code" data-id="${row.id}">إصدار رمز جديد</button></div></article>`).join('')
    : '<div class="surface-card muted">لا توجد تراخيص.</div>';
}

async function loadOwnerReferrals() {
  const rows = await api('/api/owner/referrals');
  $('#referralsList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(row.referred_customer)} — ${esc(row.referred_email)}</h4>
    <p>تمت الدعوة بواسطة: ${esc(row.referrer_name)} (${esc(row.referrer_email)})</p>
    <p>الحالة: ${esc(row.referred_status)} · رمز المُحيل: ${esc(row.referral_code || '—')}</p></div><span class="status-tag">بدون مكافأة</span></div></article>`).join('')
    : '<div class="surface-card muted">لا توجد إحالات مسجلة.</div>';
}

async function loadOwnerFees(statusFilter = null) {
  const filter = statusFilter || $('#feeFilter').value || 'due';
  const rows = await api(`/api/owner/performance-fees?status_filter=${encodeURIComponent(filter)}`);
  $('#feesList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(row.customer)} — ${esc(row.symbol)}</h4>
    <p>${esc(row.email)} · صفقة ${esc(row.trade_id)} · صافي الربح ${Number(row.net_profit).toFixed(2)} ${esc(row.currency)}</p>
    <p>رسوم الأداء: <b class="cyan">${Number(row.fee_amount).toFixed(2)} ${esc(row.currency)}</b></p></div>
    <span class="status-tag">${esc(row.status)}</span></div>
    ${row.status === 'due' ? `<button class="btn btn-small btn-success" data-fee-paid="${row.id}">تسجيل تحصيل العمولة</button>` : ''}</article>`).join('')
    : '<div class="surface-card muted">لا توجد عمولات أداء في هذا التصنيف.</div>';
}

async function loadSecurity() {
  const rows = await api('/api/owner/security-events');
  $('#securityList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><h4>${esc(row.event_type)}</h4><p>${esc(row.details || '')} · ${new Date(row.created_at).toLocaleString('ar-EG')}</p>
    <p>مستخدم: ${esc(row.user_id || 'system')} · بصمة التثبيت: ${esc(row.device_hash || '—')}</p></article>`).join('')
    : '<div class="surface-card muted">لا توجد أحداث أمان مسجلة.</div>';
}

async function loadIntegrations() {
  const [rows, diagnostics] = await Promise.all([
    api('/api/owner/integrations/sources'),
    api('/api/owner/integrations/diagnostics'),
  ]);
  $('#newsSourcesTotal').textContent = diagnostics.sources_total ?? rows.length;
  $('#newsSourcesEnabled').textContent = diagnostics.sources_enabled ?? rows.filter((x) => x.enabled).length;
  $('#newsItemsTotal').textContent = diagnostics.items_total ?? 0;
  $('#newsPollingState').textContent = diagnostics.polling_enabled ? 'نشط' : 'متوقف';
  $('#newsPollingInterval').textContent = diagnostics.polling_enabled
    ? `كل ${Math.round((diagnostics.poll_interval_seconds || 0) / 60)} دقيقة`
    : 'اضبط NEWS_POLL_INTERVAL_SECONDS';
  const diagRows = diagnostics.sources || [];
  $('#newsDiagnosticsList').innerHTML = diagRows.length ? diagRows.map((row) => `
    <div class="news-diagnostic-row">
      <div class="news-diagnostic-main">
        <strong>${esc(row.name)}</strong>
        <span class="news-kind">${esc(row.kind.toUpperCase())}</span>
        <small>${Number(row.items_received || 0)} خبر مستلم</small>
        <small>آخر استقبال خارجي: ${row.last_seen_at ? new Date(row.last_seen_at).toLocaleString('ar-EG') : 'لم يصل أي تحديث بعد'}</small>
        ${row.latest_title ? `<p class="news-latest-title">${esc(row.latest_title)}</p>` : ''}
        ${row.last_error ? `<p class="news-error">${esc(row.last_error)}</p>` : ''}
      </div>
      <div class="news-diagnostic-actions">
        <span class="news-state ${row.enabled ? 'is-enabled' : 'is-disabled'}">${row.enabled ? 'مفعّل' : 'معطّل'}</span>
        <span class="news-state ${row.last_seen_at ? 'is-enabled' : 'is-waiting'}">${row.last_seen_at ? 'استقبال مؤكد سابقًا' : 'بانتظار أول تحديث'}</span>
        <button class="btn btn-small btn-outline" data-source-test="${row.id}">اختبار النظام</button>
      </div>
    </div>`).join('') : '<p class="muted">أضف مصدرًا لبدء مراقبة الأخبار.</p>';

  $('#integrationSourcesList').innerHTML = rows.length ? rows.map((row) => `
    <article class="list-card"><div class="list-card-head"><div><h4>${esc(row.name)}</h4>
    <p>النوع: ${esc(row.kind)} · ${row.url ? esc(row.url) : 'Webhook endpoint'}</p>
    <p>آخر استقبال: ${row.last_seen_at ? new Date(row.last_seen_at).toLocaleString('ar-EG') : 'لم يستقبل بعد'} · آخر نجاح: ${row.last_success_at ? new Date(row.last_success_at).toLocaleString('ar-EG') : '—'}</p>
    ${row.last_error ? `<p class="muted">آخر خطأ: ${esc(row.last_error)}</p>` : ''}</div>
    <span class="status-tag">${row.enabled ? 'مفعّل' : 'معطّل'}</span></div>
    <div class="list-actions"><button class="btn btn-small btn-outline" data-source-toggle="${row.id}" data-enabled="${row.enabled ? 'true' : 'false'}">${row.enabled ? 'تعطيل' : 'تفعيل'}</button>
    ${row.kind === 'rss' ? `<button class="btn btn-small btn-success" data-source-poll="${row.id}">جلب الأخبار الآن</button>` : ''}</div></article>`).join('')
    : '<div class="surface-card muted">لا توجد مصادر بعد. أضف RSS أو Webhook أو Telegram.</div>';
}

$$('#ownerApp .nav-item').forEach((button) => button.addEventListener('click', () => showOwnerSection(button.dataset.section)));
$$('[data-refresh]').forEach((button) => button.addEventListener('click', () => {
  const actions = { requests: loadOwnerRequests, licenses: loadOwnerLicenses, referrals: loadOwnerReferrals,
    fees: loadOwnerFees, security: loadSecurity, integrations: loadIntegrations };
  actions[button.dataset.refresh]?.().catch((error) => toast(error.message));
}));

$('#ownerLoginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#ownerAuthMessage').classList.add('hidden');
  const body = Object.fromEntries(new FormData(event.target).entries());
  body.device_id = ownerDeviceId();
  try {
    const result = await api('/api/owner/login', { method: 'POST', body: JSON.stringify(body) });
    if (!result.user || result.user.role !== 'owner') throw new Error('تعذر التحقق من صلاحية المالك.');
    state.token = result.access_token;
    localStorage.setItem('stb_owner_token', state.token);
    await loadOwner();
  } catch (error) { authMessage(error.message, false); }
});

$('#integrationKind').addEventListener('change', () => {
  const isRss = $('#integrationKind').value === 'rss';
  $('#integrationUrlWrap').classList.toggle('hidden', !isRss);
  $('#integrationUrl').required = isRss;
});

$('#integrationSourceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const kind = String(form.get('kind'));
  const payload = { name: String(form.get('name')), kind };
  if (kind === 'rss') payload.url = String(form.get('url'));
  try {
    const result = await api('/api/owner/integrations/sources', { method: 'POST', body: JSON.stringify(payload) });
    const box = $('#integrationSourceResult');
    if (result.secret_once) {
      box.textContent = `احفظ السر الآن — لن يظهر مرة أخرى.\nSource ID: ${result.id}\nWebhook URL: ${result.webhook_url}\nHeader: ${result.secret_header}\nSecret: ${result.secret_once}`;
      box.classList.remove('hidden');
    } else {
      box.textContent = `تم إنشاء مصدر RSS بنجاح. Source ID: ${result.id}`;
      box.classList.remove('hidden');
    }
    event.target.reset();
    $('#integrationKind').dispatchEvent(new Event('change'));
    await loadIntegrations();
    toast('تم إنشاء مصدر المعلومات');
  } catch (error) { toast(error.message); }
});

$('#integrationSourcesList').addEventListener('click', async (event) => {
  const toggle = event.target.closest('[data-source-toggle]');
  const poll = event.target.closest('[data-source-poll]');
  try {
    if (toggle) {
      const enabled = toggle.dataset.enabled !== 'true';
      await api(`/api/owner/integrations/sources/${toggle.dataset.sourceToggle}`, {
        method: 'PATCH', body: JSON.stringify({ enabled }),
      });
      await loadIntegrations();
      toast('تم تحديث حالة المصدر');
    } else if (poll) {
      const result = await api(`/api/owner/integrations/sources/${poll.dataset.sourcePoll}/poll`, { method: 'POST' });
      await loadIntegrations();
      toast(result.ok ? `نجح الجلب: ${result.inserted} خبر جديد و${result.duplicates} مكرر` : (result.error || 'فشل جلب المصدر'));
    }
  } catch (error) { toast(error.message); }
});

$('#newsDiagnosticsList').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-source-test]');
  if (!button) return;
  button.disabled = true;
  button.textContent = 'جارٍ الاختبار...';
  try {
    const result = await api(`/api/owner/integrations/sources/${button.dataset.sourceTest}/test`, { method: 'POST' });
    const external = result.external_delivery_confirmed
      ? 'سبق وصول بيانات خارجية حقيقية لهذا المصدر.'
      : 'لم يصل تحديث خارجي حقيقي بعد؛ الاختبار المحلي وحده لا يؤكد اتصال البوت الخارجي.';
    toast(`${result.message} ${external}`);
    await loadIntegrations();
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = 'إعادة الاختبار';
  }
});

$('#requestFilter').addEventListener('change', () => loadOwnerRequests().catch((error) => toast(error.message)));
$('#feeFilter').addEventListener('change', () => loadOwnerFees().catch((error) => toast(error.message)));

$('#ownerApp').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-approve],[data-reject],[data-license],[data-fee-paid]');
  if (!button) return;
  try {
    if (button.dataset.approve) {
      if (!confirm('تأكيد استلام مجاني واعتماد الاشتراك؟')) return;
      const result = await api(`/api/owner/subscription-requests/${button.dataset.approve}/review`, {
        method: 'POST', body: JSON.stringify({ decision: 'approve', note: 'Payment checked by owner' }),
      });
      alert(`تم اعتماد الاشتراك. رمز التفعيل (احفظه الآن):\n\n${result.activation_code}\n\nرابط الإحالة: ${result.referral_url}`);
      await loadOwner(); toast('تم اعتماد الاشتراك وإصدار الرمز');
    } else if (button.dataset.reject) {
      const note = prompt('سبب رفض الطلب (اختياري):') || '';
      await api(`/api/owner/subscription-requests/${button.dataset.reject}/review`, {
        method: 'POST', body: JSON.stringify({ decision: 'reject', note }),
      });
      await loadOwnerRequests(); toast('تم رفض الطلب');
    } else if (button.dataset.license) {
      const id = button.dataset.id;
      const action = button.dataset.license;
      const note = prompt('ملاحظة سجل الإدارة:') || '';
      if (action === 'reset-device' && !confirm('سيتم إلغاء ربط الجهاز الحالي ويتطلب العميل إدخال رمز التفعيل مجددًا. متابعة؟')) return;
      if (action === 'regenerate-code' && !confirm('سيُلغى الرمز الحالي نهائيًا ويصدر رمز تفعيل جديد. متابعة؟')) return;
      const result = await api(`/api/owner/licenses/${id}/${action}`, { method: 'POST', body: JSON.stringify({ note }) });
      if (action === 'regenerate-code') alert(`رمز التفعيل الجديد (احفظه الآن):\n\n${result.activation_code}`);
      await loadOwnerLicenses(); toast('تم تحديث الترخيص');
    } else if (button.dataset.feePaid) {
      const reference = prompt('أدخل مرجع استلام العمولة:');
      if (!reference) return;
      await api(`/api/owner/performance-fees/${button.dataset.feePaid}/mark-paid`, {
        method: 'POST', body: JSON.stringify({ payment_reference: reference }),
      });
      await loadOwner(); toast('تم تسجيل تحصيل العمولة');
    }
  } catch (error) { toast(error.message); }
});

$('#exportRevenue').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/owner/export/revenue.csv', { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) throw new Error('فشل التصدير');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'super-trading-revenue.csv'; link.click(); URL.revokeObjectURL(url);
  } catch (error) { toast(error.message); }
});

$('#ownerLogoutBtn').addEventListener('click', async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* revoke may already have occurred */ }
  state.token = ''; localStorage.removeItem('stb_owner_token'); showOwnerLogin(); toast('تم تسجيل الخروج');
});

async function bootOwner() {
  if (!state.token) { showOwnerLogin(); return; }
  try { await loadOwner(); }
  catch {
    state.token = ''; localStorage.removeItem('stb_owner_token'); showOwnerLogin();
  }
}

bootOwner();
