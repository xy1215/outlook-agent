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

function renderMails(listElementId, mails, emptyText) {
  const mailList = document.getElementById(listElementId);
  mailList.innerHTML = '';
  if (!mails || !mails.length) {
    const li = document.createElement('li');
    li.textContent = emptyText;
    mailList.appendChild(li);
    return;
  }

  mails.forEach((mail) => {
    const li = document.createElement('li');
    li.innerHTML = `${mail.subject} - ${mail.sender} ${mail.url ? `<a href="${mail.url}" target="_blank">打开</a>` : ''}`;
    mailList.appendChild(li);
  });
}

async function loadDigest() {
  const res = await fetch('/api/today');
  const data = await res.json();

  document.getElementById('summary').textContent = `${data.date_label} | ${data.summary_text}`;
  document.getElementById('pushStyle').textContent = `催办风格: ${data.due_push_style || '学姐风'}`;
  document.getElementById('pushMessage').textContent = data.due_push_message || '暂无 48 小时内到期催办文案';

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
      li.innerHTML = `<strong>${due}</strong> | ${task.title} ${task.url ? `<a href="${task.url}" target="_blank">打开</a>` : ''}`;
      tasks.appendChild(li);
    });
  }

  const triage = data.mail_triage || {};
  renderMails('mailsNow', triage['立刻处理'] || [], '暂无需要立刻处理邮件');
  renderMails('mailsWeek', triage['本周待办'] || [], '暂无本周待办邮件');
  renderMails('mailsRef', triage['信息参考'] || [], '暂无信息参考邮件');
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
