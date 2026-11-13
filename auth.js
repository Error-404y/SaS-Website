(() => {
  'use strict';
  const one = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const message = (value, success = false) => {
    const node = one('#auth-feedback');
    node.textContent = value;
    node.classList.toggle('success', success);
  };
  async function request(path, payload) {
    const response = await fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      cache: 'no-store'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed.');
    return data;
  }
  function tab(mode) {
    for (const button of all('[data-auth-tab]'))
      button.classList.toggle('active', button.dataset.authTab === mode);
    one('.auth-tabs').classList.remove('hidden');
    one('#member-login-form').classList.toggle('hidden', mode !== 'signin');
    one('#member-register-form').classList.toggle('hidden', mode !== 'register');
    one('#password-request-form').classList.add('hidden');
    one('#password-complete-form').classList.add('hidden');
    one('#auth-heading').textContent = mode === 'signin' ? 'Welcome back' : 'Join Saints and Sinners';
    one('#auth-subheading').textContent = mode === 'signin'
      ? 'Sign in to continue to Saints and Sinners.'
      : 'Submit your account for alliance review.';
    message('');
  }
  function recover(mode) {
    one('.auth-tabs').classList.toggle('hidden', mode !== 'signin');
    one('#member-login-form').classList.toggle('hidden', mode !== 'signin');
    one('#member-register-form').classList.add('hidden');
    one('#password-request-form').classList.toggle('hidden', mode !== 'request');
    one('#password-complete-form').classList.toggle('hidden', mode !== 'complete');
    one('#auth-heading').textContent = mode === 'request' ? 'Forgot your password?'
      : mode === 'complete' ? 'Set a new password' : 'Welcome back';
    one('#auth-subheading').textContent = mode === 'request'
      ? 'Submit a password change request to your alliance administrator.'
      : mode === 'complete' ? 'Enter the one-time reset code provided by your administrator.'
      : 'Sign in to continue to Saints and Sinners.';
    message('');
  }
  function submit(form, action) {
    one(form).addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try { await action(); }
      catch (error) { message(error.message); }
      finally { button.disabled = false; }
    });
  }
  all('[data-auth-tab]').forEach(button => button.addEventListener('click', () => tab(button.dataset.authTab)));
  all('[data-auth-back]').forEach(button => button.addEventListener('click', () => recover('signin')));
  one('#forgot-password').addEventListener('click', () => recover('request'));
  one('#have-reset-code').addEventListener('click', () => recover('complete'));
  one('#auth-admin').addEventListener('click', () => one('#login-dialog').showModal());
  all('[data-close]').forEach(button => button.addEventListener('click', () => one('#' + button.dataset.close).close()));
  submit('#member-login-form', async () => {
    await request('/api/member/login', {
      username: one('#member-login-name').value,
      password: one('#member-login-password').value
    });
    window.location.replace('/');
  });
  submit('#member-register-form', async () => {
    await request('/api/register', {
      username: one('#member-username').value,
      player_name: one('#member-player').value,
      email: one('#member-email').value,
      password: one('#member-password').value
    });
    one('#member-register-form').reset();
    tab('signin');
    message('Registration received. An administrator must approve your account before you can sign in.', true);
  });
  submit('#password-request-form', async () => {
    const result = await request('/api/password/request', {
      identifier: one('#reset-identifier').value
    });
    message(result.message + ' Once approved, request your one-time code from an administrator.', true);
  });
  submit('#password-complete-form', async () => {
    const result = await request('/api/password/complete', {
      username: one('#reset-username').value,
      code: one('#reset-code').value.trim(),
      new_password: one('#reset-new-password').value
    });
    one('#password-complete-form').reset();
    recover('signin');
    message(result.message, true);
  });
  submit('#login-form', async () => {
    try {
      await request('/api/login', {
        username: one('#login-username').value,
        password: one('#login-password').value
      });
      window.location.replace('/');
    } catch (error) {
      one('#login-error').textContent = error.message;
    }
  });
  // The server, not JavaScript, decides if the application can be served.
  fetch('/api/session', { credentials: 'same-origin', cache: 'no-store' })
    .then(response => response.ok ? response.json() : null)
    .then(session => {
      if (session && (session.admin || session.approved)) window.location.replace('/');
      if (session && session.status === 'rejected') {
        message('Your application was declined: ' + (session.review_message || 'Contact an administrator.'));
      } else if (session && session.status === 'pending') {
        message('Your account is awaiting administrator approval.');
      }
    }).catch(() => {});
})();
