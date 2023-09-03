# SR865_Stream_EventDetect

The main.py should be used with Lock-in Amplifier SR865A (product of Stanford Research System, check [product's page](https://www.thinksrs.com/products/sr865a.html) to make sure it's the right device). This program streams data from SR865 and detect events with specified pattern (like a pulse or sine wave).

The stream part was modified from [Bob's project](https://github.com/BobBaylor/stream), it will be very helpful to go through it before my project because it provides more config information, especially when you need to develop your own program.

* Tested on python 3.9.7 on Windows.
* Modules you need to install: PySide2, vxi11.
* A stable connection between the Amplifier and your computer is necessary. You can run the script by Bob first to see if you can accept the number of package dropped.
