async function loadDigest() {
  const res = await fetch('/api/today');
  const data = await res.json();

  document.getElementById('summary').textContent = `${data.date_label} | ${data.summary_text}`;

  const tasks = document.getElementById('tasks');
  tasks.innerHTML = '';
  if (!data.tasks.length) {
    const li = document.createElement('li');
    li.textContent = '今天没有 Canvas 待办';
    tasks.appendChild(li);
  } else {
    data.tasks.forEach((task) => {
      const li = document.createElement('li');
      const due = task.due_at ? new Date(task.due_at).toLocaleString() : '无截止时间';
      li.innerHTML = `${task.title} (${due}) ${task.url ? `<a href="${task.url}" target="_blank">打开</a>` : ''}`;
      tasks.appendChild(li);
    });
  }

  const mails = document.getElementById('mails');
  mails.innerHTML = '';
  if (!data.important_mails.length) {
    const li = document.createElement('li');
    li.textContent = '今天没有重要邮件';
    mails.appendChild(li);
  } else {
    data.important_mails.forEach((mail) => {
      const li = document.createElement('li');
      li.innerHTML = `${mail.subject} - ${mail.sender} ${mail.url ? `<a href="${mail.url}" target="_blank">打开</a>` : ''}`;
      mails.appendChild(li);
    });
  }
}

async function runNow() {
  const btn = document.getElementById('runNow');
  btn.disabled = true;
  btn.textContent = '执行中...';
  try {
    await fetch('/api/run-now', { method: 'POST' });
    await loadDigest();
    alert('执行完成，已发送推送。');
  } catch (err) {
    alert(`执行失败: ${err}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '立即执行并推送';
  }
}

document.getElementById('refresh').addEventListener('click', loadDigest);
document.getElementById('runNow').addEventListener('click', runNow);
loadDigest();
