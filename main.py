# pyinstaller test.py --clean

import socket
import vxi11
import queue
import math
import threading
from struct import unpack_from
from PySide2.QtWidgets import (QApplication, QPushButton, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QLabel, QComboBox)
from PySide2.QtCore import Slot


def open_interfaces(ipadd, port):
    global the_vx_ifc
    global the_udp_socket
    print('\nopening incoming UDP Socket at %d ...' %port, end=' ')
    the_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # 创建 UDP Socket
    the_udp_socket.bind(('', port))      # listen to anything arriving on this port from anyone
    print('done')
    print('opening VXI-11 at %s ...' % ipadd, end=' ')
    the_vx_ifc = vxi11.Instrument(ipadd)
    the_vx_ifc.write('STREAMPORT %d'%port)
    print('done')


def dut_conn(vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers):
    vx_ifc.write('STREAM OFF')                          # turn off streaming while we set it up
    vx_ifc.write('STREAMCH %s'%s_channels)
    if b_integers:
        vx_ifc.write('STREAMFMT 1')                 # 16 bit int
    else:
        vx_ifc.write('STREAMFMT 0')                 # 32 bit float
    vx_ifc.write('STREAMOPTION 2')      # use big-endian (~1) and data integrity checking (2)
    vx_ifc.write('STREAMPCKT %d'%idx_pkt_len)
    f_rate_max = float(vx_ifc.ask('STREAMRATEMAX?'))      # filters determine the max data rate

    # calculate a decimation to stay under f_rate_req
    i_decimate = int(math.ceil(math.log(f_rate_max/f_rate_req, 2.0)))
    if i_decimate < 0:
        i_decimate = 0
    if i_decimate > 20:
        i_decimate = 20

    f_rate = f_rate_max/(2.0**i_decimate)
    print('Max rate is %.3f kS/S.'%(f_rate_max*1e-3))
    print('Decimating by 2^%d down to %.3f kS/S'%(i_decimate, f_rate*1e-3))
    vx_ifc.write('STREAMRATE %d'%i_decimate)     # bring the rate under our target rate
    return f_rate


def cleanup_ifcs():
    the_vx_ifc.write('STREAM OFF')
    the_vx_ifc.close()
    the_udp_socket.close()
    print('\nconnections closed')


def fill_queue(sock_udp, q_data, bytes_per_pkt):
    while(1):
        buf, _ = sock_udp.recvfrom(bytes_per_pkt)
        q_data.put(buf)


def empty_queue(q_data, q_vals, fmt_unpk):             
    while(1):
        buf = q_data.get()
        vals = list(unpack_from(fmt_unpk, buf, 4))
        # vals = [-1* i for i in vals]
        q_vals.put(vals)


def event_detect(q_vals, thresh, width, num_detected, gui_blank):
    FLAG_A = FLAG_B = [0, 0]
    while(1):
        vals = q_vals.get()
        print(len(vals))
        for i in range(len(vals)-1):
            if( (vals[i] <= thresh) & (vals[i+1] >= thresh) ):
                FLAG_A = [1, 10*width]
            if( (vals[i] >= thresh) & (vals[i+1] <= thresh) & (FLAG_A[0]==1) ):
                FLAG_B = [1, 0]

            if(FLAG_B[0] == 1):
                num_detected += 1
                gui_blank.setText(str(num_detected))
                FLAG_A = FLAG_B = [0, 0]

            if(FLAG_B[0] == 0):
                FLAG_A[1] = max(FLAG_A[1] -1, 0)

            if(FLAG_A[1] == 0):
                FLAG_A[0] = 0


class MainWindow(QMainWindow):
    def __init__(self, widget):
        QMainWindow.__init__(self)
        
        self.setWindowTitle('SR865')
        self.setCentralWidget(widget)


