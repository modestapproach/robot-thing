# SO-101 model

`so101_new_calib.xml`, `so101_new_calib.urdf`, `joints_properties.xml` and `assets/*.stl` are copied unmodified from
[TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) (`Simulation/SO101`),
licensed under the Apache License 2.0. The "new calib" variant matches LeRobot's calibration
convention (joint zero at the middle of each range). AutoLab's scene (`simulation/so101/scene.py`)
includes this file unchanged and adds the calibration board, markers and cameras around it.
