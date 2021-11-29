import math
import socket
import sys
import time
import vxi11
import docopt
import queue
import threading
import numpy as np
from tkinter import _flatten
from struct import unpack_from

from PySide2.QtWidgets import (QApplication, QPushButton, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel)
from PySide2.QtCore import Slot
import pyqtgraph as pg


USE_STR = """
 --Stream Data from an SR865 to a file--
 Usage:
  stream  [--address=<A>] [--length=<L>] [--port=<P>] [--duration=<D>] [--vars=<V>] [--rate=<R>] [--silent] [--thread] [--file=<F>] [--ints]
  stream -h | --help

 Options:
  -a --address <A>     IP address of SR865 [default: 192.168.1.102]
  -d --duration <D>    How long to transfer in seconds [default: 3]
  -f --file <F>        Name for file output. No file output without a file name.
  -h --help            Show this screen
  -i --ints            Data in 16-bit ints instead of 32-bit floats
  -l --length <L>      Packet length enum (0 to 3) [default: 0]
  -p --port <P>        UDP Port [default: 1865]
  -r --rate <R>        Sample rate per second. Actual will be less and depends on filter settings [default: 1e4]
  -s --silent          Refrain from printing packet count and data until complete
  -t --thread          Decouple output from ethernet stream using threads
  -v --vars <V>        Lock-in variables to stream [default: RT]    XY, RT, or XYRT are also allowed
    """

the_udp_socket = None     
the_vx_ifc = None      


def show_status(left_text='', right_text=''):
    print('\n %-30s %48s\r'%(left_text[:30], right_text[:48]), end=' ')
   

def show_results(count_dropped, pkts_num, lst_dropped, count_samples):
    """ print indicating OK, or some dropped packets"""
    if count_dropped:
        print('\nFAIL: Dropped %d out of %d packets in %d gaps:'%(count_dropped, pkts_num, len(lst_dropped)), end=' ')   
        print(''.join('%d at %d, '%(x[0], x[1]) for x in lst_dropped[:5]))
    else:
        print('\npass: No packets dropped out of %d. %d samples captured.'%(pkts_num, count_samples))   


def open_interfaces(ipadd, port):
    global the_udp_socket   #pylint: disable=global-statement, invalid-name
    global the_vx_ifc       #pylint: disable=global-statement, invalid-name
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
    print("\n cleaning up...", end=' ')
    the_vx_ifc.write('STREAM OFF')
    the_vx_ifc.close()
    the_udp_socket.close()
    print('connections closed\n')


def fill_queue(sock_udp, q_data, pkts_num, bytes_per_pkt):
    for _ in range(pkts_num):
        buf, _ = sock_udp.recvfrom(bytes_per_pkt)
        q_data.put(buf)


def empty_queue(q_data, q_drop, q_vals, pkts_num, bytes_per_pkt, fmt_unpk, s_prt_fmt, s_channels, bshow_status): #pylint: disable=too-many-arguments, too-many-locals, line-too-long

    prev_pkt_cntr = None                         # init the packet counter
    lst_dropped = []                            # make a list of any missing packets
    count_dropped = 0
    lst_stream = []
    count_vars = len(s_channels)
    for i in range(pkts_num):
        buf = q_data.get()
        vals, _, n_dropped, prev_pkt_cntr = process_packet(buf, fmt_unpk, prev_pkt_cntr)
        q_vals.put(vals)
        lst_stream += [vals]
        if n_dropped:
            lst_dropped += [(n_dropped, i)]
        count_dropped += n_dropped
        # if bshow_status:
        #     # show_status('dropped %4d of %d'%(count_dropped, i+1), s_prt_fmt%tuple(lst_stream[-1][-count_vars:]))   
        #     print('dropped %4d of %d'%(count_dropped, i+1))

    show_results(count_dropped, pkts_num, lst_dropped, pkts_num*bytes_per_pkt/(4*count_vars))    


