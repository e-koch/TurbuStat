
from astropy.io import fits
import astropy.units as u
import numpy as np
from astropy.wcs import WCS

from ..io import input_data


class BaseStatisticMixIn(object):
    """
    Common properties to all statistics
    """

    # Disable this flag when a statistic does not need a header
    need_header_flag = True

    # Disable this when the data property will not be used.
    no_data_flag = False

    @property
    def header(self):
        return self._header

    @header.setter
    def header(self, input_hdr):

        if not self.need_header_flag:
            input_hdr = None

        elif not isinstance(input_hdr, fits.header.Header):
            raise TypeError("The header must be a"
                            " astropy.io.fits.header.Header.")

        self._header = input_hdr

    @property
    def _wcs(self):
        if not hasattr(self, "_header"):
            raise AttributeError("No header was found.")

        return WCS(self.header)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, values):

        if self.no_data_flag:
            values = None

        elif not isinstance(values, np.ndarray):
            raise TypeError("Data is not a numpy array.")

        self._data = values

    def input_data_header(self, data, header):
        '''
        Check if the header is given separately from the data type.
        '''

        if header is not None:
            self.data = input_data(data, no_header=True)
            self.header = header
        else:
            self.data, self.header = input_data(data)

    @property
    def _angular_equiv(self):
        if not hasattr(self, "_header"):
            raise AttributeError("No header has not been given.")

        return [(u.pix, u.deg, lambda x: x * float(self._ang_size.value),
                lambda x: x / float(self._ang_size.value))]

    @property
    def _ang_size(self):
        if not hasattr(self, "_header"):
            raise AttributeError("No header has not been given.")

        return np.abs(self.header["CDELT2"]) * u.Unit(self._wcs.wcs.cunit[1])

    @property
    def distance(self):
        if not hasattr(self, "_header"):
            raise AttributeError("No header has not been given. Cannot make"
                                 " use of distance.")

        if not hasattr(self, "_distance"):
            raise AttributeError("No distance has not been given.")

        return self._distance

    @distance.setter
    def distance(self, value):
        '''
        Value must be a quantity with a valid distance unit. Will keep the
        units given.
        '''

        if not isinstance(value, u.Quantity):
            raise TypeError("Value for distance must an astropy Quantity.")

        if not value.unit.is_equivalent(u.pc):
            raise u.UnitConversionError("Given unit ({}) is not a valid unit"
                                        " of distance.".format(value.unit))

        if not value.isscalar:
            raise TypeError("Distance must be a scalar quantity.")

        self._distance = value

    @property
    def _physical_size(self):
        if not hasattr(self, "_distance"):
            raise AttributeError("No distance has not been given.")

        return (self._ang_size *
                self.distance).to(self.distance.unit,
                                  equivalencies=u.dimensionless_angles())

    @property
    def _physical_equiv(self):
        if not hasattr(self, "_distance"):
            raise AttributeError("No distance has not been given.")

        return [(u.pix, self.distance.unit,
                lambda x: x * float(self._physical_size.value),
                lambda x: x / float(self._physical_size.value))]

    def _to_pixel(self, value):
        '''
        Convert from angular or physical scales to pixels.
        '''

        if not isinstance(value, u.Quantity):
            raise TypeError("value must be an astropy Quantity object.")

        # Angular converions
        if value.unit.is_equivalent(u.pix):
            return value
        elif value.unit.is_equivalent(u.deg):
            return value.to(u.pix, equivalencies=self._angular_equiv)
        elif value.unit.is_equivalent(u.pc):
            return value.to(u.pix, equivalencies=self._physical_equiv)
        else:
            raise u.UnitConversionError("value has units of {}. It must have "
                                        "an angular or physical unit."
                                        .format(value.unit))

    def _to_pixel_freq(self, value):
        '''
        Converts from angular or physical frequencies to the pixel frequency.
        '''

        return 1 / self._to_pixel(1 / value)

    def _to_angular(self, value, unit=u.deg):
        if not hasattr(self, "_header"):
            raise AttributeError("No header has not been given.")

        return value.to(unit, equivalencies=self._angular_equiv)

    def _to_physical(self, value, unit=u.pc):
        if not hasattr(self, "_distance"):
            raise AttributeError("No distance has not been given.")

        return value.to(unit, equivalencies=self._physical_equiv)

    def _spatial_unit_conversion(self, pixel_value, unit):
        '''
        Convert a value in pixel units to the given unit.
        '''

        if isinstance(unit, u.Quantity):
            unit = unit.unit

        if unit.is_equivalent(u.pix):
            return pixel_value
        elif unit.is_equivalent(u.deg):
            return self._to_angular(pixel_value, unit)
        elif unit.is_equivalent(u.pc):
            return self._to_physical(pixel_value, unit)
        else:
            raise u.UnitConversionError("unit must be an angular or physical"
                                        " unit.")

    def _spatial_freq_unit_conversion(self, pixel_value, unit):
        '''
        Same as _spatial_unit_converison, but handles the inverse units.

        Feed in as the inverse of the value, and then inverse again so that
        the unit conversions will work.
        '''

        return 1 / self._spatial_unit_conversion(1 / pixel_value, 1 / unit)

    def _has_spectral(self, raise_error=False):
        '''
        Test whether there is a spectral axis.
        '''
        axtypes = self._wcs.get_axis_types()

        types = [a['coordinate_type'] for a in axtypes]

        if 'spectral' not in types:
            if raise_error:
                raise ValueError("Header does not have spectral axis.")
            return False

        return True

    @property
    def _spectral_size(self):

        self._has_spectral(raise_error=True)

        spec = self._wcs.wcs.spec
        return np.abs(self._wcs.wcs.cdelt[spec]) * \
            u.Unit(self._wcs.wcs.cunit[spec])

    @property
    def spectral_equiv(self):
        return [(u.pix, self._spectral_size.unit,
                lambda x: x * float(self._spectral_size.value),
                lambda x: x / float(self._spectral_size.value))]

    def _to_spectral(self, value, unit):
        '''
        Convert to spectral unit to pixel, and in reverse.
        '''

        return value.to(unit, self.spectral_equiv)

    def _spectral_freq_unit_conversion(self, value, unit):
        '''
        Same as _spatial_unit_converison, but handles the inverse units.

        Feed in as the inverse of the value, and then inverse again so that
        the unit conversions will work.
        '''

        return 1 / self._to_spectral(1 / value, 1 / unit)
