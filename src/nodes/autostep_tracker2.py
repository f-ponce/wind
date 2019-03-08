#!/usr/bin/env python
from __future__ import print_function

import sys
import time
import rospy
import threading
import numpy as np
import math

from std_msgs.msg import Header
from magnotether.msg import MsgAngleData

from autostep_proxy import AutostepProxy
from autostep_ros.msg import TrackingData

#autostep = AutostepProxy()

class AngleAccumulator(object):

    def __init__(self):
        self.value = None
        self.is_first = True
        
    def reset(self):
        self.is_first = True
                
    def update(self,angle):
        if self.is_first:
            self.value = angle  
            self.is_first = False
        else:
            delta_theta = smallestSignedAngleBetween(self.value, angle)
            self.value = self.value + delta_theta
        return self.value
        
class LowpassFilter(object):

    def __init__(self, fcut):
        self.fcut = fcut
        self.is_first = True
        self.value = 0.0

    @property
    def time_constant(self):
        rc = 1.0/(2.0*math.pi*self.fcut)
        return rc

    def update(self,x,dt):
        if self.is_first:
            self.value = x
            self.is_first = False
        else:
            coeff_0 = dt/(self.time_constant + dt)
            coeff_1 = 1.0 - coeff_0 
            self.value = coeff_0*x + coeff_1*self.value

    def reset(self):
        self.is_first = True
        
        
class MyKalmanFilter(object):

    def __init__(self):
        
        #kf parameters
        dt = 1.0/30.0
        a = 0.1
        Q_vec = [a,a/dt,a/dt**2]
    
        Q = np.array([[Q_vec[0], 0, 0], 
              [0, Q_vec[1], 0],
              [0, 0, Q_vec[2]]])
    
        R = np.zeros((1, 1))
        np.fill_diagonal(R, 1)

        P1 = np.zeros((3, 3))
        np.fill_diagonal(P1, 1)

        x1 = np.zeros((1,3))
        x1 = x1[0]

        F = np.array([[1, dt, 0.5*dt**2], 
            [0, 1, dt],
            [0, 0, 1]])
    
        lx = len(Q)
        H1 = np.zeros((3, 3))
        np.fill_diagonal(H1, 1)
    
        self.H = H1
        self.x = x1
        self.P = P1
        self.F = F
        self.Q = Q
        self.R = R
        self.lx = lx
        
    def get_velocity(self,item):

        Y = [item,0,0]
        self.x = self.F.dot(self.x)
    
        self.P = (self.F.dot(self.P)).dot(np.transpose(self.F))+self.Q

        self.k1 = self.P.dot(np.transpose(self.H))
        self.k2 = (self.H.dot(self.P)).dot(np.transpose(self.H))+self.R
        self.K = np.transpose(np.linalg.solve(np.transpose(self.k2),np.transpose(self.k1)))
    
        self.x = self.x + self.K.dot(Y - (self.H.dot(self.x)))
    
        lx_1 = np.zeros((self.lx,self.lx))
        np.fill_diagonal(lx_1, 1)
        self.P = (lx_1-self.K.dot(self.H)).dot(self.P)
        #eliminating velocity 
        return 0 #self.x
        
       
class AngleFixer(object):
    
    def __init__(self, size=30):
        self.size = size
        self.data = []

    def fix_data(self,item):
        self.data.append(item)
        if len(self.data) > self.size:
            self.mean_angle = np.mean(self.data)
            self.data.pop(0)
            if (self.data[-1]-self.mean_angle)>=130:
                self.data[-1] = self.data[-1]-180.0
                return self.data[-1]
            elif (self.data[-1]-self.mean_angle)<=-130:
                self.data[-1] = self.data[-1]+180.0
                return self.data[-1]
            else:
                return self.data[-1]
        else:
            return self.data[-1]


class AutostepTracker(object):

    def __init__(self):

        rospy.init_node('autosteptracker')
        self.angles = rospy.Subscriber('/angle_data', MsgAngleData,self.get_unwrapped_angle_callback)
        self.tracking_data_pub = rospy.Publisher('tracking_data', TrackingData, queue_size=10)

        self.angle_accumulator = AngleAccumulator()
        self.kf = MyKalmanFilter()
        self.af = AngleFixer()
        self.lowpass = LowpassFilter(10.0)
        
        self.lock = threading.Lock()

        self.new_data = False
        self.unwrapped_angle = 0
        self.filt_angle = 0.0
        self.rot_vel = 0

    def get_unwrapped_angle_callback(self, data): 
        with self.lock:
            self.unwrapped_angle = self.angle_accumulator.update(data.angle)
            self.fixedangle = self.af.fix_data(self.unwrapped_angle)
            #low pass filter data
            dt = 1.0/30.0
            self.lowpass.update(self.fixedangle,dt)
            vel = self.kf.get_velocity(self.unwrapped_angle)
            self.filt_angle = self.lowpass.value #x_filt[0]
            self.rot_vel = vel
            self.new_data = True
                  
    def run(self): 
        while not rospy.is_shutdown():
            header = Header()
            header.stamp = rospy.Time.now()
            with self.lock:
                unwrapped_angle = self.filt_angle
                rot_vel = self.rot_vel
                new_data = self.new_data
                self.new_data = False
            if new_data:
                rospy.logwarn(unwrapped_angle)
                self.tracking_data_pub.publish(TrackingData(header,unwrapped_angle,rot_vel))

           
# Utility functions
# -------------------------------------------------------------------------------------------------  
def smallestSignedAngleBetween(theta1, theta2):
    x = float(np.radians(theta1))
    y = float(np.radians(theta2))
    a = np.arctan2(np.sin(y-x), np.cos(y-x))
    a = (np.degrees(a))
    return a
# -------------------------------------------------------------------------------------------------

if __name__ == '__main__':
    autosteptracker = AutostepTracker()
    autosteptracker.run()

