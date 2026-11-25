import unittest
import numpy as np
from scripts.subject_motion_qa import motion_metrics, evaluate

class SubjectMotionQATests(unittest.TestCase):
    def test_static_frames_fail(self):
        frames=np.full((8,180,100),120,dtype=np.uint8)
        result=evaluate(motion_metrics(frames))
        self.assertFalse(result["passed"])
        self.assertTrue(any("motion too low" in p for p in result["failures"]))

    def test_subject_motion_with_static_background_passes(self):
        frames=np.full((8,180,100),120,dtype=np.uint8)
        for i in range(8):
            # Simulate a moving subject inside the central ROI, leaving outer bands fixed.
            x=20+i*4
            frames[i,55:125,x:x+20]=255
        result=evaluate(motion_metrics(frames),minimum_delta=0.35)
        self.assertGreater(result["subject_roi_mean_delta"],0.35)
        self.assertTrue(result["subject_motion_dominates"])

    def test_background_only_motion_is_rejected(self):
        frames=np.zeros((8,180,100),dtype=np.uint8)
        for i in range(8):
            frames[i,:,:]=i*20
        result=evaluate(motion_metrics(frames))
        self.assertFalse(result["passed"])
        self.assertFalse(result["subject_motion_dominates"])

if __name__=="__main__": unittest.main()
