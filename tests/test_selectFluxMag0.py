#
# LSST Data Management System
# Copyright 2008-2017 LSST Corporation.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#
from __future__ import absolute_import, division, print_function
"""Test lsst.obs.lsstSim.selectFluxMag0 and integration with pipe.tasks.scaleZeroPoint
"""
from builtins import object
import sys
import unittest

import numpy as np

import lsst.afw.geom as afwGeom
import lsst.afw.image as afwImage
import lsst.afw.math as afwMath
import lsst.daf.base

from lsst.daf.persistence import DbAuth
from lsst.obs.lsstSim.selectFluxMag0 import SelectLsstSimFluxMag0Task
from lsst.pipe.tasks.scaleZeroPoint import SpatialScaleZeroPointTask
import lsst.utils.tests


class WrapDataId(object):
    """A container for dataId that looks like dataRef to computeImageScaler()
    """

    def __init__(self, dataId):
        self.dataId = dataId


class ScaleLsstSimZeroPointTaskTestCase(unittest.TestCase):
    """A test case for ScaleLsstSimZeroPointTask
    """

    def setUp(self):
        """Initialize the DB connection.  Raise SkipTest if unable to access DB."""
        config = SpatialScaleZeroPointTask.ConfigClass()
        config.selectFluxMag0.retarget(SelectLsstSimFluxMag0Task)
        try:
            DbAuth.username(config.selectFluxMag0.host, str(config.selectFluxMag0.port)),
        except RuntimeError as e:
            reason = "Warning: did not find host=%s, port=%s in your db-auth file; or %s " \
                     "skipping unit tests" % \
                     (config.selectFluxMag0.host, str(config.selectFluxMag0.port), e)
            raise unittest.SkipTest(reason)

    def makeTestExposure(self, xNumPix, yNumPix):
        """
        Create and return an exposure that is completely covered by the database: test_select_lsst_images
        """
        metadata = lsst.daf.base.PropertySet()
        metadata.set("NAXIS", 2)
        metadata.set("RADECSYS", "ICRS")
        metadata.set("EQUINOX", 2000.)
        metadata.setDouble("CRVAL1", 60.000000000000)
        metadata.setDouble("CRVAL2", 10.812316963572)
        metadata.setDouble("CRPIX1", 700000.00000000)
        metadata.setDouble("CRPIX2", 601345.00000000)
        metadata.set("CTYPE1", "RA---STG")
        metadata.set("CTYPE2", "DEC--STG")
        metadata.setDouble("CD1_1", -5.5555555555556e-05)
        metadata.setDouble("CD1_2", 0.0000000000000)
        metadata.setDouble("CD2_2", 5.5555555555556e-05)
        metadata.setDouble("CD2_1", 0.0000000000000)
        metadata.set("CUNIT1", "deg")
        metadata.set("CUNIT2", "deg")
        # exposure needs a wcs and a bbox
        wcs = afwGeom.makeSkyWcs(metadata)
        bbox = afwGeom.Box2I(afwGeom.Point2I(327750, 235750), afwGeom.Extent2I(xNumPix, yNumPix))
        exposure = afwImage.ExposureF(bbox, wcs)
        mi = exposure.getMaskedImage()
        mi.set(1.0)
        mi.getVariance().set(1.0)
        return exposure

    def testSelectFluxMag0(self):
        """Test SelectFluxMag0"""
        config = SelectLsstSimFluxMag0Task.ConfigClass()
        config.database = "test_select_lsst_images"
        task = SelectLsstSimFluxMag0Task(config=config)
        visit = 865990051
        dataId = {'visit': visit}
        fmInfoStruct = task.run(dataId)
        fmInfoList = fmInfoStruct.fluxMagInfoList
        self.assertEqual(sum([1 for fmInfo in fmInfoList if fmInfo.dataId['visit'] == visit]),
                         len(fmInfoList))

    def testScaleZeroPoint(self):
        """Test integration of pipe.tasks.scaleZeroPoint and obs.lsstSim.selectFluxMag0"""

        ZEROPOINT = 27
        self.sctrl = afwMath.StatisticsControl()
        self.sctrl.setNanSafe(True)

        config = SpatialScaleZeroPointTask.ConfigClass()
        config.zeroPoint = ZEROPOINT
        config.interpStyle = "CONSTANT"
        config.selectFluxMag0.retarget(SelectLsstSimFluxMag0Task)
        config.selectFluxMag0.database = "test_select_lsst_images"
        zpScaler = SpatialScaleZeroPointTask(config=config)

        """ Note: this order does not properly retarget
        zpScaler = ScaleZeroPointTask()
        zpScaler.config.doInterpScale = True
        zpScaler.config.zeroPoint = ZEROPOINT
        zpScaler.config.interpStyle = "CONSTANT"
        zpScaler.config.selectFluxMag0.retarget(SelectLsstSimFluxMag0Task)
        zpScaler.config.selectFluxMag0.database = "test_select_lsst_images"
        """

        outCalib = zpScaler.getCalib()
        self.assertAlmostEqual(outCalib.getMagnitude(1.0), ZEROPOINT)

        exposure = self.makeTestExposure(10, 10)
        # create dataId for exposure. Visit is only field needed. Others ignored.
        exposureId = {'ignore_fake_key': 1234, 'visit': 882820621}

        # API for computImageScale() takes a dataRef not a dataId.
        exposureFakeDataRef = WrapDataId(exposureId)
        # test methods: computeImageScale(), scaleMaskedImage(), getInterpImage()
        imageScaler = zpScaler.computeImageScaler(exposure, exposureFakeDataRef)
        scaleFactorIm = imageScaler.getInterpImage(exposure.getBBox())
        predScale = np.mean(imageScaler._scaleList)  # 0.011125492863357

        self.assertAlmostEqual(afwMath.makeStatistics(scaleFactorIm, afwMath.VARIANCE, self.sctrl).getValue(),
                               0.0)
        self.assertAlmostEqual(afwMath.makeStatistics(scaleFactorIm, afwMath.MEAN, self.sctrl).getValue(),
                               predScale)

        mi = exposure.getMaskedImage()
        imageScaler.scaleMaskedImage(mi)
        self.assertAlmostEqual(mi.get(1, 1)[0], predScale)  # check image plane scaled
        self.assertAlmostEqual(mi.get(1, 1)[2], predScale**2)  # check variance plane scaled

        exposure.setCalib(zpScaler.getCalib())
        self.assertAlmostEqual(exposure.getCalib().getFlux(ZEROPOINT), 1.0)

    def makeCalib(self, zeroPoint):
        calib = afwImage.Calib()
        fluxMag0 = 10**(0.4 * zeroPoint)
        calib.setFluxMag0(fluxMag0, 1.0)
        return calib


class MemoryTester(lsst.utils.tests.MemoryTestCase):
    pass


def setup_module(module):
    lsst.utils.tests.init()


if __name__ == "__main__":
    setup_module(sys.modules[__name__])
    unittest.main()
