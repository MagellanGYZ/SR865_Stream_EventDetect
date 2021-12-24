# SR865_Stream_EventDetect

This project contains one python file: main.py, which should be used with Lock-in Amplifier SR865A (product of Stanford Research System, check https://www.thinksrs.com/products/sr865a.html to make sure it's the device you're using). This program streams data from SR865 and detect events with specified pattern (like a pulse or sine wave).

The streaming part was modified from the project by Bob (you can find it here https://github.com/BobBaylor/stream), it will be very helpful to read it before using this project because more config information is provided there. It's necessary for you to check that if you need to develop your own program. If you just need to capture data, which means you don't need to detect event, use the script by Bob or executable file on product's page is enough.


Tested on python 3.9.7 for Windows.
Besides basic python environment, there are some modules you need to install first to run this main.py: PySide2, vxi11. Both of them can be installed via pip or conda.
A stable connection between the Amplifier and your computer is also needed. You can run the script by Bob (the address is given above) to see if you can accept the number of package dropped.
