
import sys
from serial import Serial
from time import sleep, time
from struct import pack, unpack
from threading import Thread

import mcu

MESSAGE_MIN = 5
MESSAGE_MAX = 128
MESSAGE_SYNC = 0x7e


CMD_DISPLAY_TEXT  = 10
CMD_KNOB_EVENT    = 12
CMD_BUTTON_EVENT  = 13
CMD_BUZZER_PLAY   = 14
CMD_BUZZER_QUEUE  = 15
CMD_BUZZER_EVENT  = 16


def crc16_ccitt(buf):
    crc = 0xffff
    for data in buf:
        data ^= crc & 0xff
        data ^= (data & 0x0f) << 4
        crc = ((data << 8) | (crc >> 8)) ^ (data >> 4) ^ (data << 3)
    return [crc >> 8, crc & 0xff]



def send_cmd(cmd_fun):
    def _cmd_fun(self, *cmd_args):
        msg = cmd_fun(self, *cmd_args)
        msg = bytes((len(msg) + MESSAGE_TRAILER_SIZE + 1,)) + msg
        msg = msg + bytes(crc16_ccitt(msg)) + bytes((MESSAGE_SYNC,))
        # print('Sending:', msg)
        self.dev.write(msg)

    return _cmd_fun


class VinDisplay:

    def __init__(self, config):
        
        self.line_length = 20
        self.n_lines = 2
        self.printer = config.get_printer()
        self.dev = Serial(config.get('vin_display_dev'),
                          timeout=None, write_timeout=1.0)
        self.rdata = bytearray()
        self.in_commands = []
        self.read_thread = Thread(target=self.read_process, daemon=True)

        self.in_cmd_dict = {
            CMD_KNOB_EVENT: self.cmd_in_knob_event,
            CMD_BUTTON_EVENT: self.cmd_in_button_event,
            CMD_BUZZER_EVENT: self.cmd_in_buzzer_event,
        }

        self.last_knob_pos = 0
        self.last_knob_time = time()
        self.last_btn_state = 0
        self.last_btn_time = time()
        self._init_buffer()

        def default_key_callback(event, ev_time):
            pass

        self.menu_key_callback = default_key_callback


    def _init_buffer(self):
        self.buffer = [bytearray(self.line_length) for i in range(self.n_lines)]        


    def read_process(self):
        while True:
            self.rdata.extend(self.dev.read())
            self.parse_incoming_data()
            self.dispatch_in_commands()


    def dispatch_in_commands(self):
        while self.in_commands:
            cmd = self.in_commands.pop(0)
            cmd_id = cmd[1]

            if cmd_id in self.in_cmd_dict:
                self.in_cmd_dict[cmd_id](cmd)
            else:
                print('INCOMING COMMAND ERRROR!')


    def cmd_in_knob_event(self, data):
        size, cmd_id, pos, crc, sync =  unpack('<BBhhB', data)
        now = time()
        diff = pos - self.last_knob_pos

        if diff > 0:
            self.menu_key_callback('down', now)
            self.beep(1000.0, 0.05)
        elif diff < 0:
            self.menu_key_callback('up', now)
            self.beep(1000.0, 0.05)

        self.last_knob_pos = pos

        print('Knob position:', pos)


    def cmd_in_button_event(self, data):
        size, cmd_id, state, crc, sync =  unpack('<BBBhB', data)
        now = time()

        if state == 1 and self.last_btn_state == 0:
            self.last_btn_time = now
        elif state == 0 and self.last_btn_state == 1:
            dt = now - self.last_btn_time
            if dt >= 1.0:
                self.menu_key_callback('long_click', now)
            else:
                self.menu_key_callback('click', now)
                self.beep(400.0, 0.05)


        self.last_btn_state = state

        print('Button state:', state)


    def cmd_in_buzzer_event(self, data):
        size, cmd_id, event, crc, sync = unpack('<BBBhB', data)
        # edict = {1 : "Buffer is free", 2 : "Buffer is full"}
        # print('Buzzer event:', edict[event] if event in edict else event)


    @send_cmd
    def cmd_display_text(self, text):
        size = len(text)
        cmd = pack(f'BB{size}s', CMD_DISPLAY_TEXT, size, text) 
        return cmd


    @send_cmd
    def cmd_buzzer_play(self, cancel_pplay=False):
        cmd = pack('B?', CMD_BUZZER_PLAY, cancel_pplay)
        return cmd


    @send_cmd
    def cmd_buzzer_queue(self, freq, duration):
        ncycles = max(1, int(freq * duration))
        hperiod = int(1_000_000.0 / freq) // 2
        cmd = pack('<BBLHH', CMD_BUZZER_QUEUE, 8, ncycles, hperiod, hperiod)
        return cmd


    def parse_incoming_data(self):

        while len(self.rdata) >= MESSAGE_MIN:    
            if self.rdata[0] == MESSAGE_SYNC:
                self.rdata = self.rdata[1:]
                continue

            block_len = self.rdata[0]

            if not (MESSAGE_MIN <= block_len <= MESSAGE_MAX):
                self.rdata.pop(0)
                continue

            if block_len > len(self.rdata):
                break

            if self.rdata[block_len - 1] != MESSAGE_SYNC:
                self.rdata.pop(0)
                continue

            msg_crc = list(self.rdata[block_len - 3: block_len - 1])
            crc = crc16_ccitt(self.rdata[:block_len - 3])

            if crc != msg_crc:
                self.rdata = self.rdata[1:]
                print('wrong CRC!')
                continue

            self.in_commands.append(self.rdata[:block_len])
            self.rdata = self.rdata[block_len:]


    def beep(self, freq, duration):
        self.cmd_buzzer_queue(freq, duration)
        self.cmd_buzzer_play(True)


    def init(self):
        self.read_thread.start()


    def flush(self):
        text = bytearray().join(self.buffer)
        self.cmd_display_text(text)
        self._init_buffer()


    def write_text(self, x, y, data):
        ln = max(0, min((self.line_length - x), len(data)))
        self.buffer[y][x : x + ln] = data[:ln]


    def set_glyphs(self, glyphs):
        pass


    def write_glyph(self, x, y, glyph_name):
        return 0


    def write_graphics(self, x, y, data):
        pass


    def clear(self):
        pass


    def get_dimensions(self):
        return (self.line_length, self.n_lines)
