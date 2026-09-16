"""AP settings API; requires adafruit_httpserver on the device."""
from xbrut_storage import read_json, write_json
from ap_page import HTML

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
        value = read_json("/base-conf.json", {}) or {}
        import project
        value["document_urls"] = project.config().get("document_urls", [])
        return JSONResponse(request, value)

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
            if "document_urls" in value:
                import project
                project.save_urls(value["document_urls"])
            return JSONResponse(request, {"ok": True})
        except Exception as error:
            return JSONResponse(request, {"ok": False, "error": str(error)}, status=400)

    server.start(str(platform.ap_address()))
    return conf, server
