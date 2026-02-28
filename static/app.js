async function loadAuthStatus() {
  const res = await fetch('/api/auth-status');
  const data = await res.json();
  const authEl = document.getElementById('authStatus');
  const connectBtn = document.getElementById('connectOutlook');
  const disconnectBtn = document.getElementById('disconnectOutlook');

  if (!data.configured) {
    authEl.textContent = 'Outlook 连接状态: 未配置（请先填写 .env）';
    connectBtn.disabled = true;
    disconnectBtn.disabled = true;
    return;
  }

  if (data.connected) {
    authEl.textContent = 'Outlook 连接状态: 已连接';
    connectBtn.disabled = true;
    disconnectBtn.disabled = false;
  } else {
    authEl.textContent = 'Outlook 连接状态: 未连接，请点击“连接 Outlook”授权';
    connectBtn.disabled = false;
    disconnectBtn.disabled = true;
  }
}

async function loadServiceHealth() {
  const el = document.getElementById('serviceStatus');
  if (!el) return;
  try {
    const res = await fetch('/api/health', { cache: 'no-store' });
    if (!res.ok) throw new Error('health http error');
    const data = await res.json();
    const now = data?.now_utc ? new Date(data.now_utc).toLocaleTimeString('zh-CN', { hour12: false }) : '--:--:--';
    el.textContent = `服务状态: 在线 (${now})`;
    el.classList.remove('down');
    el.classList.add('ok');
  } catch (_) {
    el.textContent = '服务状态: 离线';
    el.classList.remove('ok');
    el.classList.add('down');
  }
}

async function loadDigest(forceRefresh = false) {
  const endpoint = forceRefresh ? '/api/today?refresh=1' : '/api/today';
  const res = await fetch(endpoint);
  const data = await res.json();
  const nowTs = data.generated_at ? new Date(data.generated_at).getTime() : Date.now();
  const updatedText = data.generated_at ? new Date(data.generated_at).toLocaleString() : '未知';

  document.getElementById('summary').textContent = `${data.date_label} | ${data.summary_text}`;
  document.getElementById('generatedAt').textContent = `数据更新时间：${updatedText}`;
  document.getElementById('taskTitleCount').textContent = `${(data.tasks || []).length}`;
  document.getElementById('immediateTitleCount').textContent = `${(data.mails_immediate || []).length}`;
  document.getElementById('weeklyTitleCount').textContent = `${(data.mails_weekly || []).length}`;
  document.getElementById('referenceTitleCount').textContent = `${(data.mails_reference || []).length}`;
  document.getElementById('internshipTitleCount').textContent = `${(data.mails_internship || []).length}`;
  document.getElementById('researchTitleCount').textContent = `${(data.mails_research || []).length}`;
  document.getElementById('triageSummary').textContent =
    `邮件分类统计：立刻处理 ${ (data.mails_immediate || []).length } 封，` +
    `本周待办 ${ (data.mails_weekly || []).length } 封，` +
    `信息参考 ${ (data.mails_reference || []).length } 封，` +
    `实习机会 ${ (data.mails_internship || []).length } 封，` +
    `研究机会 ${ (data.mails_research || []).length } 封`;
  document.getElementById('pushStyle').textContent = `催办风格：${data.due_push_style || '未设置'}`;
  document.getElementById('dueNudgeCurrent').textContent = `当前风格文案：${data.due_nudge_current || '暂无'}`;
  document.getElementById('dueNudgeSenior').textContent = `学姐风文案：${data.due_nudge_senior || '暂无'}`;
  document.getElementById('dueNudgeCute').textContent = `可爱风文案：${data.due_nudge_cute || '暂无'}`;
  document.getElementById('pushPersonaHint').textContent =
    data.due_push_style
      ? `当前采用 ${data.due_push_style}，以下为本次推送实际发送内容。`
      : '当前没有可用催办风格，以下为默认推送内容。';
  document.getElementById('nextDueHint').textContent = data.next_due_hint || '最近截止提示：暂无';
  document.getElementById('pushPreview').textContent = data.push_preview || '暂无推送预览';
  document.getElementById('pushPreviewSenior').textContent = data.push_preview_senior || '暂无学姐风预览';
  document.getElementById('pushPreviewCute').textContent = data.push_preview_cute || '暂无可爱风预览';

  const tasks = document.getElementById('tasks');
  tasks.innerHTML = '';
  if (!data.tasks.length) {
    const li = document.createElement('li');
    li.textContent = '今天没有带截止时间的任务';
    tasks.appendChild(li);
  } else {
    data.tasks.forEach((task) => {
      const li = document.createElement('li');
      const due = task.due_at ? new Date(task.due_at).toLocaleString() : '待定';
      const dueTs = task.due_at ? new Date(task.due_at).getTime() : null;
      const publishedTs = task.published_at
        ? new Date(task.published_at).getTime()
        : (dueTs ? dueTs - 72 * 3600 * 1000 : nowTs);
      const total = dueTs ? Math.max(1, dueTs - publishedTs) : 1;
      const elapsed = dueTs ? Math.max(0, Math.min(total, nowTs - publishedTs)) : 0;
      const ratio = dueTs ? Math.max(0, Math.min(1, elapsed / total)) : 0;
      const hoursLeft = dueTs ? (dueTs - nowTs) / 3600000 : 999;
      const isRed = dueTs && hoursLeft <= 6;
      const barClass = isRed ? 'ddl-fill ddl-fill-red breathing' : 'ddl-fill';
      let status = '无 DDL 进度';
      if (dueTs) {
        const diffMs = dueTs - nowTs;
        const absMinutes = Math.floor(Math.abs(diffMs) / 60000);
        const hh = Math.floor(absMinutes / 60);
        const mm = absMinutes % 60;
        status = diffMs >= 0 ? `剩余 ${hh} 小时 ${mm} 分钟` : `已超时 ${hh} 小时 ${mm} 分钟`;
      }

      li.innerHTML = `
        <div><strong>${due}</strong> | ${task.title} ${task.url ? `<a href="${task.url}" target="_blank">打开</a>` : ''}</div>
        <div class="ddl-track"><div class="${barClass}" style="width:${(ratio * 100).toFixed(1)}%"></div></div>
        <div class="ddl-meta">${status}${isRed ? ' · 红色警戒（<=6h）' : ''}</div>
      `;
      tasks.appendChild(li);
    });
  }

  const renderMailList = (id, items, emptyText, limit = 6) => {
    const root = document.getElementById(id);
    root.innerHTML = '';
    if (!items.length) {
      const li = document.createElement('li');
      li.textContent = emptyText;
      root.appendChild(li);
      return;
    }
    const visible = items.slice(0, limit);
    visible.forEach((mail) => {
      const li = document.createElement('li');
      li.innerHTML = `${mail.subject} - ${mail.sender} ${mail.url ? `<a href="${mail.url}" target="_blank">打开</a>` : ''}`;
      root.appendChild(li);
    });
    if (items.length > limit) {
      const li = document.createElement('li');
      li.innerHTML = `<em>其余 ${items.length - limit} 条已折叠，减少噪音展示。</em>`;
      root.appendChild(li);
    }
  };

  renderMailList('mailsImmediate', data.mails_immediate || [], '当前没有需要立刻处理的邮件', 5);
  renderMailList('mailsWeekly', data.mails_weekly || [], '当前没有本周待办邮件', 6);
  renderMailList('mailsReference', data.mails_reference || [], '当前没有信息参考邮件', 8);
  renderMailList('mailsInternship', data.mails_internship || [], '当前没有实习机会邮件', 6);
  renderMailList('mailsResearch', data.mails_research || [], '当前没有研究机会邮件', 6);

  if (
    !(data.mails_immediate || []).length &&
    !(data.mails_weekly || []).length &&
    !(data.mails_reference || []).length &&
    (data.important_mails || []).length
  ) {
    // Backward-compatible fallback for older payloads.
    renderMailList('mailsReference', data.important_mails || [], '当前没有信息参考邮件', 8);
  }

}