def event_detect(total_pkts, q_vals, thresh, num_detected, gui_blank):
    # FLAG_A=FLAG_B=FLAG_C=FLAG_D=[0,0,0]
    FLAG_A=FLAG_B=[0,0,0]
    for _ in range(total_pkts):
        print(num_detected)
        vals = q_vals.get()
        print(num_detected)
        for i in length(vals):
            if( val[i] >= thresh & vals[i-1] <= thresh & FLAG_A[1]==0 ):
                FLAG_A = [1, i, 10*width]
            if( val[i] <= thresh & vals[i-1] >= thresh & FLAG_A[1]==1 & FLAG_B[1]==0 ):
                FLAG_B = [1, i, 0]
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

            if(FLAG_B(0) == 0):
                FLAG_A[2] = max(FLAG_A[2] -1, 0)

            if(FLAG_A[2] == 0):
                FLAG_A[0] = 0

    cleanup_ifcs()


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
        show_status('streaming...')
        the_vx_ifc.write('STREAM ON')
        
        the_threads = []
        queue_drops = queue.Queue()
        queue_data = queue.Queue()
        queue_vals = queue.Queue()            # decouple the printing/saving from the UDP socket
        for queue_func, queue_args in [(fill_queue, (the_udp_socket, queue_data, total_pkts, bytes_per_pkt+4)),    
                                       (empty_queue, (queue_data, queue_vals, queue_drops, total_pkts, bytes_per_pkt, fmt_unpk, fmt_live_printing, s_channels, bshow_status)),
                                       (event_detect, (total_pkts, queue_vals, threshold, num_detected, self.result))]:   
            the_threads.append(threading.Thread(target=queue_func, args=queue_args))
            # the_threads[-1].setDaemon(True)
            the_threads[-1].start()
        s_no_printing = '' if bshow_status else 'silently'
        print('threads started %s\n'%s_no_printing)
        the_threads[0].join(duration_stream+2)    # time out 2 seconds after the expected duration
        the_threads[1].join(duration_stream*2)    # time out 2x the duration more
        the_threads[2].join(duration_stream*2) # idk what to set, just choose the longer one
        print('threads done')


    @Slot()
    def flow_stop(self):
        show_status('Stopped Streaming ...')
        the_vx_ifc.write('STREAM OFF')        


def main(opts):

    dut_add = opts['--address']
    dut_port = int(opts['--port'])
    f_rate_req = float(opts['--rate']) # sample rate that host wants. Actual rate will be below this
    idx_pkt_len = int(opts['--length']) # select the packet size from 1024 to 128 bytes per packet
    global duration_stream
    global bshow_status
    global s_channels
    duration_stream = float(opts['--duration'])
    bshow_status = not opts['--silent']
    fname = opts['--file']
    s_channels = str(opts['--vars']) # what to stream. X, XY, RT, or XYRT allowed
    lst_vars_allowed = ['X', 'XY', 'RT', 'XYRT']
    b_integers = opts['--ints'] # 以下两个参数都是在缺省的状态下默认是0？
    # b_use_threads = opts['--thread']

    open_interfaces(dut_add, dut_port)
    global f_total_samples
    global bytes_per_pkt
    global total_pkts    
    f_total_samples = duration_stream * dut_config(the_vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers)
    bytes_per_pkt = [1024, 512, 256, 128][idx_pkt_len]
    total_pkts = int(math.ceil(f_total_samples*4*len(s_channels)/bytes_per_pkt))# 要获取的packet数。乘以4是默认是浮点数吗？
    print(total_pkts)

    global fmt_unpk
    global fmt_live_printing
    if b_integers: # 16 bit int
        fmt_unpk = '>%dh'%(bytes_per_pkt//2)            # create an unpacking format string.
        fmt_live_printing = '%12d'*len(s_channels)        # create status format string.
    else: # 32 bit float
        fmt_unpk = '>%df'%(bytes_per_pkt//4)
        fmt_live_printing = '%12.6f'*len(s_channels)
    
    global threshold
    global num_detected
    threshold = 8e-6
    num_detected = 0

    app = QApplication([])
    widget = Widget()
    window = MainWindow(widget)
    window.show()    
    sys.exit(app.exec_())
    cleanup_ifcs()


if __name__ == '__main__':
    options = docopt.docopt(USE_STR, version='0.0.2')
    main(options)
