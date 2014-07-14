# Licensed under an MIT open source license - see LICENSE


'''
Test functions for PSpec
'''

from unittest import TestCase

import numpy as np
import numpy.testing as npt
import copy

from ..statistics import PowerSpectrum, PSpec_Distance
from ._testing_data import \
    dataset1, dataset2, computed_data, computed_distances


class testPSpec(TestCase):

    def setUp(self):
        self.dataset1 = dataset1
        self.dataset2 = dataset2

    def test_PSpec_method(self):
        self.tester = \
            PowerSpectrum(dataset1["integrated_intensity"][0],
                          dataset1["integrated_intensity"][1],
                          dataset1["integrated_intensity_error"][0] ** 2.)
        self.tester.run()
        assert np.allclose(self.tester.ps1D, computed_data['pspec_val'])

    def test_PSpec_distance(self):
        self.tester_dist = \
            PSpec_Distance(dataset1["integrated_intensity"],
                           dataset2["integrated_intensity"],
                           weights1=dataset1["integrated_intensity_error"][0] ** 2.,
                           weights2=dataset2["integrated_intensity_error"][0] ** 2.)
        self.tester_dist.distance_metric()

        npt.assert_almost_equal(self.tester_dist.distance,
                                computed_distances['pspec_distance'])
