"""AP settings API; requires adafruit_httpserver on the device."""
from storage import read_json, write_json

HTML = b'''<!doctype html><meta charset=utf-8><title>X Brut</title><style>body{max-width:42rem;margin:2rem auto;background:#eee;color:#111;font:16px monospace}input{width:100%;box-sizing:border-box;margin:.3rem 0 1rem;padding:.5rem}button{padding:.6rem 2rem}</style><h1>X Brut</h1><form id=f><h2>Client mode</h2>Wifi SSID<input name=wifi_ssid>Wifi PWD<input type=password name=wifi_password>Manifest URL<input name=manifest_url>Splash URL<input name=splash_url><h2>AP mode</h2>SSID<input name=ap_ssid>PWD<input name=ap_password><button>Save</button> <span id=s></span></form><script>let f=document.forms.f;fetch('/api/settings').then(x=>x.json()).then(x=>Object.keys(x).forEach(k=>f[k]&&(f[k].value=x[k])));f.onsubmit=e=>{e.preventDefault();fetch('/api/settings',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(f))),headers:{'content-type':'application/json'}}).then(x=>x.json()).then(x=>s.textContent=x.ok?'saved':x.error)}</script>'''

def start(platform):
    """Start the AP and return a server which the main loop polls."""
    conf = read_json("/base-conf.json", {}) or {}
    platform.start_ap(conf)
    from adafruit_httpserver import Server, Request, Response, JSONResponse, POST
    server = Server(platform.socket_pool(), "/static", debug=False)

    @server.route("/")
    def page(request):
        return Response(request, HTML, content_type="text/html")

    @server.route("/api/settings")
    def get_settings(request):
        return JSONResponse(request, read_json("/base-conf.json", {}) or {})

    @server.route("/api/settings", methods=[POST])
    def put_settings(request):
        try:
            value = request.json()
            # Persist only keys owned by the base; project keys can be added later.
            allowed = ("wifi_ssid", "wifi_password", "manifest_url", "splash_url", "ap_ssid", "ap_password")
            current = read_json("/base-conf.json", {}) or {}
            current.pop("ap_base_ip", None)  # discard obsolete configurations on their next save
            for key in allowed:
                if key in value: current[key] = value[key]
            write_json("/base-conf.json", current)
            return JSONResponse(request, {"ok": True})
        except Exception as error:
            return JSONResponse(request, {"ok": False, "error": str(error)}, status=400)

    server.start(str(platform.ap_address()))
    return conf, server