class Widget(QWidget):
    def __init__(self):
        QWidget.__init__(self)

        self.ip_box = QLineEdit()
        self.ip_box.setText('192.168.1.100')
        self.channel_box = QComboBox()
        self.channel_box.addItems(['X', 'XY', 'RT'])
        self.maxrate_box = QLineEdit()
        self.maxrate_box.setText('1e4')
        self.threshold_box = QLineEdit()
        self.threshold_box.setText('1')
        self.flowspeed_box = QLineEdit()
        self.flowspeed_box.setText('0.5')
        self.connect_btn = QPushButton('CONNECT')
        self.start_btn = QPushButton('START')
        self.stop_btn = QPushButton('STOP')
        self.disconnect_btn = QPushButton('DISCONNECT')
        self.num_detected_box = QLineEdit()

        self.layout = QVBoxLayout()
        self.layout.addWidget(QLabel('IP address of SR865'))
        self.layout.addWidget(self.ip_box)
        self.layout.addWidget(QLabel('Data channel'))
        self.layout.addWidget(self.channel_box)
        self.layout.addWidget(QLabel('Expected sample rate, actual rate will be below this'))
        self.layout.addWidget(self.maxrate_box)
        self.layout.addWidget(QLabel('Detection threshold, unit: V'))
        self.layout.addWidget(self.threshold_box)
        self.layout.addWidget(QLabel('Flow speed, unit: uL/min'))
        self.layout.addWidget(self.flowspeed_box)
        self.layout.addWidget(self.connect_btn)
        self.layout.addWidget(self.start_btn)
        self.layout.addWidget(self.stop_btn)
        self.layout.addWidget(self.disconnect_btn)
        self.layout.addWidget(QLabel('Num_Dectected'))
        self.layout.addWidget(self.num_detected_box)
        self.setLayout(self.layout)

        self.connect_btn.clicked.connect(self.establish_connection)
        self.start_btn.clicked.connect(self.flow_start)
        self.stop_btn.clicked.connect(self.flow_stop)
        self.disconnect_btn.clicked.connect(cleanup_ifcs)


    @Slot()
    def establish_connection(self):
        global the_vx_ifc
        global the_udp_socket
        
        dut_add = self.ip_box.text()
        dut_port = 1865
        s_channels = self.channel_box.currentText()
        freq = f_rate_req = float(self.maxrate_box.text())
        b_integers = 1
        idx_pkt_len = 0
        open_interfaces(dut_add, dut_port)
        dut_conn(the_vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers)

        global bytes_per_pkt
        global fmt_unpk
        bytes_per_pkt = [1024, 512, 256, 128][idx_pkt_len]
        if b_integers:
            fmt_unpk = '>%dh'%(bytes_per_pkt//2)          
        else:
            fmt_unpk = '>%df'%(bytes_per_pkt//4)

        global threshold
        threshold = int(float(self.threshold_box.text()))
        global width
        width = round(6e-8*20*25*50*freq/float(self.flowspeed_box.text()))
        print(width)


    @Slot()
    def flow_start(self):
        # global the_vx_ifc    
        print('\nstreaming...')
        the_vx_ifc.write('STREAM ON')
        
        global num_detected
        num_detected = 0

        the_threads = []
        queue_data = queue.Queue()
        queue_vals = queue.Queue()    
        for queue_func, queue_args in [(fill_queue, (the_udp_socket, queue_data, bytes_per_pkt+4)),    
                                       (empty_queue, (queue_data, queue_vals, fmt_unpk)),
                                       (event_detect, (queue_vals, threshold, width, num_detected, self.num_detected_box))]:   
            the_threads.append(threading.Thread(target=queue_func, args=queue_args))
            the_threads[-1].start()


    @Slot()
    def flow_stop(self):
        print('\nStopped Streaming ...')
        the_vx_ifc.write('STREAM OFF')        


the_vx_ifc = None      
the_udp_socket = None     

if __name__ == '__main__':
    app = QApplication([])
    widget = Widget()
    window = MainWindow(widget)
    window.resize(400, 300)
    window.show()    
    app.exec_()
    cleanup_ifcs()
