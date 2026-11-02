"""Static, dependency-free AP settings page."""
HTML = b'''<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X Brut</title>
<style>
body { max-width:42rem; margin:2rem auto; background:#eee; color:#111; font:16px monospace; }
input, select, button { box-sizing:border-box; height:2.75rem; font:inherit; }
input, select { width:100%; margin:.3rem 0 1rem; padding:.5rem; }
button { padding:0 .8rem; }
.url { display:flex; gap:.5rem; align-items:center; }
.url input { margin-bottom:.5rem; }
.url button { flex:none; white-space:nowrap; }
.wide { width:100%; }
#status { position:sticky; top:0; padding:.75rem; background:#fff; border:1px solid #777; }
#status[data-error="true"] { color:#900; border-color:#900; }
</style>
<h1>X Brut</h1>
<form id="settings">
  <p id="status" role="status" aria-live="polite">Loading settings...</p>
  <h2>Home Wi-Fi</h2>
  Wi-Fi SSID <input name="wifi_ssid" maxlength="32" autocomplete="off">
  Wi-Fi password <input name="wifi_password" type="password" autocomplete="new-password">
  Manifest URL <input name="manifest_url">
  Splash URL <input name="splash_url">
  <h2>Hotspot (AP mode)</h2>
  SSID <input name="ap_ssid" maxlength="32" autocomplete="off">
  Password <input name="ap_password" type="password" minlength="8" maxlength="63" autocomplete="new-password">
  <small>Use at least 8 characters. Leaving this blank generates a password next time.</small>
  <h2>Diagnostics</h2>
  Log level
  <select name="log_level">
    <option value="debug">Debug (verbose)</option>
    <option value="info">Info</option>
    <option value="error">Errors only</option>
    <option value="off">Off</option>
  </select>
  <h2>xViewer</h2>
  <div id="manifests"></div>
  <button class="wide" type="button" id="add-manifest">Add OPDS feed</button>
  <div id="urls"></div>
  <button class="wide" type="button" id="add">Add URL</button>
  <p>Wi-Fi and AP changes apply when you reopen the settings session.</p>
  <p><button id="save" type="submit" disabled>Save</button></p>
</form>
<script>
const form = document.querySelector('#settings');
const urls = document.querySelector('#urls');
const manifests = document.querySelector('#manifests');
const statusLine = document.querySelector('#status');
const fields = ['wifi_ssid', 'wifi_password', 'manifest_url', 'splash_url', 'ap_ssid', 'ap_password', 'log_level'];
function showStatus(message, failed = false) { statusLine.textContent = message; statusLine.dataset.error = String(failed); }
function busy(value) { form.querySelectorAll('input, select, button').forEach(e => e.disabled = value); if (!value) sync(); }
function responseJson(response) { return response.json().then(data => { if (!response.ok || data.ok === false) throw new Error(data.error || 'Settings request failed'); return data; }); }
function sync() { urls.querySelectorAll('button').forEach(b => b.disabled = urls.children.length === 1); }
function addUrl(value) {
  const row = document.createElement('div'), input = document.createElement('input'), remove = document.createElement('button');
  row.className = 'url'; input.value = value; input.placeholder = 'XTH URL';
  remove.type = 'button'; remove.textContent = 'Remove'; remove.onclick = () => { row.remove(); sync(); };
  row.append(input, remove); urls.append(row); sync();
}
document.querySelector('#add').onclick = () => addUrl('');
function addManifest(value = {}) {
  const row = document.createElement('div'), name = document.createElement('input'), url = document.createElement('input'), remove = document.createElement('button');
  row.className = 'url'; name.value = value.name || ''; name.placeholder = 'Feed name'; name.className = 'manifest-name';
  url.value = value.url || ''; url.placeholder = 'OPDS acquisition feed URL'; url.className = 'manifest-url';
  remove.type = 'button'; remove.textContent = 'Remove'; remove.onclick = () => row.remove();
  row.append(name, url, remove); manifests.append(row);
}
document.querySelector('#add-manifest').onclick = () => addManifest();
busy(true);
fetch('/api/settings', {cache:'no-store'}).then(responseJson).then(data => {
  fields.forEach(key => { form.elements.namedItem(key).value = data[key] || ''; });
  (data.document_manifests || []).forEach(addManifest);
  (data.document_urls || []).filter(Boolean).forEach(addUrl); if (!urls.children.length) addUrl('');
  if (!data.storage_available) {
    showStatus('No SD card: settings cannot be saved.', true);
  } else {
    busy(false); showStatus('Ready. Keep this settings session open until saving finishes.');
  }
}).catch(() => { showStatus('Could not load settings. Keep AP mode or Web settings open and reload this page.', true); });
form.onsubmit = event => {
  event.preventDefault();
  const value = {};
  // Do not require Object.fromEntries/FormData support from captive-portal browsers.
  fields.forEach(key => { value[key] = form.elements.namedItem(key).value; });
  value.document_urls = [...urls.querySelectorAll('input')].map(input => input.value.trim()).filter(Boolean);
  value.document_manifests = [...manifests.children].map(row => ({name: row.querySelector('.manifest-name').value.trim(), url: row.querySelector('.manifest-url').value.trim()})).filter(item => item.url);
  busy(true); showStatus('Saving...');
  fetch('/api/settings', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(value)})
    .then(responseJson)
    .then(() => fetch('/api/settings', {cache:'no-store'}))
    .then(responseJson)
    .then(saved => {
      for (const key of ['wifi_ssid', 'wifi_password', 'ap_ssid', 'ap_password']) {
        if ((saved[key] || '') !== value[key]) throw new Error('Saved values could not be verified. Reload the page and retry.');
      }
      showStatus('Saved and verified. Reopen AP mode or Web settings to apply Wi-Fi changes.');
    })
    .catch(problem => { showStatus('Save failed: ' + (problem.message || 'no response') + '. Keep the settings session open and retry.', true); })
    .then(() => busy(false));
};
</script>'''
