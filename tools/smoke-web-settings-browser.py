#!/usr/bin/env python3
"""Exercise the actual settings form with temporary data in Chromium.

Optional dependency: playwright and its Chromium browser (or --executable).
Run from an environment allowed to open localhost sockets and launch Chromium.
"""
import argparse
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'device/CIRCUITPY/base')]


def main():
    from playwright.sync_api import sync_playwright
    from xbrut.simulator.portrait import PortraitSimulator
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as root:
        sim = PortraitSimulator(root=root, ap_host='127.0.0.1', ap_port=0)
        sim.runtime.step(['left'])
        index = next(i for i, item in enumerate(sim.ui.actions) if item[1] == 'ap')
        while sim.ui.focus != index:
            sim.runtime.step(['down'])
        sim.runtime.step(['confirm'])
        stop = threading.Event()

        def tick():
            while not stop.is_set():
                sim.tick()
                time.sleep(.005)

        thread = threading.Thread(target=tick)
        thread.start()
        try:
            with sync_playwright() as playwright:
                options = {'headless': True, 'args': ['--no-sandbox']}
                if args.executable:
                    options['executable_path'] = args.executable
                browser = playwright.chromium.launch(**options)
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                # Captive-portal/older WebViews may lack this newer API.
                page.add_init_script('Object.fromEntries = undefined')
                page.goto('http://127.0.0.1:%d/' % sim.controller.web.server.port)
                page.wait_for_selector('#save:enabled')
                expected = {'wifi_ssid': 'TEST-NET', 'wifi_password': 'test-password',
                            'ap_ssid': 'TestReader', 'ap_password': 'test-pass123'}
                for name, value in expected.items():
                    page.locator('[name=%s]' % name).fill(value)
                page.get_by_role('button', name='Save', exact=True).click()
                page.wait_for_function("document.querySelector('#status').textContent.includes('Saved and verified')")
                actual = sim.read_json('/sd/base-conf.json', {})
                assert all(actual.get(key) == value for key, value in expected.items())
                page.reload()
                page.wait_for_selector('#save:enabled')
                for key, value in expected.items():
                    assert page.locator('[name=%s]' % key).input_value() == value
                page.locator('[name=ap_password]').fill('short')
                assert not page.locator('[name=ap_password]').evaluate('(input) => input.checkValidity()')
                page.locator('[name=ap_password]').fill(expected['ap_password'])
                page.route('**/api/settings', lambda route: route.abort() if route.request.method == 'POST' else route.continue_())
                page.get_by_role('button', name='Save', exact=True).click()
                page.wait_for_function("document.querySelector('#status').textContent.includes('Save failed')")
                page.wait_for_selector('#save:enabled')
                assert not errors, errors
                browser.close()
                print('Browser PASS: verified save/readback, reload persistence, password validation, visible network failure; no credentials printed')
        finally:
            stop.set()
            thread.join()
            sim.close()


if __name__ == '__main__':
    main()
