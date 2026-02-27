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

async function loadDigest() {
  const res = await fetch('/api/today');
  const data = await res.json();
  const nowTs = data.generated_at ? new Date(data.generated_at).getTime() : Date.now();

  document.getElementById('summary').textContent = `${data.date_label} | ${data.summary_text}`;
  document.getElementById('triageSummary').textContent =
    `邮件分类统计：立刻处理 ${ (data.mails_immediate || []).length } 封，` +
    `本周待办 ${ (data.mails_weekly || []).length } 封，` +
    `信息参考 ${ (data.mails_reference || []).length } 封`;
  document.getElementById('pushStyle').textContent = `催办风格：${data.due_push_style || '未设置'}`;
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
      const status = dueTs ? `进度 ${(ratio * 100).toFixed(0)}%` : '无 DDL 进度';

      li.innerHTML = `
        <div><strong>${due}</strong> | ${task.title} ${task.url ? `<a href="${task.url}" target="_blank">打开</a>` : ''}</div>
        <div class="ddl-track"><div class="${barClass}" style="width:${(ratio * 100).toFixed(1)}%"></div></div>
        <div class="ddl-meta">${status}${isRed ? ' · 红色警戒（<=6h）' : ''}</div>
      `;
      tasks.appendChild(li);
    });
  }

  const renderMailList = (id, items, emptyText) => {
    const root = document.getElementById(id);
    root.innerHTML = '';
    if (!items.length) {
      const li = document.createElement('li');
      li.textContent = emptyText;
      root.appendChild(li);
      return;
    }
    items.forEach((mail) => {
      const li = document.createElement('li');
      li.innerHTML = `${mail.subject} - ${mail.sender} ${mail.url ? `<a href="${mail.url}" target="_blank">打开</a>` : ''}`;
      root.appendChild(li);
    });
  };

  renderMailList('mailsImmediate', data.mails_immediate || [], '当前没有需要立刻处理的邮件');
  renderMailList('mailsWeekly', data.mails_weekly || [], '当前没有本周待办邮件');
  renderMailList('mailsReference', data.mails_reference || [], '当前没有信息参考邮件');

  if (
    !(data.mails_immediate || []).length &&
    !(data.mails_weekly || []).length &&
    !(data.mails_reference || []).length &&
    (data.important_mails || []).length
  ) {
    // Backward-compatible fallback for older payloads.
    renderMailList('mailsReference', data.important_mails || [], '当前没有信息参考邮件');
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

document.getElementById('refresh').addEventListener('click', loadDigest);
document.getElementById('runNow').addEventListener('click', runNow);
document.getElementById('connectOutlook').addEventListener('click', connectOutlook);
document.getElementById('disconnectOutlook').addEventListener('click', disconnectOutlook);
loadAuthStatus();
loadDigest();
