import math
import socket
import sys
import time
import vxi11
import queue
import threading
from struct import unpack_from
from PySide2.QtWidgets import (QApplication, QPushButton, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel)
from PySide2.QtCore import Slot

the_vx_ifc = None      
the_udp_socket = None     


def show_results(count_dropped, pkts_num, lst_dropped, count_samples):
    """ print indicating OK, or some dropped packets"""
    if count_dropped:
        print('\nFAIL: Dropped %d out of %d packets in %d gaps:'%(count_dropped, pkts_num, len(lst_dropped)), end=' ')   
        print(''.join('%d at %d, '%(x[0], x[1]) for x in lst_dropped[:5]))
    else:
        print('\npass: No packets dropped out of %d. %d samples captured.'%(pkts_num, count_samples))   


def open_interfaces(ipadd, port):
    global the_udp_socket
    global the_vx_ifc
    print('opening incoming UDP Socket at %d ...' % port, end=' ')
    the_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    the_udp_socket.bind(('', port))      # listen to anything arriving on this port from anyone
    print('done')
    print('opening VXI-11 at %s ...' % ipadd, end=' ')
    the_vx_ifc = vxi11.Instrument(ipadd)
    the_vx_ifc.write('STREAMPORT %d'%port)
    print('done')


def dut_config(vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers):
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


def process_packet(buf, fmt_unpk, prev_pkt_cntr):
    vals = list(unpack_from(fmt_unpk, buf, 4)) 
    head = unpack_from('>I', buf)[0]          
    cntr = head & 0xff                
    
    if prev_pkt_cntr is not None and ((prev_pkt_cntr+1)&0xff) != cntr: # check for missed packets, if this isn't the 1st and the difference isn't 1 then calculate how many we missed
        n_dropped = cntr - prev_pkt_cntr               
        if n_dropped < 0:
            n_dropped += 0xff
    else:
        n_dropped = 0

    return vals, head, n_dropped, cntr


def cleanup_ifcs():
    global the_vx_ifc
    global the_udp_socket
    print("\n cleaning up...", end=' ')
    the_vx_ifc.write('STREAM OFF')
    the_vx_ifc.close()
    the_udp_socket.close()
    print('connections closed\n')


def fill_queue(sock_udp, q_data, bytes_per_pkt):
    print('Fill started')
    while(1):
        buf, _ = sock_udp.recvfrom(bytes_per_pkt)
        q_data.put(buf)


def empty_queue(q_data, q_vals, bytes_per_pkt, fmt_unpk, s_prt_fmt, s_channels):
    prev_pkt_cntr = None                 
    lst_dropped = []              
    count_dropped = 0
    count_vars = len(s_channels)
    print('Empty started')
    while(1):
        buf = q_data.get()
        vals, _, n_dropped, prev_pkt_cntr = process_packet(buf, fmt_unpk, prev_pkt_cntr)
        vals = [1e9* i for i in vals]
        # print(vals)
        q_vals.put(vals)
        count_dropped += n_dropped


def event_detect(q_vals, thresh, num_detected, gui_blank):
    FLAG_A = FLAG_B = [0,0]
    print('Detection started')
    while(1):
        vals = q_vals.get()
        for i in range(len(vals)):
            if( (vals[i] >= thresh) & (vals[i-1] <= thresh) & (FLAG_A[1]==0) ):
                FLAG_A = [1, 100]
            if( (vals[i] <= thresh) & (vals[i-1] >= thresh) & (FLAG_A[1]==1) & (FLAG_B[1]==0) ):
                FLAG_B = [1, 0]
            # if( val[i] <= -1* thresh & vals[i-1] >= -1* thresh & FLAG_A[1]==1 & FLAG_B[1]==1 & FLAG_C[1] ==0 ):
            #     FLAG_C = [1, i, 0] 
            # if( val[i] >= -1*thresh & vals[i-1] <= -1*thresh & FLAG_A[1]==1 & FLAG_B[1]==1 & FLAG_C[1]==1 & FLAG_D[1]==0 ):
            #     FLAG_D = [1, i, 0] 

            # if(FLAG_D[0] == 1):
            #     num_detected += 1
            #     gui_blank.setText(str(num_detected))
            #     FLAG_A = FLAG_B = FLAG_C = FLAG_D = [0, 0, 0]
            # if(FLAG_D(0) == 0):
            #     FLAG_A[2] = max(FLAG_A[2] -1, 0)
            # if(FLAG_A[2] == 0):
            #     FLAG_A[0] = FLAG_B[0] = FLAG_C[0] = 0

            if(FLAG_B[0] == 1):
                num_detected += 1
                gui_blank.setText(str(num_detected))
                FLAG_A = FLAG_B = [0, 0, 0]

            if(FLAG_B[0] == 0):
                FLAG_A[1] = max(FLAG_A[1] -1, 0)

            if(FLAG_A[1] == 0):
                FLAG_A[0] = 0
        # print('Num_Detected = %d' %num_detected)



