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

  document.getElementById('summary').textContent = `${data.date_label} | ${data.summary_text}`;
  document.getElementById('pushPreview').textContent = data.push_preview || '暂无推送预览';

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
      const src = task.source === 'llm_mail_extract' ? '[LLM]' : '[规则]';
      li.innerHTML = `<strong>${due}</strong> ${src} | ${task.title} ${task.url ? `<a href="${task.url}" target="_blank">打开</a>` : ''}`;
      tasks.appendChild(li);
    });
  }

  renderMailBucket('mailImmediate', data.mail_buckets?.immediate_action || [], '暂无立刻处理邮件');
  renderMailBucket('mailWeek', data.mail_buckets?.week_todo || [], '暂无本周待办邮件');
  renderMailBucket('mailInfo', data.mail_buckets?.info_reference || [], '暂无信息参考邮件');
}

function renderMailBucket(elementId, mails, emptyText) {
  const el = document.getElementById(elementId);
  el.innerHTML = '';
  if (!mails.length) {
    const li = document.createElement('li');
    li.textContent = emptyText;
    el.appendChild(li);
    return;
  }
  mails.forEach((mail) => {
    const li = document.createElement('li');
    li.innerHTML = `${mail.subject} - ${mail.sender} ${mail.url ? `<a href="${mail.url}" target="_blank">打开</a>` : ''}`;
    el.appendChild(li);
  });
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
