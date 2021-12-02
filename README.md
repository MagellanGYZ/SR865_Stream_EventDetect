# SR865_Stream_EventDetect

This project contains one python file: main.py, which streams data from Lock-in Amplifier SR865A (product of Stanford Research System), and detect the event with specified pattern (like a pulse or sine wave).

The streaming part was modified from the project by Bob (you can find it here https://github.com/BobBaylor/stream), it will be very helpful to read it before using this project because more config information is provided there, and it'll be easier for you to develop your own program based on that. If you just need to capture data, which means you don't need to detect event, use the script by Bob is enough.

Tested on python 3.9.7 for Windows.
Besides basic python environment, there are some modules you need to install first to run this main.py: PySide2, vxi11. Both of them can be installed by pip or conda.
A stable connection between the Amplifier and your computer is also needed. You can run the script by Bob (the address is given above) to see if you can accept the number of package dropped.