class MainWindow(QMainWindow):
    def __init__(self, widget):
        QMainWindow.__init__(self)
        self.setWindowTitle('GUI')
        self.setCentralWidget(widget)


class Widget(QWidget):
    def __init__(self):
        QWidget.__init__(self)

        # left elements
        self.start = QPushButton('START')
        self.stop = QPushButton('STOP')
        self.text = QLabel("Num_Dectected")
        self.result = QLineEdit()

        self.left = QVBoxLayout()
        self.left.addWidget(self.start)
        self.left.addWidget(self.stop)
        self.left.addWidget(self.text)
        self.left.addWidget(self.result)

        # layout
        self.layout = QHBoxLayout()
        self.layout.addLayout(self.left)
        self.setLayout(self.layout)

        # functions
        self.start.clicked.connect(self.flow_start)
        self.stop.clicked.connect(self.flow_stop)
 

    @Slot()
    def flow_start(self):
        global the_vx_ifc    
        print('streaming...')
        the_vx_ifc.write('STREAM ON')
        
        the_threads = []
        # queue_drops = queue.Queue()
        queue_data = queue.Queue()
        queue_vals = queue.Queue()    
        for queue_func, queue_args in [(fill_queue, (the_udp_socket, queue_data, bytes_per_pkt+4)),    
                                       (empty_queue, (queue_data, queue_vals, bytes_per_pkt, fmt_unpk, fmt_live_printing, s_channels)),
                                       (event_detect, (queue_vals, threshold, num_detected, self.result))]:   
            the_threads.append(threading.Thread(target=queue_func, args=queue_args))
            the_threads[-1].start()


    @Slot()
    def flow_stop(self):
        print('Stopped Streaming ...')
        the_vx_ifc.write('STREAM OFF')        
 

def main():
    dut_add = '192.168.1.101'
    dut_port = 1865
    f_rate_req = 1e4 # sample rate that host wants. Actual rate will be below this
    # global duration_stream
    global s_channels
    # duration_stream = 5
    # fname = 'C:\\Users\\24483\\Desktop\\test.csv'
    s_channels = 'X'
    lst_vars_allowed = ['X', 'XY', 'RT', 'XYRT']
    b_integers = 0
    global bytes_per_pkt
    bytes_per_pkt = [1024, 512, 256, 128][0]    

    open_interfaces(dut_add, dut_port)

    global fmt_unpk
    global fmt_live_printing
    if b_integers: # 16 bit int
        fmt_unpk = '>%dh'%(bytes_per_pkt//2)          
        fmt_live_printing = '%12d'*len(s_channels)     
    else: # 32 bit float
        fmt_unpk = '>%df'%(bytes_per_pkt//4)
        fmt_live_printing = '%12.6f'*len(s_channels)
    
    global threshold
    global num_detected
    threshold = 380
    num_detected = 0

    app = QApplication([])
    widget = Widget()
    window = MainWindow(widget)
    window.show()    
    app.exec_()
    cleanup_ifcs()


if __name__ == '__main__':
    main()
