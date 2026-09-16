"""Static, dependency-free AP settings page."""
HTML = b'''<!doctype html>
<meta charset="utf-8">
<title>X Brut</title>
<style>
body { max-width:42rem; margin:2rem auto; background:#eee; color:#111; font:16px monospace; }
input, button { box-sizing:border-box; height:2.75rem; font:inherit; }
input { width:100%; margin:.3rem 0 1rem; padding:.5rem; }
button { padding:0 .8rem; }
.url { display:flex; gap:.5rem; align-items:center; }
.url input { margin-bottom:.5rem; }
.url button { flex:none; white-space:nowrap; }
.wide { width:100%; }
</style>
<h1>X Brut</h1>
<form id="settings">
  <h2>Client mode</h2>
  Wifi SSID <input name="wifi_ssid">
  Wifi PWD <input name="wifi_password" type="password">
  Manifest URL <input name="manifest_url">
  Splash URL <input name="splash_url">
  <h2>AP mode</h2>
  SSID <input name="ap_ssid">
  PWD <input name="ap_password">
  <h2>xViewer</h2>
  <div id="urls"></div>
  <button class="wide" type="button" id="add">Add URL</button>
  <p><button>Save</button> <span id="status"></span></p>
</form>
<script>
const form = document.querySelector('#settings');
const urls = document.querySelector('#urls');
function sync() { urls.querySelectorAll('button').forEach(b => b.disabled = urls.children.length === 1); }
function addUrl(value) {
  const row = document.createElement('div'), input = document.createElement('input'), remove = document.createElement('button');
  row.className = 'url'; input.value = value; input.placeholder = 'XTH URL';
  remove.type = 'button'; remove.textContent = 'Remove'; remove.onclick = () => { row.remove(); sync(); };
  row.append(input, remove); urls.append(row); sync();
}
document.querySelector('#add').onclick = () => addUrl('');
fetch('/api/settings').then(r => r.json()).then(data => {
  Object.keys(data).forEach(key => { if (form[key]) form[key].value = data[key]; });
  (data.document_urls || []).forEach(addUrl); if (!urls.children.length) addUrl('');
});
form.onsubmit = event => {
  event.preventDefault(); const value = Object.fromEntries(new FormData(form));
  value.document_urls = [...urls.querySelectorAll('input')].map(input => input.value.trim()).filter(Boolean);
  fetch('/api/settings', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(value)})
    .then(r => r.json()).then(data => document.querySelector('#status').textContent = data.ok ? 'saved' : data.error);
};
</script>'''