function startRealtimeClock() {
  const el = document.getElementById('realtimeClock');
  if (!el) return;
  const tick = () => {
    const now = new Date();
    const text = now.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    el.textContent = text;
  };
  tick();
  setInterval(tick, 1000);
}

function weatherCodeToText(code) {
  const map = {
    0: '晴',
    1: '大部晴',
    2: '局部多云',
    3: '阴',
    45: '有雾',
    48: '雾凇',
    51: '小毛雨',
    53: '毛雨',
    55: '大毛雨',
    61: '小雨',
    63: '中雨',
    65: '大雨',
    71: '小雪',
    73: '中雪',
    75: '大雪',
    80: '阵雨',
    81: '强阵雨',
    82: '暴雨',
    95: '雷暴',
  };
  return map[code] || '多变';
}

async function loadTodayWeather() {
  const el = document.getElementById('weatherToday');
  if (!el) return;
  el.textContent = '读取中...';

  const fetchByLatLon = async (lat, lon, label) => {
    const url =
      `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
      '&daily=weathercode,temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=auto';
    const res = await fetch(url);
    if (!res.ok) throw new Error('weather http error');
    const data = await res.json();
    const code = data?.daily?.weathercode?.[0];
    const maxT = data?.daily?.temperature_2m_max?.[0];
    const minT = data?.daily?.temperature_2m_min?.[0];
    const weatherText = weatherCodeToText(code);
    const maxLabel = Number.isFinite(maxT) ? Math.round(maxT) : '--';
    const minLabel = Number.isFinite(minT) ? Math.round(minT) : '--';
    el.textContent = `${label} ${weatherText} ${maxLabel}°/${minLabel}°`;
  };

  const getPos = () =>
    new Promise((resolve, reject) =>
      navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 7000, maximumAge: 3600000 }),
    );

  try {
    if (!navigator.geolocation) throw new Error('geo unsupported');
    const pos = await getPos();
    await fetchByLatLon(pos.coords.latitude, pos.coords.longitude, '当前位置:');
  } catch (_) {
    try {
      // Fallback: Madison, WI
      await fetchByLatLon(43.0731, -89.4012, 'Madison:');
    } catch (err) {
      el.textContent = `天气读取失败`;
    }
  }
}

async function runNow() {
  const btn = document.getElementById('runNow');
  btn.disabled = true;
  btn.textContent = '执行中...';
  try {
    const res = await fetch('/api/run-now', { method: 'POST' });
    const result = await res.json();
    await loadDigest();
    if (result.push_sent) {
      alert('执行完成，已发送推送。');
    } else {
      alert(`执行完成，但推送失败: ${result.error || 'unknown error'}`);
    }
  } catch (err) {
    alert(`执行失败: ${err}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '立即执行并推送';
  }
}

function connectOutlook() {
  window.location.href = '/auth/login';
}

async function disconnectOutlook() {
  await fetch('/auth/logout', { method: 'POST' });
  await loadAuthStatus();
  await loadDigest();
}

document.getElementById('refresh').addEventListener('click', () => loadDigest(true));
document.getElementById('runNow').addEventListener('click', runNow);
document.getElementById('connectOutlook').addEventListener('click', connectOutlook);
document.getElementById('disconnectOutlook').addEventListener('click', disconnectOutlook);
loadAuthStatus();
loadServiceHealth();
setInterval(loadServiceHealth, 15000);
loadDigest();
startRealtimeClock();
loadTodayWeather();
