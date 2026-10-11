# SO-101 model

`so101_new_calib.xml`, `so101_new_calib.urdf`, `joints_properties.xml` and `assets/*.stl` are copied unmodified from
[TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) (`Simulation/SO101`),
licensed under the Apache License 2.0. The "new calib" variant matches LeRobot's calibration
convention (joint zero at the middle of each range). AutoLab's scene (`simulation/so101/scene.py`)
includes this file unchanged and adds the calibration board, markers and cameras around it.

`menagerie_so101.xml` is copied unmodified from
[google-deepmind/mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie) (`robotstudio_so101`,
Apache License 2.0), together with the five extra meshes it references
(`moving_jaw_so101_gripper*`, `wrist_roll_follower_so101_gripper_part0_v1.stl`,
`wrist_roll_follower_so101_camera_mount.stl`). Its link kinematics are identical to `so101_new_calib.xml`
(0.0 mm over random poses); AutoLab uses it only for its primitive collision geometry. Note its `gripperframe`
site sits 19.9 mm from the official one (between the jaws at one opening); AutoLab's tool point is the official
`gripperframe`, at the fixed-jaw tip.
