"""Exercise the migrated Python path and the actual native raster on x64."""
import ctypes
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "device/CIRCUITPY/base"))
from ui import BaseUI
from framebuffer import Framebuffer
from xbrut.simulator.server import Platform
from native.micropython.base.xbrut_hardware import X4Platform
from native.micropython.base.xbrut_boot import BootController
from native.micropython.base.xbrut_runtime import Runtime
from native.micropython.app.xbrut_input import Input, Actions


class Clock:
    # Small wrapping counter verifies that production callers use ticks_diff.
    def __init__(self): self.now = 0
    def ticks_ms(self): return self.now % 65536
    def ticks_diff(self, now, then): return (now - then + 32768) % 65536 - 32768
    def advance(self, ms): self.now += ms


class NativePanel:
    """Strict native API fake using the production C raster implementation."""
    def __init__(self, raster):
        self.raster = raster
        self.data = (ctypes.c_uint8 * 48000)(*([255] * 48000))
        self.busy = False
        self.presentations = 0
        self.left = self.right = 4095
        self.power = False
    def init(self): pass
    def writable(self):
        if self.busy: raise RuntimeError("framebuffer update pending")
    def framebuffer_ready(self): return not self.busy
    def framebuffer_clear(self):
        self.writable()
        ctypes.memset(self.data, 255, 48000)
    def framebuffer_fill_rect(self, x, y, width, height, black):
        self.writable()
        self.raster.rect(self.data, x, y, width, height, black)
    def framebuffer_blit_portrait(self, x, y, width, height, packed):
        self.writable()
        source = (ctypes.c_uint8 * len(packed)).from_buffer_copy(packed)
        self.raster.blit(self.data, x, y, width, height, source)
    def framebuffer_present(self):
        self.writable()
        self.presentations += 1
        self.busy = True
    def adc_raw(self): return 2700, self.left, self.right
    def usb_present(self): return False
    def power_button(self): return self.power
    def logical(self):
        output = bytearray(48000)
        for y in range(800):
            for x in range(480):
                if not self.data[(479-x)*100+y//8] & (128 >> (y & 7)):
                    output[y*60+x//8] |= 128 >> (x & 7)
        return bytes(output)


class PortraitRasterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / "raster.c"
        source.write_text('#include "raster.h"\n'
            'void rect(uint8_t *p,int x,int y,int w,int h,bool b){x4_raster_rect(p,x,y,w,h,b);}\n'
            'void blit(uint8_t *p,int x,int y,int w,int h,const uint8_t *s){x4_raster_blit_portrait(p,x,y,w,h,s);}\n')
        # Compile the production initializer with GPIO/SPI ownership fakes.
        # gpio_config(output) disconnects the SPI signal on ESP-IDF, so count
        # every output reconfiguration before and after SPI claims the pins.
        native_source = (ROOT / "native/micropython/xbrut_x4/xbrut_x4.c").read_text()
        begin = native_source.index("static mp_obj_t xbrut_x4_init(void)")
        end = native_source.index("static MP_DEFINE_CONST_FUN_OBJ_0", begin)
        with source.open("a") as handle:
            handle.write("\n" + "\n".join([
                "typedef void *mp_obj_t;",
                "#define mp_const_none NULL",
                "#define X4_PANEL_DC_GPIO 4",
                "#define X4_PANEL_RESET_GPIO 5",
                "#define X4_PANEL_CS_GPIO 21",
                "#define X4_POWER_BUTTON_GPIO 3",
                "#define X4_USB_PRESENT_GPIO 20",
                "#define GPIO_PULLUP_ONLY 1",
                "#define GPIO_FLOATING 0",
                "static bool spi_ready;",
                "static unsigned output_mask;",
                "static void x4_output(int pin,int value){(void)value;output_mask|=1u<<pin;}",
                "static void x4_input(int pin,int pull){(void)pin;(void)pull;}",
                "static void x4_setup_adc(void){}",
                native_source[begin:end],
                "unsigned initialize(bool ready){spi_ready=ready;output_mask=0;xbrut_x4_init();return output_mask;}",
            ]))
        library = Path(cls.temp.name) / "raster.so"
        subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-I",
                        str(ROOT / "native/micropython/xbrut_x4"), str(source), "-o", str(library)], check=True)
        cls.raster = ctypes.CDLL(str(library))
        pointer = ctypes.POINTER(ctypes.c_uint8)
        cls.raster.initialize.argtypes = [ctypes.c_bool]
        cls.raster.initialize.restype = ctypes.c_uint
        cls.raster.rect.argtypes = [pointer] + [ctypes.c_int]*4 + [ctypes.c_bool]
        cls.raster.blit.argtypes = [pointer] + [ctypes.c_int]*4 + [pointer]
        cls.raster.rect.restype = cls.raster.blit.restype = None
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def setUp(self):
        self.native = NativePanel(self.raster)
        self.platform = X4Platform(self.native)

    def test_repeated_native_init_preserves_spi_pin_ownership(self):
        self.assertEqual(self.raster.initialize(False), (1 << 4) | (1 << 5) | (1 << 21))
        self.assertEqual(self.raster.initialize(True), 0)
        self.assertEqual(self.raster.initialize(True), 0)

    def test_old_firmware_is_rejected_before_a_partial_render(self):
        self.native.framebuffer_blit_portrait = None
        with self.assertRaisesRegex(RuntimeError, 'X4 firmware lacks framebuffer_blit_portrait'):
            X4Platform(self.native)
        self.assertEqual(self.native.presentations,0)

    def test_asymmetric_corners_rotation_and_white_erasure(self):
        self.platform.fill_rect(0, 0, 9, 3, True)
        self.platform.pixel(479, 0)
        self.platform.fill_rect(477, 797, 3, 3, True)
        self.platform.pixel(0, 799)
        self.platform.fill_rect(2, 0, 2, 1, False)
        expected = Platform()
        expected.fill_rect(0, 0, 9, 3, True)
        expected.pixel(479, 0)
        expected.fill_rect(477, 797, 3, 3, True)
        expected.pixel(0, 799)
        expected.fill_rect(2, 0, 2, 1, False)
        expected.refresh()
        self.assertEqual(self.native.logical(), expected.frame)
        self.assertFalse(self.native.data[479*100] & 128)
        self.assertFalse(self.native.data[0] & 128)

    def test_clipped_rectangles_and_non_aligned_transparent_bitmap(self):
        self.platform.fill_rect(-2, -3, 8, 9, True)
        self.platform.fill_rect(478, 798, 99, 99, True)
        self.platform.blit(-3, -1, 9, 3, bytes([255, 128, 170, 128, 85, 0]))
        self.platform.blit(478, 798, 9, 3, bytes([255, 128]*3))
        self.platform.fill_rect(12, 12, -2, 1, True)
        logical = self.native.logical()
        self.assertEqual(len(logical), 48000)
        # Check with a coordinate-level reference, independent of rotation.
        points = {(x,y) for y in range(6) for x in range(6)}
        points.update((x,y) for y in range(798,800) for x in range(478,480))
        source = bytes([255,128,170,128,85,0])
        for row in range(3):
            for col in range(9):
                x,y=col-3,row-1
                if x>=0 and y>=0 and source[row*2+col//8] & (128>>(col&7)): points.add((x,y))
        reference = bytearray(48000)
        for x,y in points: reference[y*60+x//8] |= 128>>(x&7)
        self.assertEqual(logical, reference)

    def test_complete_frame_replacement_and_short_input_is_atomic(self):
        self.platform.present(b'\xff'*48000)
        self.assertEqual(self.native.logical(), b'\xff'*48000)
        with self.assertRaises(RuntimeError): self.platform.clear()
        self.native.busy = False
        with self.assertRaises(ValueError): self.platform.present(b'short')
        self.assertEqual(self.native.logical(), b'\xff'*48000)
        self.platform.present(bytes(48000))
        self.assertEqual(self.native.logical(), bytes(48000))
        self.native.busy = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'frame.bin';path.write_bytes(b'\x80'+bytes(47999))
            self.platform.present_file(path)
            self.assertEqual(self.native.logical(), path.read_bytes())

    def test_shared_ui_and_text_match_simulator(self):
        native_ui = BaseUI(self.platform)
        expected = Platform(); expected_ui = BaseUI(expected)
        docs = [('first.xth','First document'),('second.xtc','Second document')]
        native_ui.document_grid('xViewer',docs,1)
        expected_ui.document_grid('xViewer',docs,1)
        expected.battery_status = self.platform.battery_status
        # Battery must have the same inputs for a byte-for-byte comparison.
        expected_ui.document_grid('xViewer',docs,1)
        self.assertEqual(self.native.logical(),expected.frame)
        self.native.busy = False
        self.platform.clear(); expected.clear()
        for platform in (self.platform,expected):
            frame=Framebuffer(platform)
            frame.text(-4, -2, 'clipped', 2)
            frame.text_rotated_180(200,200,'back')
        expected.refresh()
        self.assertEqual(self.native.logical(), expected.frame)


CONFIG = {'baseline': {'left':4095,'right':4095}, 'buttons': {
    'lower-1': {'channel':'left','raw':500}, 'lower-2': {'channel':'left','raw':1400},
    'lower-3': {'channel':'left','raw':2300}, 'lower-4': {'channel':'left','raw':3200},
    'side-1': {'channel':'right','raw':900}, 'side-2': {'channel':'right','raw':2600}}}


class InputTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.hardware = SimpleNamespace(left=4095,right=4095,power=False)
        self.hardware.adc_raw = lambda: (2700,self.hardware.left,self.hardware.right)
        self.hardware.power_button = lambda: self.hardware.power
        self.input = Input(self.hardware,clock=self.clock,config=CONFIG)
        self.actions = Actions(self.input,clock=self.clock)
    def settle(self, **values):
        for key,value in values.items(): setattr(self.hardware,key,value)
        first=self.actions.poll(); self.clock.advance(20)
        return first+self.actions.poll()
    def test_bounce_unknown_values_and_held_keys(self):
        self.hardware.right=2600; self.assertEqual(self.actions.poll(),[])
        self.clock.advance(5); self.hardware.right=4095; self.actions.poll()
        self.clock.advance(5); self.hardware.right=2600; self.actions.poll()
        self.clock.advance(19); self.assertEqual(self.actions.poll(),[])
        self.clock.advance(1); self.assertEqual(self.actions.poll(),['down'])
        self.clock.advance(1000); self.assertEqual(self.actions.poll(),[])
        self.assertEqual(self.settle(right=4095),[])
        self.assertEqual(self.settle(right=1900),[])
    def test_double_press_independent_ladders_and_power_debounce(self):
        self.assertEqual(self.settle(right=2600),['down'])
        self.assertEqual(self.settle(right=4095),[])
        self.assertEqual(self.settle(right=2600,left=1400),['confirm','down'])
        self.assertEqual(self.settle(power=True),['power'])
        self.clock.advance(100); self.assertEqual(self.actions.poll(),[])
    def test_short_and_long_back_are_mutually_exclusive_across_wrap(self):
        self.clock.now=65500
        self.assertEqual(self.settle(left=500),[])
        self.clock.advance(50)
        self.assertEqual(self.settle(left=4095),['left'])
        self.assertEqual(self.settle(left=500),[])
        self.clock.advance(700); self.assertEqual(self.actions.poll(),['left_long'])
        self.clock.advance(700); self.assertEqual(self.actions.poll(),[])
        self.assertEqual(self.settle(left=4095),[])
    def test_power_held_through_wake_is_suppressed_until_released(self):
        self.hardware.power = True
        self.actions = Actions(self.input, clock=self.clock)
        self.clock.advance(100)
        self.assertEqual(self.actions.poll(), [])
        self.assertFalse(self.actions.released())
        self.assertEqual(self.settle(power=False), [])
        self.assertTrue(self.actions.released())
        self.assertEqual(self.settle(power=True), ['power'])
        self.assertFalse(self.actions.released())

    def test_button_mapping(self):
        for name,config in CONFIG['buttons'].items():
            if name=='lower-1': continue
            with self.subTest(name=name):
                self.assertEqual(self.settle(**{config['channel']:config['raw']}),[Actions.NAMES[name]])
                self.settle(**{config['channel']:4095})


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        from xbrut.simulator.portrait import PortraitSimulator
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        docs=Path(self.temp.name)/'xviewer-docs';docs.mkdir()
        for index in range(7): (docs/('%d.xth'%index)).touch()
        self.clock=Clock()
        self.sim=PortraitSimulator(self.temp.name,self.clock)
    def test_model_advances_while_busy_and_latest_screen_is_rendered(self):
        frame=self.sim.platform.frame
        self.sim.runtime.step(['down','down','down'])
        self.assertEqual(self.sim.ui.focus,3)
        self.assertEqual(self.sim.platform.frame,frame)
        self.assertTrue(self.sim.ui.pending)
        self.clock.advance(250);self.sim.tick()
        self.assertFalse(self.sim.ui.pending)
        expected=Platform(); BaseUI(expected).document_grid('xViewer',[(str(i)+'.xth',str(i)+'.xth') for i in range(7)],3)
        self.assertEqual(self.sim.platform.frame,expected.frame)
    def test_settings_back_focus_and_long_home_use_shared_controller(self):
        self.sim.runtime.step(['down','down','left'])
        self.assertEqual(self.sim.ui.page,'settings')
        self.sim.runtime.step(['left'])
        self.assertEqual(self.sim.ui.page,'home')
        # Home focus is retained when opening base settings.
        self.assertEqual(self.sim.ui.focus,2)
        self.sim.runtime.step(['left_long'])
        self.assertEqual(self.sim.ui.focus,0)
    def test_busy_timeout_latches_but_controls_continue(self):
        self.sim.runtime.timeout_ms=100
        self.clock.advance(101);self.sim.runtime.step(['down'])
        self.assertIsInstance(self.sim.runtime.display_error,OSError)
        frame=self.sim.platform.frame
        self.clock.advance(250);self.sim.runtime.step(['down'])
        self.assertEqual(self.sim.ui.focus,2)
        self.assertEqual(self.sim.platform.frame,frame)
    def test_actual_input_actions_remain_live_during_busy(self):
        hardware=SimpleNamespace(left=4095,right=4095,power_button=lambda:False)
        hardware.adc_raw=lambda:(2700,hardware.left,hardware.right)
        self.sim.runtime.controls=Actions(Input(hardware,clock=self.clock,config=CONFIG),clock=self.clock)
        frame=self.sim.platform.frame
        for raw in (2600,4095,2600,4095):
            hardware.right=raw
            self.sim.runtime.step()
            self.clock.advance(20)
            self.sim.runtime.step()
        self.assertEqual(self.sim.ui.focus,2)
        self.assertEqual(self.sim.platform.frame,frame)
        self.clock.advance(250);self.sim.runtime.step()
        self.assertNotEqual(self.sim.platform.frame,frame)
    def test_viewer_handoff_can_return_back(self):
        self.sim.runtime.step(['down','confirm'])
        self.assertEqual(self.sim.ui.page,'unavailable')
        self.sim.runtime.step(['left'])
        self.assertEqual((self.sim.ui.page,self.sim.ui.focus),('home',1))
    def test_native_readiness_error_latches_without_painting(self):
        def fail(): raise OSError('native BUSY timeout')
        self.sim.platform.ready=fail
        frame=self.sim.platform.frame
        self.sim.runtime.step(['down'])
        self.assertIsInstance(self.sim.runtime.display_error,OSError)
        self.assertEqual(self.sim.platform.frame,frame)

    def open_web_settings(self, action):
        from tests.test_web_settings import FakeServer
        self.sim.controller.web.server_factory = FakeServer
        self.sim.runtime.step(['left'])
        index = next(i for i, item in enumerate(self.sim.ui.actions) if item[1] == action)
        while self.sim.ui.focus != index:
            self.sim.runtime.step(['down'])
        self.sim.runtime.step(['confirm'])
        return index

    def test_ap_service_starts_on_selection_and_back_stops_it(self):
        web = self.sim.controller.web
        self.assertFalse(web.radio.ap)
        self.assertIsNone(web.server)
        index = self.open_web_settings('ap')
        self.assertEqual(self.sim.ui.page, 'ap')
        self.assertTrue(web.radio.ap)
        self.assertTrue(web.server.started)
        self.assertTrue(any('http://' in line for line in self.sim.ui.lines))
        self.sim.runtime.step(['left'])
        self.assertEqual((self.sim.ui.page, self.sim.ui.focus), ('settings', index))
        self.assertFalse(web.radio.ap)
        self.assertIsNone(web.server)
        self.sim.runtime.step(['confirm', 'left_long'])
        self.assertEqual(self.sim.ui.page, 'home')
        self.assertFalse(web.radio.ap)

    def test_station_web_settings_shows_missing_credentials_then_saved_wifi(self):
        web = self.sim.controller.web
        index = self.open_web_settings('web_settings')
        self.assertEqual(self.sim.ui.page, 'web_settings')
        self.assertIn('NO SAVED WIFI', '\n'.join(self.sim.ui.lines))
        self.assertFalse(web.radio.station)
        self.sim.runtime.step(['left'])
        self.assertEqual(self.sim.ui.focus, index)
        web.store.save({'wifi_ssid': 'Home', 'wifi_password': 'password'})
        self.sim.runtime.step(['confirm'])
        self.assertTrue(web.radio.station)
        self.assertEqual(web.phase, 'ready')
        self.sim.runtime.step(['left_long'])
        self.assertFalse(web.radio.station)
        self.assertEqual(self.sim.ui.page, 'home')

    def open_sd_manager(self):
        self.sim.runtime.step(['left'])
        index = next(i for i, action in enumerate(self.sim.ui.actions) if action[1] == 'manage_sd')
        while self.sim.ui.focus != index:
            self.sim.runtime.step(['down'])
        self.sim.runtime.step(['confirm'])
        self.assertEqual(self.sim.ui.page, 'sd_manager')
        return index

    def settle_display(self):
        self.clock.advance(250)
        self.sim.tick()
        self.clock.advance(250)
        self.sim.tick()

    def test_sd_manager_opens_navigates_and_restores_settings_focus(self):
        index = self.open_sd_manager()
        self.assertEqual(self.sim.controller.manager.__class__.__module__, 'native.micropython.base.sd_manager')
        self.assertTrue(self.sim.controller.manager.rows)
        frame = self.sim.platform.frame
        self.sim.runtime.step(['down', 'down'])
        self.assertEqual(self.sim.controller.manager.focus, 2)
        self.assertEqual(self.sim.platform.frame, frame)
        self.settle_display()
        self.assertNotEqual(self.sim.platform.frame, frame)
        self.sim.runtime.step(['left'])
        self.assertEqual((self.sim.ui.page, self.sim.ui.focus), ('settings', index))
        self.assertIsNone(self.sim.controller.manager)

    def test_sd_delete_requires_presented_dialog_and_back_cancels(self):
        self.open_sd_manager()
        selected = Path(self.sim.controller.manager.selected()['path'])
        self.sim.runtime.step(['confirm', 'confirm'])
        self.assertTrue(self.sim.controller.manager.modal)
        self.assertTrue(selected.exists())
        self.sim.runtime.step(['confirm'])
        self.assertTrue(selected.exists())
        self.settle_display()
        self.sim.runtime.step(['left'])
        self.assertEqual(self.sim.ui.page, 'sd_manager')
        self.assertFalse(self.sim.controller.manager.modal)
        self.assertTrue(selected.exists())
        self.sim.runtime.step(['left_long'])
        self.assertEqual(self.sim.ui.page, 'home')
        self.assertIsNone(self.sim.controller.manager)

    def test_sd_delete_after_confirmation_only_removes_selected_temporary_item(self):
        self.open_sd_manager()
        selected = Path(self.sim.controller.manager.selected()['path'])
        self.sim.runtime.step(['confirm'])
        self.settle_display()
        self.sim.runtime.step(['confirm'])
        self.assertFalse(selected.exists())
        self.assertTrue(Path(self.temp.name).is_dir())
        self.assertEqual(self.sim.ui.page, 'sd_manager')
        self.assertFalse(self.sim.controller.manager.modal)

    def test_sd_card_loss_during_confirmation_returns_read_only_home(self):
        self.open_sd_manager()
        selected = Path(self.sim.controller.manager.selected()['path'])
        self.sim.runtime.step(['confirm'])
        self.settle_display()
        self.sim.sd_present = False
        self.sim.runtime.step(['confirm'])
        self.assertTrue(selected.exists())
        self.assertEqual(self.sim.ui.page, 'home')
        self.assertTrue(self.sim.ui.read_only)
        self.assertIsNone(self.sim.controller.manager)

    def test_sd_manager_handles_failed_open_and_empty_tree(self):
        with patch('native.micropython.base.sd_manager.os.listdir', side_effect=OSError('card removed')):
            self.sim.runtime.step(['left'])
            index = next(i for i, action in enumerate(self.sim.ui.actions) if action[1] == 'manage_sd')
            self.sim.ui.focus = index
            self.sim.runtime.step(['confirm'])
        self.assertEqual(self.sim.ui.page, 'home')
        self.assertTrue(self.sim.ui.read_only)
        with tempfile.TemporaryDirectory() as empty:
            self.sim.ui.read_only = False
            self.sim.controller.sd_root = empty
            self.open_sd_manager()
            self.assertEqual(self.sim.controller.manager.rows, [])
            self.sim.runtime.step(['confirm', 'down', 'left'])
            self.assertEqual(self.sim.ui.page, 'settings')

    def test_read_only_boot(self):
        self.sim.toggle_sd()
        self.assertTrue(self.sim.ui.read_only)
        self.assertEqual(self.sim.ui.actions,[])


class MigratedStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.temp.name
        paths = SimpleNamespace(BASE_CONFIG_PATH=root+'/base-conf.json', DATA_ROOT=root)
        self.mounts = []
        import os
        self.os = SimpleNamespace(VfsFat=lambda card: ('vfs',card),
            mount=lambda vfs,path: self.mounts.append((vfs,path)), statvfs=os.statvfs,
            rename=os.rename, remove=os.remove)
        spec = importlib.util.spec_from_file_location('migrated_storage', ROOT/'native/micropython/base/xbrut_storage.py')
        self.storage = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'os':self.os,'xbrut_x4':SimpleNamespace(SDCard=lambda:'card'), 'xbrut_paths':paths}):
            spec.loader.exec_module(self.storage)
    def test_mount_roundtrip_and_sd_write_guard(self):
        with self.assertRaises(self.storage.SDCardUnavailable): self.storage.write_json(self.temp.name+'/config.json',{})
        self.assertTrue(self.storage.mount_sd())
        self.assertTrue(self.storage.mount_sd())
        self.assertEqual(len(self.mounts),1)
        path=self.temp.name+'/config.json'
        self.storage.write_json(path,{'focus':3})
        self.assertEqual(self.storage.read_json(path),{'focus':3})
        self.assertFalse(Path(path+'.new').exists())
        for invalid in ('/config.json',self.temp.name+'/../config.json',self.temp.name+'/a/../../config.json'):
            with self.subTest(path=invalid), self.assertRaises(ValueError): self.storage.write_json(invalid,{})
    def test_failed_mount_does_not_trust_an_existing_directory(self):
        def fail(*args): raise OSError('mount failed')
        self.os.mount=fail
        self.assertFalse(self.storage.mount_sd())
        self.assertFalse(self.storage.sd_available())
        with self.assertRaises(self.storage.SDCardUnavailable): self.storage.write_json(self.temp.name+'/config.json',{})
    def test_actual_native_logger_uses_rotated_sd_path(self):
        spec=importlib.util.spec_from_file_location('migrated_log', ROOT/'native/micropython/base/xbrut_log.py')
        logger=importlib.util.module_from_spec(spec)
        clock=Clock()
        with patch.dict(sys.modules, {'time':clock}): spec.loader.exec_module(logger)
        path=self.temp.name+'/base.log'
        logger.set_path(path);logger.configure({'log_level':'debug'})
        logger._max_bytes=80
        logger.info('test','first entry')
        logger.info('test','second entry')
        self.assertTrue(Path(path+'.1').exists())
        self.assertIn('second entry',Path(path).read_text())
        logger.configure({'log_level':'off'})
        before=Path(path).read_bytes();logger.error('test','disabled')
        self.assertEqual(before,Path(path).read_bytes())


class PayloadTest(unittest.TestCase):
    def test_explicit_payload_contains_shared_ui_and_migrated_runtime(self):
        spec=importlib.util.spec_from_file_location('stage_mp',ROOT/'tools/stage-micropython.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            portrait=module.stage(Path(root)/'portrait','portrait')
            for path in ('main.py','xbrut_input.py','base/ui.py','base/framebuffer.py','base/sweet16mono.f8',
                         'base/xbrut_runtime.py','base/xbrut_boot.py','base/xbrut_hardware.py',
                         'base/ap_page.py','base/xbrut_http.py','base/xbrut_web.py','base/xbrut_network.py','base/xbrut_lifecycle.py'):
                self.assertTrue((portrait/path).is_file(),path)
            self.assertEqual((portrait/'base/ui.py').read_bytes(),(ROOT/'device/CIRCUITPY/base/ui.py').read_bytes())
            browser=module.stage(Path(root)/'browser','browser')
            self.assertEqual(sorted(p.name for p in browser.iterdir()),['main.py','xbrut_input.py'])
            with self.assertRaises(ValueError): module.stage(browser,'portrait')


if __name__ == '__main__': unittest.main()
